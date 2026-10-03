import Darwin
import Foundation

@main
struct BootstrapChecks {
    @MainActor static func main() async {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent("chronos-bootstrap-" + UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: root) }
        do {
            guard CommandLine.arguments.count == 3 else { throw CommandError.invalid("Pass catalog and bridge paths") }
            let catalogURL = URL(fileURLWithPath: CommandLine.arguments[1])
            let bridge = URL(fileURLWithPath: CommandLine.arguments[2])
            let manager = RuntimeManager(root: root, catalogURL: catalogURL)
            let first = try await manager.synchronize(bridge: bridge, status: { print($0) })
            guard let candidate = first.candidate, let active = ActiveRuntime.read(at: root),
                  candidate.pythonPath.hasPrefix(root.path),
                  FileManager.default.fileExists(atPath: root.appendingPathComponent("python").path) else {
                throw CommandError.invalid("Fresh private Python bootstrap failed")
            }
            let second = try await manager.synchronize(bridge: bridge)
            guard second.candidate == candidate else { throw CommandError.invalid("Unchanged CLI was reinstalled") }
            _ = try await manager.synchronize(bridge: bridge, force: true)
            let restored = try await manager.rollback(bridge: bridge)
            guard restored == candidate else { throw CommandError.invalid("Rollback did not restore the previous environment") }
            // An altered Python checksum must fail before activation and keep
            // the previous runtime. Wheel hashes are also matched against PyPI.
            var data = try JSONSerialization.jsonObject(with: Data(contentsOf: catalogURL)) as! [String: Any]
            var python = data["python"] as! [String: Any]
            python["sha256"] = String(repeating: "0", count: 64)
            data["python"] = python
            let broken = root.appendingPathComponent("bad-catalog.json")
            try JSONSerialization.data(withJSONObject: data).write(to: broken)
            let invalid = RuntimeManager(root: root, catalogURL: broken)
            do {
                _ = try await invalid.synchronize(bridge: bridge, force: true)
                throw CommandError.invalid("An invalid runtime checksum was accepted")
            } catch {
                guard error.localizedDescription.contains("checksum mismatch") else { throw error }
            }
            guard ActiveRuntime.read(at: root)?.environment == active.environment else {
                throw CommandError.invalid("Failed update replaced the active runtime")
            }
            // Reproduce a broken installed package in the disposable tree.
            // Launch checks must recover using a separate environment, and a
            // rollback to that broken package must never change the pointer.
            let runner = ProcessRunner()
            let response = await runner.run(executable: candidate.pythonPath, arguments: ["-I", "-B", bridge.path, "probe"],
                directory: root, environment: RuntimeDiscovery.environment(), timeout: 30)
            let probe = try JSONDecoder().decode(RuntimeProbe.self, from: Data(response.stdout.utf8))
            guard let package = probe.packagePath,
                  URL(fileURLWithPath: package).resolvingSymlinksInPath().path.hasPrefix(root.resolvingSymlinksInPath().path + "/") else {
                throw CommandError.invalid("Refusing to change a package outside the disposable bootstrap tree")
            }
            try Data("raise RuntimeError('simulated broken package')\n".utf8)
                .write(to: URL(fileURLWithPath: package).appendingPathComponent("__init__.py"))
            let repaired = try await manager.synchronize(bridge: bridge)
            guard repaired.candidate != nil, repaired.candidate != candidate, let working = ActiveRuntime.read(at: root) else {
                throw CommandError.invalid("Launch checks failed to repair the broken private CLI")
            }
            do {
                _ = try await manager.rollback(bridge: bridge)
                throw CommandError.invalid("Rollback accepted a broken previous copy")
            } catch {
                guard error.localizedDescription.contains("did not pass") else { throw error }
            }
            guard ActiveRuntime.read(at: root)?.environment == working.environment else {
                throw CommandError.invalid("Rejected rollback replaced the working CLI")
            }
            print("Fresh standalone bootstrap, reuse, repair, verified rollback, checksum failure and broken-copy recovery passed.")
        } catch {
            fputs("Bootstrap failed: \(error.localizedDescription)\n", stderr)
            exit(1)
        }
    }
}
