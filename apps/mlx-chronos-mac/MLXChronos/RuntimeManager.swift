import CryptoKit
import Darwin
import Foundation

struct ReleaseVersion: Comparable {
    let parts: [Int]
    init?(_ text: String) {
        let fields = text.split(separator: ".", omittingEmptySubsequences: false)
        guard (2...3).contains(fields.count), fields.allSatisfy({
            !$0.isEmpty && $0.allSatisfy(\.isNumber) && ($0 == "0" || !$0.hasPrefix("0"))
        }) else { return nil }
        let numbers = fields.compactMap { Int($0) }
        guard numbers.count == fields.count else { return nil }
        parts = numbers + Array(repeating: 0, count: 3 - numbers.count)
    }
    static func < (lhs: Self, rhs: Self) -> Bool { lhs.parts.lexicographicallyPrecedes(rhs.parts) }
}

struct AppRuntimeContract: Codable, Equatable {
    let apiVersion: Int
    let minimumAppVersion: String
    let requiredCapabilities: [String]
    let supportedCommands: [String]
    enum CodingKeys: String, CodingKey {
        case apiVersion = "api_version", minimumAppVersion = "minimum_app_version"
        case requiredCapabilities = "required_capabilities", supportedCommands = "supported_commands"
    }
    static func == (lhs: Self, rhs: Self) -> Bool {
        lhs.apiVersion == rhs.apiVersion && ReleaseVersion(lhs.minimumAppVersion) == ReleaseVersion(rhs.minimumAppVersion)
            && Set(lhs.requiredCapabilities) == Set(rhs.requiredCapabilities)
            && Set(lhs.supportedCommands) == Set(rhs.supportedCommands)
    }
}

enum AppRuntimePolicy {
    static var appVersion: String { Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "0.2.0" }
    static let capabilities: Set<String> = ["cli-options-v1", "snapshot-v1", "benchmark-json-v1", "thermal-foundation-v1", "command-safety-v1"]
    static let commands: Set<String> = ["run", "matrix", "context", "concurrency", "energy", "doctor", "validate", "models", "engines", "history", "compare", "submit", "upgrade", "wizard"]
    static func issue(_ contract: AppRuntimeContract, appVersion: String = appVersion) -> String? {
        guard let current = ReleaseVersion(appVersion), let required = ReleaseVersion(contract.minimumAppVersion) else {
            return "Compatibility metadata contains an invalid app version."
        }
        if current < required { return "Requires app \(contract.minimumAppVersion) or newer. Update the app first." }
        guard contract.apiVersion == 1, Set(contract.requiredCapabilities).count == contract.requiredCapabilities.count,
              Set(contract.supportedCommands).count == contract.supportedCommands.count,
              Set(contract.requiredCapabilities).isSubset(of: capabilities),
              !contract.supportedCommands.isEmpty, Set(contract.supportedCommands).isSubset(of: commands) else {
            return "Requires an interface or commands unsupported by this app. Update the app first."
        }
        return nil
    }
    static func validate(_ probe: RuntimeProbe, release: RuntimeRelease, expectedPrefix: String? = nil) throws {
        guard issue(release.contract) == nil, probe.ready, probe.thermalAvailable, probe.architecture == "arm64",
              probe.isVirtualenv, probe.packageOwned, probe.installer == "pip",
              expectedPrefix.map({ URL(fileURLWithPath: probe.prefix).standardizedFileURL.path == URL(fileURLWithPath: $0).standardizedFileURL.path }) ?? true,
              probe.packageVersion == release.version,
              probe.commands.allSatisfy({ release.contract.supportedCommands.contains($0.name)
                && $0.options.allSatisfy({ ["boolean", "integer", "number", "text", "repeat"].contains($0.kind) }) }),
              Set(probe.commands.map(\.name)) == Set(release.contract.supportedCommands),
              probe.appContract == release.contract || (probe.appContract == nil && release.allowLegacyBridge == true) else {
            throw CommandError.invalid("The downloaded CLI did not pass version, interface, command and thermal checks. The active copy was kept.")
        }
    }
}

struct RuntimeArtifact: Codable {
    let version: String
    let url: URL
    let sha256: String
}
struct RuntimeRelease: Codable {
    let version: String
    let url: URL
    let sha256: String
    let contract: AppRuntimeContract
    let allowLegacyBridge: Bool?
    enum CodingKeys: String, CodingKey { case version, url, sha256, contract; case allowLegacyBridge = "allow_legacy_bridge" }
}
struct RuntimePublication: Decodable {
    struct Digests: Decodable { let sha256: String }
    let url: URL
    let digests: Digests
    let yanked: Bool
}
struct RuntimeProject: Decodable {
    let releases: [String: [RuntimePublication]]
    var latestStable: String? {
        releases.keys.filter { ReleaseVersion($0) != nil && releases[$0]?.contains(where: { !$0.yanked }) == true }
            .max { ReleaseVersion($0)! < ReleaseVersion($1)! }
    }
}
struct RuntimeCatalog: Codable {
    let schema: Int
    let python: RuntimeArtifact
    let releases: [RuntimeRelease]
    func validate() throws {
        guard schema == 1, ReleaseVersion(python.version) != nil,
              python.url.scheme == "https", python.url.host == "github.com",
              python.url.path.hasPrefix("/astral-sh/python-build-standalone/releases/download/"),
              python.url.path.hasSuffix("aarch64-apple-darwin-install_only.tar.gz"), Self.validDigest(python.sha256),
              Set(releases.map(\.version)).count == releases.count,
              releases.allSatisfy({ ReleaseVersion($0.version) != nil && $0.url.scheme == "https"
                && $0.url.host == "files.pythonhosted.org" && $0.url.path.hasSuffix(".whl") && Self.validDigest($0.sha256) }) else {
            throw CommandError.invalid("Runtime catalog is invalid; automatic installation was skipped.")
        }
    }
    static func validDigest(_ value: String) -> Bool {
        value.count == 64 && value.allSatisfy { "0123456789abcdef".contains($0) }
    }
    func newestCompatible(published: Set<String>, appVersion: String) -> RuntimeRelease? {
        releases.filter { published.contains($0.version) && AppRuntimePolicy.issue($0.contract, appVersion: appVersion) == nil }
            .max { ReleaseVersion($0.version)! < ReleaseVersion($1.version)! }
    }
    func verifiedPublished(in project: RuntimeProject) -> Set<String> {
        // A catalog entry is eligible only while PyPI still publishes this
        // exact approved wheel. Empty releases and withdrawn wheels are skipped.
        Set(releases.filter { release in
            project.releases[release.version]?.contains(where: {
                !$0.yanked && $0.url == release.url && $0.digests.sha256 == release.sha256
            }) == true
        }.map(\.version))
    }
}

struct ActiveRuntime: Codable {
    let environment: String
    let previousEnvironment: String?
    let release: RuntimeRelease
    static func read(at root: URL) -> Self? {
        guard let data = try? Data(contentsOf: root.appendingPathComponent("active-runtime.json")), data.count < 100_000,
              let value = try? JSONDecoder().decode(Self.self, from: data), safeName(value.environment),
              value.previousEnvironment.map(safeName) ?? true else { return nil }
        return value
    }
    static func safeName(_ name: String) -> Bool {
        !name.isEmpty && name.count < 100 && name.allSatisfy { "abcdefghijklmnopqrstuvwxyz0123456789-".contains($0) }
    }
    func candidate(at root: URL) -> RuntimeCandidate {
        RuntimeCandidate(pythonPath: root.appendingPathComponent("managed-runtimes/\(environment)/bin/python").path)
    }
}

struct RuntimeSyncResult {
    let candidate: RuntimeCandidate?
    let notice: String
}

/// Downloads only explicitly approved artifacts, creates environments at their
/// final paths (venvs are not relocatable), and switches an atomic pointer only
/// after verification. The previous environment is retained for rollback.
@MainActor
final class RuntimeManager {
    nonisolated static let catalogURL = URL(string: "https://igurss.github.io/mlx-chronos/app-runtime.json")!
    private let root: URL
    private let session: URLSession
    private let catalogURL: URL
    private var runner: ProcessRunner?
    init(root: URL = RuntimeDiscovery.applicationDirectory, session: URLSession? = nil, catalogURL: URL = RuntimeManager.catalogURL) {
        self.root = root
        self.catalogURL = catalogURL
        let configuration = URLSessionConfiguration.ephemeral
        configuration.httpShouldSetCookies = false
        configuration.urlCache = nil
        configuration.timeoutIntervalForRequest = 30
        configuration.timeoutIntervalForResource = 600
        self.session = session ?? URLSession(configuration: configuration)
    }
    func stop() { runner?.stop() }

    func synchronize(bridge: URL, force: Bool = false,
                     status: (String) -> Void = { _ in }, log: @escaping @Sendable (String) -> Void = { _ in }) async throws -> RuntimeSyncResult {
        #if !arch(arm64)
        throw CommandError.invalid("Automatic runtime setup requires Apple Silicon. Select an external Python instead.")
        #endif
        status("Checking compatible mlx-chronos releases")
        let catalog = try JSONDecoder().decode(RuntimeCatalog.self, from: await metadata(catalogURL))
        try catalog.validate()
        let project = try JSONDecoder().decode(RuntimeProject.self, from: await metadata(URL(string: "https://pypi.org/pypi/mlx-chronos/json")!))
        guard let latest = project.latestStable else { throw CommandError.invalid("PyPI has no stable published CLI releases.") }
        guard let release = catalog.newestCompatible(published: catalog.verifiedPublished(in: project), appVersion: AppRuntimePolicy.appVersion) else {
            let reason = catalog.releases.first(where: { $0.version == latest }).flatMap { AppRuntimePolicy.issue($0.contract) }
            return RuntimeSyncResult(candidate: nil, notice: reason ?? "No verified compatible CLI release is available. Automatic installation was skipped.")
        }
        let latestNotice: String
        if let newest = ReleaseVersion(latest), let chosen = ReleaseVersion(release.version), newest > chosen {
            latestNotice = catalog.releases.first(where: { $0.version == latest }).flatMap { AppRuntimePolicy.issue($0.contract) }
                ?? "CLI \(latest) has no verified compatibility metadata; keeping compatible CLI \(release.version)."
        } else { latestNotice = "App-managed CLI \(release.version) is up to date." }
        let fm = FileManager.default
        try ensureDirectory(root)
        let lock = try RuntimeFileLock(root.appendingPathComponent("runtime-update.lock"))
        defer { lock.close() }
        try rejectSymbolicLink(root.appendingPathComponent("managed-runtimes"))
        let active = ActiveRuntime.read(at: root)
        if let active, fm.isExecutableFile(atPath: active.candidate(at: root).pythonPath) {
            // Never silently downgrade a functioning copy, even when a catalog
            // is stale or a published release has been withdrawn.
            if !force, let installed = ReleaseVersion(active.release.version), installed >= ReleaseVersion(release.version)! {
                try rejectSymbolicLink(root.appendingPathComponent("managed-runtimes/\(active.environment)"))
                do {
                    let probe = try await probe(active.candidate(at: root), bridge: bridge, log: log)
                    try AppRuntimePolicy.validate(probe, release: active.release, expectedPrefix: root.appendingPathComponent("managed-runtimes/\(active.environment)").path)
                    let notice = active.release.version == release.version ? latestNotice
                        : "Keeping installed compatible CLI \(active.release.version). " + latestNotice
                    return RuntimeSyncResult(candidate: active.candidate(at: root), notice: notice)
                } catch is CancellationError { throw CancellationError() }
                catch { log("Existing private CLI failed verification; preparing a separate compatible replacement.\n") }
            }
        }
        let runtimes = root.appendingPathComponent("managed-runtimes", isDirectory: true)
        try ensureDirectory(runtimes)
        let name = UUID().uuidString.lowercased()
        let environment = runtimes.appendingPathComponent(name, isDirectory: true)
        var activated = false
        defer { if !activated { try? fm.removeItem(at: environment) } }
        let python = try await preparePython(catalog.python, status: status, log: log)
        status("Preparing a separate CLI environment")
        _ = try await command(python, ["-I", "-B", bridge.path, "venv", environment.path], log: log)
        let candidate = RuntimeCandidate(pythonPath: environment.appendingPathComponent("bin/python").path)
        status("Downloading verified mlx-chronos \(release.version)")
        let wheel = try await artifact(release.url, digest: release.sha256)
        defer { try? fm.removeItem(at: wheel) }
        let wheelDirectory = root.appendingPathComponent("downloads-" + UUID().uuidString, isDirectory: true)
        try ensureDirectory(wheelDirectory)
        defer { try? fm.removeItem(at: wheelDirectory) }
        let namedWheel = wheelDirectory.appendingPathComponent(release.url.lastPathComponent)
        try fm.moveItem(at: wheel, to: namedWheel)
        _ = try await command(candidate.pythonPath, ["-I", "-B", bridge.path, "pip", "install", "--index-url", "https://pypi.org/simple",
            "--disable-pip-version-check", namedWheel.path + "[thermal]"], log: log)
        _ = try await command(candidate.pythonPath, ["-I", "-B", bridge.path, "pip", "check"], log: log)
        status("Verifying CLI compatibility and thermal support")
        let verified = try await probe(candidate, bridge: bridge, log: log)
        try AppRuntimePolicy.validate(verified, release: release, expectedPrefix: environment.path)
        try Task.checkCancellation()
        try JSONEncoder().encode(release).write(to: environment.appendingPathComponent("release.json"), options: .atomic)
        let next = ActiveRuntime(environment: name, previousEnvironment: active?.environment, release: release)
        try JSONEncoder().encode(next).write(to: root.appendingPathComponent("active-runtime.json"), options: .atomic)
        activated = true
        return RuntimeSyncResult(candidate: candidate, notice: latestNotice)
    }

    func rollback(bridge: URL) async throws -> RuntimeCandidate {
        try ensureDirectory(root)
        try rejectSymbolicLink(root.appendingPathComponent("managed-runtimes"))
        let lock = try RuntimeFileLock(root.appendingPathComponent("runtime-update.lock"))
        defer { lock.close() }
        guard let active = ActiveRuntime.read(at: root), let previous = active.previousEnvironment,
              let data = try? Data(contentsOf: root.appendingPathComponent("managed-runtimes/\(previous)/release.json")),
              let release = try? JSONDecoder().decode(RuntimeRelease.self, from: data), AppRuntimePolicy.issue(release.contract) == nil else {
            throw CommandError.invalid("No previous compatible app-managed copy is available.")
        }
        let restored = ActiveRuntime(environment: previous, previousEnvironment: active.environment, release: release)
        try rejectSymbolicLink(root.appendingPathComponent("managed-runtimes/\(previous)"))
        guard FileManager.default.isExecutableFile(atPath: restored.candidate(at: root).pythonPath) else {
            throw CommandError.invalid("The previous environment is no longer available.")
        }
        let verified = try await probe(restored.candidate(at: root), bridge: bridge, log: { _ in })
        try AppRuntimePolicy.validate(verified, release: release, expectedPrefix: root.appendingPathComponent("managed-runtimes/\(previous)").path)
        try JSONEncoder().encode(restored).write(to: root.appendingPathComponent("active-runtime.json"), options: .atomic)
        return restored.candidate(at: root)
    }

    func checkAppRelease() async -> (String, URL)? {
        guard let data = try? await metadata(URL(string: "https://api.github.com/repos/igurss/mlx-chronos/releases?per_page=100")!),
              let releases = try? JSONSerialization.jsonObject(with: data) as? [[String: Any]],
              let current = ReleaseVersion(AppRuntimePolicy.appVersion) else { return nil }
        return releases.compactMap { release -> (String, URL)? in
            guard release["draft"] as? Bool == false, release["prerelease"] as? Bool == false,
                  let tag = release["tag_name"] as? String, tag.hasPrefix("app-v"),
                  let version = ReleaseVersion(String(tag.dropFirst(5))), version > current,
                  let raw = release["html_url"] as? String, let url = URL(string: raw),
                  url.scheme == "https", url.host == "github.com", url.path.hasPrefix("/igurss/mlx-chronos/releases/") else { return nil }
            return (String(tag.dropFirst(5)), url)
        }.max { ReleaseVersion($0.0)! < ReleaseVersion($1.0)! }
    }

    private func metadata(_ url: URL) async throws -> Data {
        // Explicit file URLs are used only by disposable developer bootstrap
        // checks. The production constructor always uses the HTTPS catalog.
        if url.isFileURL {
            guard (try url.resourceValues(forKeys: [.fileSizeKey]).fileSize ?? Int.max) <= 2_000_000 else {
                throw CommandError.invalid("Runtime catalog exceeded the size limit.")
            }
            return try Data(contentsOf: url)
        }
        var request = URLRequest(url: url)
        request.timeoutInterval = 15
        request.setValue("MLXChronos/" + AppRuntimePolicy.appVersion, forHTTPHeaderField: "User-Agent")
        let (file, response) = try await session.download(for: request)
        defer { try? FileManager.default.removeItem(at: file) }
        guard (response as? HTTPURLResponse)?.statusCode == 200,
              (try file.resourceValues(forKeys: [.fileSizeKey]).fileSize ?? Int.max) <= 2_000_000 else {
            throw CommandError.invalid("Update service returned an invalid response.")
        }
        return try Data(contentsOf: file)
    }
    private func artifact(_ url: URL, digest: String) async throws -> URL {
        let (file, response) = try await session.download(from: url)
        do {
            guard (response as? HTTPURLResponse)?.statusCode == 200,
                  (try file.resourceValues(forKeys: [.fileSizeKey]).fileSize ?? Int.max) <= 200_000_000 else {
                throw CommandError.invalid("Runtime download failed or exceeded the size limit.")
            }
            let worker = Task.detached {
                let handle = try FileHandle(forReadingFrom: file)
                defer { try? handle.close() }
                var hash = SHA256()
                while let chunk = try handle.read(upToCount: 1_048_576), !chunk.isEmpty {
                    try Task.checkCancellation(); hash.update(data: chunk)
                }
                return hash.finalize().map { String(format: "%02x", $0) }.joined()
            }
            let actual = try await withTaskCancellationHandler { try await worker.value } onCancel: { worker.cancel() }
            guard actual == digest else { throw CommandError.invalid("Downloaded runtime checksum mismatch; the active copy was kept.") }
            return file
        } catch { try? FileManager.default.removeItem(at: file); throw error }
    }
    private func preparePython(_ artifact: RuntimeArtifact, status: (String) -> Void,
                               log: @escaping @Sendable (String) -> Void) async throws -> String {
        let parent = root.appendingPathComponent("python", isDirectory: true)
        try ensureDirectory(parent)
        let directory = parent.appendingPathComponent(artifact.version + "-" + artifact.sha256.prefix(16), isDirectory: true)
        let python = directory.appendingPathComponent("python/bin/python3").path
        try rejectSymbolicLink(directory)
        if FileManager.default.isExecutableFile(atPath: python) {
            try await verifyPython(python, version: artifact.version, log: log)
            return python
        }
        if FileManager.default.fileExists(atPath: directory.path) {
            throw CommandError.invalid("Private Python is incomplete. Remove that incomplete runtime folder before trying again.")
        }
        status("Downloading private Python \(artifact.version)")
        let archive = try await self.artifact(artifact.url, digest: artifact.sha256)
        defer { try? FileManager.default.removeItem(at: archive) }
        let listing = try await command("/usr/bin/tar", ["-tzf", archive.path], log: { _ in })
        let names = listing.stdout.split(separator: "\n")
        guard !names.isEmpty, names.allSatisfy({ $0.hasPrefix("python/") && !$0.split(separator: "/").contains("..") }) else {
            throw CommandError.invalid("Python archive contains unexpected paths.")
        }
        try ensureDirectory(directory)
        var complete = false
        defer { if !complete { try? FileManager.default.removeItem(at: directory) } }
        _ = try await command("/usr/bin/tar", ["-xzf", archive.path, "-C", directory.path], log: { _ in })
        try await verifyPython(python, version: artifact.version, log: log)
        complete = true
        return python
    }
    private func verifyPython(_ python: String, version: String, log: @escaping @Sendable (String) -> Void) async throws {
        let checked = try await command(python, ["-I", "-c", "import platform; print(platform.python_version()); print(platform.machine())"], log: log)
        guard checked.stdout.trimmingCharacters(in: .whitespacesAndNewlines) == version + "\narm64" else {
            throw CommandError.invalid("Private Python failed version or architecture verification.")
        }
    }
    private func probe(_ candidate: RuntimeCandidate, bridge: URL, log: @escaping @Sendable (String) -> Void) async throws -> RuntimeProbe {
        let response = try await command(candidate.pythonPath, ["-I", "-B", bridge.path, "probe"], log: { _ in })
        return try JSONDecoder().decode(RuntimeProbe.self, from: Data(response.stdout.utf8))
    }
    private func command(_ executable: String, _ arguments: [String], log: @escaping @Sendable (String) -> Void) async throws -> ProcessResult {
        try Task.checkCancellation()
        let worker = ProcessRunner(); runner = worker
        defer { runner = nil }
        var environment = RuntimeDiscovery.environment()
        // pip config/target variables must never redirect a private install
        // into another environment or silently switch package indexes.
        for key in environment.keys.filter({ $0.hasPrefix("PIP_") || $0 == "PYTHONUSERBASE" }) { environment.removeValue(forKey: key) }
        environment["PIP_CONFIG_FILE"] = "/dev/null"
        let result = await withTaskCancellationHandler {
            await worker.run(executable: executable, arguments: arguments, directory: root,
                environment: environment, timeout: 600, onOutput: log)
        } onCancel: { worker.stop() }
        if result.cancelled || Task.isCancelled { throw CancellationError() }
        guard result.succeeded else { throw CommandError.invalid("Runtime setup failed (exit \(result.exitCode)): " + String((result.stderr + result.stdout).suffix(3000))) }
        return result
    }
    private func ensureDirectory(_ directory: URL) throws {
        // All writes stay in a private tree, never a symlink redirected into an
        // external Python. Existing older installations are not removed.
        try rejectSymbolicLink(directory)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
    }
    private func rejectSymbolicLink(_ directory: URL) throws {
        guard (try? directory.resourceValues(forKeys: [.isSymbolicLinkKey]).isSymbolicLink) != true else {
            throw CommandError.invalid("An app runtime folder cannot be a symbolic link.")
        }
    }
}

private final class RuntimeFileLock {
    private var descriptor: Int32
    init(_ file: URL) throws {
        descriptor = Darwin.open(file.path, O_CREAT | O_RDWR | O_NOFOLLOW, S_IRUSR | S_IWUSR)
        guard descriptor >= 0 else { throw CommandError.invalid("Could not lock the app runtime directory.") }
        guard flock(descriptor, LOCK_EX | LOCK_NB) == 0 else {
            Darwin.close(descriptor); descriptor = -1
            throw CommandError.invalid("Another app instance is already preparing the runtime. Try again later.")
        }
    }
    func close() { if descriptor >= 0 { Darwin.close(descriptor); descriptor = -1 } }
    deinit { close() }
}
