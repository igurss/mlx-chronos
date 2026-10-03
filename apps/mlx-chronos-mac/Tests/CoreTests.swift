import Darwin
import Foundation

enum TestFailure: LocalizedError {
    case failed(String)
    var errorDescription: String? {
        switch self { case .failed(let message): return message }
    }
}
func expect(_ value: @autoclosure () -> Bool, _ message: String) throws {
    if !value() { throw TestFailure.failed(message) }
}
func rejects(_ block: () throws -> Void) throws {
    do { try block() } catch is CommandError { return }
    throw TestFailure.failed("Expected a validation error")
}

@main
struct CoreTests {
    static func main() async {
        do { try await runChecks() }
        catch {
            fputs("Core checks failed: \(error.localizedDescription)\n", stderr)
            exit(EXIT_FAILURE)
        }
    }

    static func runChecks() async throws {
        guard CommandLine.arguments.count == 3 else {
            throw TestFailure.failed("Usage: core-checks <Python executable> <bridge path>")
        }
        let python = CommandLine.arguments[1]
        let bridge = URL(fileURLWithPath: CommandLine.arguments[2])
        let runner = ProcessRunner()
        let probeResult = await runner.run(executable: python, arguments: ["-I", "-B", bridge.path, "probe"],
            directory: FileManager.default.temporaryDirectory, environment: RuntimeDiscovery.environment(), timeout: 20)
        try expect(probeResult.succeeded, "probe failed: \(probeResult.stderr)")
        let probe = try JSONDecoder().decode(RuntimeProbe.self, from: Data(probeResult.stdout.utf8))
        try checkRuntimePolicy(probe)
        try expect(probe.commands.count == 14, "all commands must decode")
        try expect(OptionPresentation.compareGuidance.contains("Invalid schemas or seals are rejected")
            && OptionPresentation.compareGuidance.contains("warnings, not a block"),
            "Compare guidance no longer distinguishes invalid files from comparability warnings")
        let root = FileManager.default.temporaryDirectory.appendingPathComponent("chronos-core-tests-" + UUID().uuidString)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: root) }

        for command in probe.commands where command.name != "wizard" {
            var values = CommandBuilder.initialValues(command, outputRoot: root)
            for option in command.options where option.required {
                values[option.name] = ["engine": "omlx", "model": "model with spaces $(never execute)",
                                      "engine_model": "omlx=first\nvllm-mlx=second", "files": "/tmp/-first.json\n/tmp/second file.json",
                                      "file": "/tmp/one result.json"][option.name] ?? "required"
            }
            let args = try CommandBuilder.arguments(command, values: values)
            try expect(args.first == command.name, "wrong command")
            if command.name == "run" {
                try expect(CommandBuilder.resultDirectory(command, values: values, workingDirectory: root)?.path == root.standardizedFileURL.path,
                    "default output folder was not resolved")
                try expect(CommandBuilder.resultDirectory(command, values: ["output_dir": "nested output"], workingDirectory: root)?.path
                    == root.appendingPathComponent("nested output").path, "relative result folder did not match the CLI working directory")
                try expect(args.contains("model with spaces $(never execute)"), "argument was split")
                try expect(!args.contains("--trials"), "profile defaults must be delegated to CLI")
                try rejects { _ = try CommandBuilder.arguments(command, values: values.merging(["ram_sample_interval": "nan"]) { _, rhs in rhs }) }
                try rejects { _ = try CommandBuilder.arguments(command, values: values.merging(["repeat": "0"]) { _, rhs in rhs }) }
                try rejects { _ = try CommandBuilder.arguments(command, values: values.merging(["cooldown_seconds": "-1"]) { _, rhs in rhs }) }
                let repeated = try CommandBuilder.arguments(command, values: values.merging(["engine_opt": "context_length=4096\ncache=true"]) { _, rhs in rhs })
                try expect(repeated.filter { $0 == "--engine-opt" }.count == 2, "repeat options lost")
                let leadingDash = try CommandBuilder.arguments(command, values: values.merging(["model": "--literal-id", "notes": "-not-an-option"]) { _, rhs in rhs })
                try expect(leadingDash.contains("--model=--literal-id") && leadingDash.contains("--notes=-not-an-option"), "literal leading dashes became options")
                try expect(CommandBuilder.timeout(command, values: values) == nil, "benchmark has an arbitrary duration cap")
            }
            if command.name == "compare" { try expect(args.contains("--"), "positional option terminator missing") }
            if command.name == "submit" {
                try expect(CommandBuilder.resultDirectory(command, values: values, workingDirectory: root) == nil,
                    "sharing changed the result browser's folder")
                try expect(args.contains("--dry-run"), "sharing must default to validation-only")
                try expect(CommandBuilder.timeout(command, values: ["timeout": "300"]) == 360, "network timeout was clipped")
            }
            if command.name == "matrix" {
                try rejects { _ = try CommandBuilder.arguments(command, values: values.merging(["engine_model": "omlx=a\nomlx = b"]) { _, rhs in rhs }) }
                try rejects { _ = try CommandBuilder.arguments(command, values: values.merging(["engine_model": "omlx= "]) { _, rhs in rhs }) }
            }
        }

        let normal = RuntimeInstallation(candidate: RuntimeCandidate(pythonPath: python), probe: probe)
        var builtIn = normal; builtIn.isBuiltIn = true
        try expect(!builtIn.canUninstall, "app-managed runtime can be uninstalled")
        var source = normal; source.candidate.sourcePath = "/tmp/source"
        try expect(!source.canUninstall, "source checkout can be uninstalled")
        var protected = normal; protected.probe?.externallyManaged = true
        try expect(!protected.canUninstall, "externally-managed Python can be modified")
        var inherited = normal; inherited.probe?.packageOwned = false
        try expect(!inherited.canUninstall, "an inherited package can be uninstalled")
        var pipx = normal; pipx.probe?.environmentManager = "pipx"
        try expect(!pipx.canUninstall, "pipx metadata can be corrupted by direct pip removal")
        var unknownThermal = probe; unknownThermal.thermalState = "unavailable_foundation_unknown_state_9"
        try expect(!unknownThermal.thermalAvailable, "unknown Foundation thermal state was accepted as verified")

        let result = root.appendingPathComponent("result.json")
        try Data(#"{"engine":{"name":"test"},"model":{"name":"model"},"meta":{"timestamp":"2026-09-30T10:00:00Z"},"metrics":{"request_tokens_per_second":{"mean":12.5},"ttft_cold":{"mean":true}}}"#.utf8).write(to: result)
        let summaries = ResultRepository.load(root)
        try expect(summaries.count == 1 && summaries[0].throughput == 12.5 && summaries[0].coldTTFT == nil, "numeric result parsing is not strict")
        try Data(#"{"unrelated":"JSON"}"#.utf8).write(to: root.appendingPathComponent("unknown.json"))
        try expect(ResultRepository.load(root).first { $0.url.lastPathComponent == "unknown.json" }?.isBenchmark == false, "an unrelated JSON was labelled a benchmark")
        let concurrency = root.appendingPathComponent("concurrency.json")
        try Data(#"{"concurrency_profile_version":"1","protocol":{"name":"cache_minimized_concurrency","version":"1"},"engine":{"name":"lmstudio"},"model":{"name":"model"},"levels":[{"concurrency":32}]}"#.utf8).write(to: concurrency)
        let concurrentSummary = ResultRepository.load(root).first { $0.url.lastPathComponent == "concurrency.json" }
        try expect(concurrentSummary?.kind == "local_concurrency_diagnostic"
            && concurrentSummary?.displayProfile == "Concurrent requests"
            && concurrentSummary?.isBenchmark == false, "Concurrency was not recognized or became eligible for benchmark actions")
        try Data(#"{"concurrency_profile_version":"1","protocol":{"name":"unrelated","version":"1"},"engine":{"name":"test"},"model":{"name":"model"},"levels":[{"concurrency":1}]}"#.utf8)
            .write(to: root.appendingPathComponent("lookalike.json"))
        try expect(ResultRepository.load(root).first { $0.url.lastPathComponent == "lookalike.json" }?.kind == "unknown",
            "An unrelated protocol was labelled a concurrency diagnostic")
        try Data(#"{"concurrency_profile_version":"1","protocol":{"name":"cache_minimized_concurrency","version":"1"},"engine":{"name":"test"},"model":{"name":"model"},"levels":[]}"#.utf8)
            .write(to: root.appendingPathComponent("empty-concurrency.json"))
        try expect(ResultRepository.load(root).first { $0.url.lastPathComponent == "empty-concurrency.json" }?.kind == "unknown",
            "An empty diagnostic was classified as a recorded concurrency run")
        let dated = root.appendingPathComponent("dated", isDirectory: true)
        try FileManager.default.createDirectory(at: dated, withIntermediateDirectories: true)
        try Data(#"{"kind":"local_matrix_diagnostic","created_at":"2026-10-02T09:00:00.123+02:00"}"#.utf8)
            .write(to: dated.appendingPathComponent("matrix.json"))
        try Data(#"{"kind":"local_context_diagnostic","timestamp":"2026-10-02T07:30:00Z"}"#.utf8)
            .write(to: dated.appendingPathComponent("context.json"))
        try Data(#"{"kind":"local_energy_diagnostic","timestamp":"2026-10-02T07:30:00Z"}"#.utf8)
            .write(to: dated.appendingPathComponent("z-same-time.json"))
        let undated = dated.appendingPathComponent("undated.json")
        try Data(#"{"unrelated":"JSON"}"#.utf8).write(to: undated)
        let fallbackDate = Date(timeIntervalSince1970: 1_700_000_000)
        try FileManager.default.setAttributes([.modificationDate: fallbackDate], ofItemAtPath: undated.path)
        let invalidDate = dated.appendingPathComponent("invalid-date.json")
        try Data(#"{"kind":"local_matrix_diagnostic","created_at":"invalid date"}"#.utf8).write(to: invalidDate)
        try FileManager.default.setAttributes([.modificationDate: fallbackDate.addingTimeInterval(-60)], ofItemAtPath: invalidDate.path)
        let chronological = ResultRepository.load(dated)
        try expect(chronological.map { $0.url.lastPathComponent } == ["context.json", "z-same-time.json", "matrix.json", "undated.json", "invalid-date.json"],
            "Result ordering ignored created_at, fractional seconds, UTC offsets or file-date fallback")
        try expect(chronological[2].timestamp == "2026-10-02T09:00:00.123+02:00"
            && abs(chronological[3].recordedAt.timeIntervalSince(fallbackDate)) < 0.01,
            "Recorded timestamp was not displayed or file-date fallback was lost")
        let tooLarge = root.appendingPathComponent("large.json")
        try Data(count: ResultRepository.fileLimit + 1).write(to: tooLarge)
        try rejects { _ = try ResultRepository.read(tooLarge) }

        try checkResultListing(root)

        let large = await ProcessRunner().run(executable: python,
            arguments: ["-I", "-c", "import sys; sys.stdout.write('a'*600000); sys.stderr.write('b'*600000)"],
            directory: root, environment: RuntimeDiscovery.environment(), timeout: 10)
        try expect(large.succeeded && large.stdout.count == 600000 && large.stderr.count == 600000, "pipe output was lost or deadlocked")
        let orphanStart = Date()
        let orphan = await ProcessRunner().run(executable: python,
            arguments: ["-I", "-c", "import subprocess,sys; subprocess.Popen([sys.executable,'-I','-c','import time; time.sleep(5)'])"],
            directory: root, environment: RuntimeDiscovery.environment(), timeout: 10)
        try expect(Date().timeIntervalSince(orphanStart) < 4.5, "an inherited pipe kept the app waiting")
        try expect(orphan.outputTruncated && !orphan.succeeded, "incomplete output was reported as success")
        let timed = await ProcessRunner().run(executable: python,
            arguments: ["-I", "-c", "import time; time.sleep(30)"], directory: root,
            environment: RuntimeDiscovery.environment(), timeout: 0.2)
        try expect(timed.timedOut && !timed.succeeded, "timeout did not stop the process")
        let cancelledRunner = ProcessRunner()
        cancelledRunner.stop()
        let cancelled = await cancelledRunner.run(executable: python, arguments: ["-V"], directory: root,
            environment: RuntimeDiscovery.environment(), timeout: 10)
        try expect(cancelled.cancelled, "cancel-before-launch was ignored")
        print("Core checks passed: CLI parity, exact arguments, defaults, validation, removal policy, result parsing, pipes, timeout and cancellation.")
    }
    static func checkRuntimePolicy(_ probe: RuntimeProbe) throws {
        let contract = AppRuntimeContract(apiVersion: 1, minimumAppVersion: "0.2.0",
            requiredCapabilities: Array(AppRuntimePolicy.capabilities), supportedCommands: probe.commands.map(\.name))
        try expect(AppRuntimePolicy.issue(contract, appVersion: "0.2.0") == nil, "Compatible CLI was blocked")
        try expect(AppRuntimePolicy.issue(contract, appVersion: "0.1.0") != nil, "Minimum app version was ignored")
        let future = AppRuntimeContract(apiVersion: 2, minimumAppVersion: "0.2.0", requiredCapabilities: [], supportedCommands: ["run"])
        try expect(AppRuntimePolicy.issue(future) != nil, "Unknown interface version was accepted")
        let feature = AppRuntimeContract(apiVersion: 1, minimumAppVersion: "0.2.0", requiredCapabilities: ["future-feature"], supportedCommands: ["run"])
        try expect(AppRuntimePolicy.issue(feature) != nil, "Unsupported capability was accepted")
        let command = AppRuntimeContract(apiVersion: 1, minimumAppVersion: "0.2.0", requiredCapabilities: [], supportedCommands: ["new-command"])
        try expect(AppRuntimePolicy.issue(command) != nil, "Unsupported command was accepted")
        let release = RuntimeRelease(version: probe.packageVersion!, url: URL(string: "https://files.pythonhosted.org/test.whl")!,
            sha256: String(repeating: "a", count: 64), contract: contract, allowLegacyBridge: true)
        try AppRuntimePolicy.validate(probe, release: release)
        try rejects { try AppRuntimePolicy.validate(probe, release: release, expectedPrefix: "/wrong/environment") }
        let strict = RuntimeRelease(version: release.version, url: release.url, sha256: release.sha256,
            contract: contract, allowLegacyBridge: false)
        if probe.appContract == nil { try rejects { try AppRuntimePolicy.validate(probe, release: strict) } }
        let catalog = RuntimeCatalog(schema: 1, python: RuntimeArtifact(version: "3.13.16",
            url: URL(string: "https://github.com/astral-sh/python-build-standalone/releases/download/test/aarch64-apple-darwin-install_only.tar.gz")!,
            sha256: String(repeating: "b", count: 64)), releases: [release])
        try catalog.validate()
        try expect(catalog.newestCompatible(published: [release.version], appVersion: "0.2.0")?.version == release.version,
            "Published compatible release was not selected")
        try expect(catalog.newestCompatible(published: [], appVersion: "0.2.0") == nil, "Unpublished release was selected")
        try expect(catalog.newestCompatible(published: [release.version], appVersion: "0.1.0") == nil, "Incompatible release was selected")
        let exact = RuntimePublication(url: release.url, digests: .init(sha256: release.sha256), yanked: false)
        let yanked = RuntimePublication(url: release.url, digests: exact.digests, yanked: true)
        let altered = RuntimePublication(url: release.url, digests: .init(sha256: String(repeating: "c", count: 64)), yanked: false)
        let publications = RuntimeProject(releases: [release.version: [exact], "0.9.0": [], "0.9.0rc1": [exact], "0.8.0": [yanked]])
        try expect(publications.latestStable == release.version, "Empty, yanked or prerelease versions became latest stable")
        try expect(catalog.verifiedPublished(in: publications) == [release.version], "Exact approved publication was skipped")
        try expect(catalog.verifiedPublished(in: RuntimeProject(releases: [release.version: [yanked, altered]])).isEmpty,
            "A withdrawn or altered wheel was approved")
        if probe.appContract != nil { try AppRuntimePolicy.validate(probe, release: strict) }
        var missing = probe; missing.appContract = nil
        try rejects { try AppRuntimePolicy.validate(missing, release: strict) }
        var unsafe = probe; unsafe.commands[0].options[0].kind = "unknown-kind"
        try rejects { try AppRuntimePolicy.validate(unsafe, release: release) }
        try expect(ReleaseVersion("0.5.0rc1") == nil && ReleaseVersion("0.5.10")! > ReleaseVersion("0.5.9")!, "Stable numeric version filtering failed")
        try expect(!ActiveRuntime.safeName("../external") && !ActiveRuntime.safeName("/tmp/external"), "Runtime pointer escaped its private tree")
    }
    static func checkResultListing(_ root: URL) throws {
        let fm = FileManager.default
        let archive = root.appendingPathComponent("many-results")
        try fm.createDirectory(at: archive, withIntermediateDirectories: true)
        let old = Data(#"{"meta":{"timestamp":"2026-01-01T00:00:00Z"},"engine":{"name":"fake"},"model":{"name":"old"},"metrics":{}}"#.utf8)
        for index in 0..<5001 { try old.write(to: archive.appendingPathComponent("run-\(index).json")) }
        let candidates = try fm.contentsOfDirectory(at: archive, includingPropertiesForKeys: nil)
        let formerlyExcluded = candidates[5000]
        let newest = Data(#"{"meta":{"timestamp":"2099-01-01T00:00:00Z"},"model":{"name":"newest"}}"#.utf8)
        try newest.write(to: formerlyExcluded)
        let cache = ResultSummaryCache()
        let listing = try ResultRepository.scan(archive, cache: cache)
        try expect(listing.total == 5001 && listing.results.count == 5000
            && listing.results.first?.url == formerlyExcluded && listing.notice != nil,
            "File limit was applied before chronological selection or was hidden")
        let changed = Data(#"{"meta":{"timestamp":"2099-01-01T00:00:00Z"},"model":{"name":"changed with a different size"}}"#.utf8)
        try changed.write(to: formerlyExcluded)
        let refreshed = try ResultRepository.scan(archive, limit: 3, cache: cache)
        try expect(refreshed.results.first?.model == "changed with a different size",
            "Display cache did not invalidate a modified file")
        var visited = 0
        do {
            _ = try ResultRepository.scan(archive, checkCancellation: {
                visited += 1
                if visited == 100 { throw CancellationError() }
            })
            throw TestFailure.failed("Cancelled scan completed")
        } catch is CancellationError {}
        let folders = root.appendingPathComponent("many-folders")
        for index in 0..<31 {
            let folder = folders.appendingPathComponent("folder-\(index)")
            try fm.createDirectory(at: folder, withIntermediateDirectories: true)
            try old.write(to: folder.appendingPathComponent("run.json"))
        }
        let allFolders = try ResultRepository.scan(folders)
        try expect(allFolders.total == 31, "Subfolders were arbitrarily excluded")
    }

}
