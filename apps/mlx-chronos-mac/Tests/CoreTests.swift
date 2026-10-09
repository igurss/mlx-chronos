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
        let legacyEngine = try JSONDecoder().decode(EngineStatus.self, from: Data("""
            {"name":"mlx-lm","installed":false,"running":true,"version":"unknown",
             "endpoint":"http://localhost:8080/v1","port":8080,"models":[]}
            """.utf8))
        try expect(legacyEngine.clientVersion == nil && legacyEngine.versionSource == nil,
            "Older compatible CLI snapshots must decode without version provenance")
        try expect(legacyEngine.versionLabel == "Reported version (source unavailable)",
            "Legacy version must not be labelled verified serving evidence")
        var localVersion = legacyEngine
        localVersion.versionSource = "client_package"
        localVersion.clientVersion = "0.31.2"
        try expect(localVersion.version == "unknown" && localVersion.versionLabel == "Locally detected engine version",
            "Installed client evidence must not overwrite the serving version")
        localVersion.versionSource = "server_api"
        try expect(localVersion.versionLabel == "Serving engine / runtime version", "Server version label lost")
        localVersion.versionSource = "process_package"
        try expect(localVersion.versionLabel == "Server installation version (indirect)", "Process evidence must remain indirect")
        let probeResult = await runner.run(executable: python, arguments: ["-I", "-B", bridge.path, "probe"],
            directory: FileManager.default.temporaryDirectory, environment: RuntimeDiscovery.environment(), timeout: 20)
        try expect(probeResult.succeeded, "probe failed: \(probeResult.stderr)")
        let probe = try JSONDecoder().decode(RuntimeProbe.self, from: Data(probeResult.stdout.utf8))
        try checkRuntimePolicy(probe)
        try expect(probe.commands.count == 14, "all commands must decode")
        try expect(RuntimeDiscovery.environment(ports: ["mlx-serve": "11235"])["MLX_CHRONOS_MLX_SERVE_PORT"] == "11235",
            "mlx-serve port override was lost")
        let configuredPorts = ["omlx": "8000", "mlx-lm": "invalid", "mlx-serve": "11235"]
        for name in ["compare", "history", "submit"] {
            let command = probe.commands.first { $0.name == name }!
            let selected = try CommandBuilder.serverPorts(command, values: [:], configured: configuredPorts)
            try expect(selected.isEmpty, "A file operation was blocked by unrelated server ports")
        }
        for name in ["run", "models", "validate", "doctor", "context", "concurrency", "energy"] {
            let command = probe.commands.first { $0.name == name }!
            let selected = try CommandBuilder.serverPorts(command, values: ["engine": "omlx"], configured: configuredPorts)
            try expect(selected == ["omlx": "8000"], "An unused engine port blocked the selected server")
            try rejects { _ = try CommandBuilder.serverPorts(command, values: ["engine": "mlx-lm"], configured: configuredPorts) }
        }
        let matrixCommand = probe.commands.first { $0.name == "matrix" }!
        let runCommand = probe.commands.first { $0.name == "run" }!
        let defaultPorts = try CommandBuilder.serverPorts(runCommand, values: ["engine": ""], configured: configuredPorts)
        try expect(defaultPorts == ["omlx": "8000"], "Blank engine should delegate to the CLI default")
        let matrixPorts = try CommandBuilder.serverPorts(matrixCommand,
            values: ["engine_model": "omlx=a\nmlx-serve=b"], configured: configuredPorts)
        try expect(matrixPorts == ["omlx": "8000", "mlx-serve": "11235"], "Matrix validated unrelated ports")
        let doctorCommand = probe.commands.first { $0.name == "doctor" }!
        try rejects { _ = try CommandBuilder.serverPorts(doctorCommand, values: [:], configured: configuredPorts) }
        let enginesCommand = probe.commands.first { $0.name == "engines" }!
        try rejects { _ = try CommandBuilder.serverPorts(enginesCommand, values: [:], configured: configuredPorts) }
        let allPorts = try CommandBuilder.serverPorts(enginesCommand, values: [:], configured: ["omlx": "8000"])
        try expect(allPorts == ["omlx": "8000"], "Engine inventory lost its port overrides")
        try rejects { _ = try CommandBuilder.validatedPorts(configuredPorts) }
        try expect(OptionPresentation.compareGuidance.contains("Invalid schemas or seals are rejected")
            && OptionPresentation.compareGuidance.contains("warnings, not a block"),
            "Compare guidance no longer distinguishes invalid files from comparability warnings")
        let root = FileManager.default.temporaryDirectory.appendingPathComponent("chronos-core-tests-" + UUID().uuidString)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: root) }

        let enabledCommand = CLICommand(name: "future", help: "", options: [
            CLIOption(name: "enabled", flag: "--enabled", kind: "boolean", required: false,
                      multiple: false, choices: [], defaultValue: "True", help: "")
        ])
        let enabledValues = CommandBuilder.initialValues(enabledCommand, outputRoot: root)
        try expect(enabledValues["enabled"] == "true", "boolean contract default was lost")
        try rejects { _ = try CommandBuilder.arguments(enabledCommand, values: ["enabled": "false"]) }
        let dependencies = RuntimeDependencySnapshot(pythonVersion: "3.13.16", requirements: "httpx==0.28.1\npsutil==7.2.2\n")
        let validatedDependencies = try dependencies.validatedRequirements()
        try expect(validatedDependencies == dependencies.requirements, "dependency versions changed")
        try rejects { _ = try RuntimeDependencySnapshot(pythonVersion: "3.13.16", requirements: "--index-url https://untrusted.invalid\n").validatedRequirements() }
        let transferSession = URLSession(configuration: .ephemeral)
        defer { transferSession.invalidateAndCancel() }
        let transfer = transferSession.downloadTask(with: URL(string: "https://example.invalid/never-started")!)
        let limit = BoundedDownloadDelegate(limit: 100)
        limit.urlSession(transferSession, downloadTask: transfer, didWriteData: 100,
                         totalBytesWritten: 100, totalBytesExpectedToWrite: -1)
        try expect(transfer.state == .suspended, "bounded transfer rejected its exact limit")
        limit.urlSession(transferSession, downloadTask: transfer, didWriteData: 1,
                         totalBytesWritten: 101, totalBytesExpectedToWrite: -1)
        try expect(transfer.state == .canceling || transfer.state == .completed, "unknown-length download exceeded limit")

        for command in probe.commands where command.name != "wizard" {
            var values = CommandBuilder.initialValues(command, outputRoot: root)
            for option in command.options where option.required {
                values[option.name] = ["engine": "omlx", "model": "model with spaces $(never execute)",
                                      "engine_model": "omlx=first\nvllm-mlx=second", "files": "/tmp/-first.json\n/tmp/second file.json",
                                      "file": "/tmp/one result.json"][option.name] ?? "required"
            }
            if command.name == "run" { values["model"] = "model with spaces $(never execute)" }
            let args = try CommandBuilder.arguments(command, values: values)
            try expect(args.first == command.name, "wrong command")
            if command.options.first(where: { $0.name == "engine" })?.choices.contains("mlx-serve") == true {
                let serveArgs = try CommandBuilder.arguments(command, values: values.merging(["engine": "mlx-serve"]) { _, rhs in rhs })
                guard let index = serveArgs.firstIndex(of: "--engine") else {
                    throw TestFailure.failed("mlx-serve engine argument missing")
                }
                try expect(serveArgs[index + 1] == "mlx-serve", "mlx-serve engine argument changed")
            }
            if command.name == "run" {
                try rejects { _ = try CommandBuilder.arguments(command, values: values.merging(["model": " "]) { _, rhs in rhs }) }
                if command.supportsRunConfigurations {
                    let imported = ["model": "loaded/model", "trials": "5", "max_tokens": "100", "repeat": "3", "preflight": "true"]
                    let filled = try CommandBuilder.applyingConfiguration(imported, to: command,
                        current: values.merging(["submitted_by": "local-owner", "save_config": "/tmp/unwanted.json"]) { _, rhs in rhs })
                    try expect(filled["output_dir"] == values["output_dir"] && filled["submitted_by"] == "local-owner", "loading replaced local paths or attribution")
                    try expect(filled["model"] == "loaded/model" && filled["trials"] == "5", "loaded settings were not applied")
                    let configured = try CommandBuilder.arguments(command, values: filled)
                    try expect(configured.contains("--trials") && configured.contains("--preflight"), "resolved settings were delegated back to new defaults")
                    try expect(!configured.contains("--config") && !configured.contains("--save-config"), "starting a loaded form would save again or reload old settings")
                    try rejects { _ = try CommandBuilder.applyingConfiguration(["unknown": "value"], to: command, current: values) }
                    let path = root.appendingPathComponent("saved settings.json")
                    let saved = await runner.run(executable: python,
                        arguments: ["-I", "-B", bridge.path, "config-save", path.path, "run", "--model", "org/model", "--profile", "sustained"],
                        directory: root, environment: RuntimeDiscovery.environment(), timeout: 20)
                    try expect(saved.succeeded, "saving through bridge failed: \(saved.stderr)")
                    let loaded = await runner.run(executable: python,
                        arguments: ["-I", "-B", bridge.path, "config-read", path.path],
                        directory: root, environment: RuntimeDiscovery.environment(), timeout: 20)
                    try expect(loaded.succeeded, "loading through bridge failed: \(loaded.stderr)")
                    let loadedDraft = try JSONDecoder().decode(RunConfigurationDraft.self, from: Data(loaded.stdout.utf8))
                    try expect(loadedDraft.values["trials"] == "1" && loadedDraft.values["max_tokens"] == "1000", "CLI profile defaults were not resolved")
                    try FileManager.default.removeItem(at: path)
                }
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
            if command.name == "compare" {
                try expect(args.contains("--"), "positional option terminator missing")
                if command.options.contains(where: { $0.name == "series_a_size" }) {
                    let series = try CommandBuilder.arguments(command, values: values.merging(["series_a_size": "1"]) { _, rhs in rhs })
                    try expect(series.contains("--series-a-size") && series.contains("--"), "series option or positional protection missing")
                    try rejects { _ = try CommandBuilder.arguments(command, values: values.merging(["series_a_size": "0"]) { _, rhs in rhs }) }
                    try rejects { _ = try CommandBuilder.arguments(command, values: values.merging(["series_a_size": "2"]) { _, rhs in rhs }) }
                }
            }
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
        try expect(unknownThermal.ready, "Missing thermal observations should not invalidate an external CLI")

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

        try checkTrialCharts(root)
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
        // Cancel after the runner has selected the child but before it launches.
        // Wait for the child to install SIGINT handling before returning from launch.
        let enteredLaunch = DispatchSemaphore(value: 0)
        let resumeLaunch = DispatchSemaphore(value: 0)
        let ready = root.appendingPathComponent("child-ready")
        let racingRunner = ProcessRunner(launch: { child in
            enteredLaunch.signal()
            guard resumeLaunch.wait(timeout: .now() + 5) == .success else {
                throw TestFailure.failed("launch barrier timed out")
            }
            try child.run()
            let deadline = Date().addingTimeInterval(5)
            while !FileManager.default.fileExists(atPath: ready.path), Date() < deadline {
                Thread.sleep(forTimeInterval: 0.01)
            }
        })
        let raceStart = Date()
        let racing = Task {
            await racingRunner.run(executable: python,
                arguments: ["-I", "-c", "import signal,time,pathlib,sys; signal.signal(signal.SIGINT,signal.SIG_IGN); pathlib.Path(sys.argv[1]).touch(); time.sleep(30)", ready.path],
                directory: root, environment: RuntimeDiscovery.environment(), timeout: 9)
        }
        // Avoid blocking the cooperative executor that starts the task above.
        let entered: Bool = await withCheckedContinuation { continuation in
            DispatchQueue.global().async {
                continuation.resume(returning: enteredLaunch.wait(timeout: .now() + 5) == .success)
            }
        }
        racingRunner.stop()
        resumeLaunch.signal()
        let raced = await racing.value
        try expect(entered && FileManager.default.fileExists(atPath: ready.path), "race fixture never reached launch")
        try expect(raced.cancelled && !raced.timedOut && Date().timeIntervalSince(raceStart) < 8,
            "cancellation during launch lost termination escalation")
        print("Core checks passed: CLI parity, exact arguments, defaults, validation, removal policy, result parsing/trial charts, pipes, timeout and cancellation.")
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
        var withoutThermal = probe; withoutThermal.thermalState = "unavailable_no_foundation"
        try expect(withoutThermal.ready, "Missing thermal observations blocked a valid external CLI")
        try rejects { try AppRuntimePolicy.validate(withoutThermal, release: release) }
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
    static func checkTrialCharts(_ root: URL) throws {
        let fixture = #"{"engine":{"name":"omlx","version":"1.2"},"model":{"name":"model","quantization":"4bit"},"hardware":{"chip":"Apple M4","memory_gb":32},"metrics":{"ttft_cold":{"mean":0.333},"ttft_cached":{"mean":0.111},"request_tokens_per_second":{"mean":77},"tokens_per_second":{"mean":99},"decode_tokens_per_second":{"mean":88}},"trials":{"count":2,"ttft_cold_raw":[0.2,0.4],"ttft_cached_raw":[0.1,0.2],"tokens_per_second_raw":[50,60],"decode_tokens_per_second_raw":[70,80]},"meta":{"benchmark_profile":"baseline","benchmark_protocol":{"name":"baseline","version":"4"},"cached_ttft_warning":true,"word_fallback_warning":false}}"#
        let original = try JSONSerialization.jsonObject(with: Data(fixture.utf8)) as! [String: Any]
        func parse(_ changed: [String: Any]) throws -> BenchmarkTrialData {
            try BenchmarkTrialData.parse(JSONSerialization.data(withJSONObject: changed))
        }
        let parsed = try parse(original)
        try expect(parsed.count == 2 && parsed.series.count == 4 && parsed.series[0].values == [200, 400],
            "Trial order or seconds-to-milliseconds conversion changed")
        try expect(parsed.series[0].recordedMean == 333 && parsed.series[2].recordedMean == 77,
            "The viewer recalculated a saved mean or preferred the legacy throughput alias")
        try expect(parsed.warnings.map(\.id) == ["cached_ttft_warning"] && parsed.protocolLabel == "baseline 4"
            && parsed.conditions == "Apple M4 · 32 GB RAM · 4bit · baseline", "Recorded context or warnings were lost")
        for source in ["process_package", "client_cli", "client_package"] {
            var changed = original
            changed["engine"] = ["name": "omlx", "version": "1.2", "version_source": source]
            let displayed = try parse(changed)
            try expect(displayed.warnings.contains { $0.id == "engine_version_indirect" }, "Saved version evidence lost its uncertainty")
        }
        let progressCases: [(Double, Int, String, Bool)] = [
            (1.0, 50, "word_fallback", false),
            (2.01, 50, "word_fallback", true),
            (1.5, 150, "usage.completion_tokens", true),
            (1.5, 150, "word_fallback", false)
        ]
        for (time, tokens, source, invalid) in progressCases {
            var changed = original
            var trials = changed["trials"] as! [String: Any]
            trials["throughput_elapsed_seconds_raw"] = [2.0, 2.0]
            trials["throughput_progress_samples_raw"] = [[
                ["elapsed_seconds": time, "completion_tokens": tokens, "token_count_source": source],
                ["elapsed_seconds": 2.0, "completion_tokens": 100, "token_count_source": "usage.completion_tokens"]
            ], []]
            changed["trials"] = trials
            changed["meta"] = ["sustained_throttling_warning": true]
            let displayed = try parse(changed)
            try expect(displayed.series == parsed.series, "Progress diagnosis altered saved trial values or means")
            try expect(displayed.warnings.contains { $0.id == "progress_chronology_warning" } == invalid,
                "Chronology diagnosis did not distinguish valid and invalid progress")
            let warning = displayed.warnings.first { $0.id == "sustained_throttling_warning" }
            try expect(warning?.title == (invalid ? "Unverified sustained warning" : "Sustained performance warning"),
                "Invalid progress was used to confirm sustained slowdown")
        }
        for engine in ["omlx", "vllm-mlx", "mlx-lm", "rapid-mlx", "lmstudio", "ollama", "mlx-serve"] {
            var changed = original; changed["engine"] = ["name": engine]
            let engineData = try parse(changed)
            try expect(engineData.series == parsed.series, "Charts depend on an engine-specific branch")
        }
        var legacy = original
        var legacyTrials = legacy["trials"] as! [String: Any]
        legacyTrials["decode_tokens_per_second_raw"] = NSNull(); legacy["trials"] = legacyTrials
        var legacyMetrics = legacy["metrics"] as! [String: Any]
        legacyMetrics.removeValue(forKey: "request_tokens_per_second"); legacy["metrics"] = legacyMetrics
        let legacyData = try parse(legacy)
        try expect(legacyData.series.count == 3 && legacyData.series[2].recordedMean == 99,
            "Missing decode samples were fabricated or legacy throughput summaries stopped working")
        legacyMetrics["ttft_cold"] = [:]; legacy["metrics"] = legacyMetrics
        let noSummary = try parse(legacy)
        try expect(noSummary.series[0].recordedMean == nil, "A missing summary was reconstructed from trials")
        for invalid in [true, -1, "0.1", NSNull()] as [Any] {
            var changed = original; var trials = changed["trials"] as! [String: Any]
            trials["ttft_cold_raw"] = [invalid, 0.4]; changed["trials"] = trials
            try rejects { _ = try parse(changed) }
        }
        for invalid in [true, 0, 1.5, BenchmarkTrialData.displayTrialLimit + 1] as [Any] {
            var changed = original; var trials = changed["trials"] as! [String: Any]
            trials["count"] = invalid; changed["trials"] = trials
            try rejects { _ = try parse(changed) }
        }
        var changed = original; var trials = changed["trials"] as! [String: Any]
        trials["ttft_cached_raw"] = [0.1]; changed["trials"] = trials
        try rejects { _ = try parse(changed) }
        trials["ttft_cached_raw"] = [0.1, 0.2]; trials["ttft_cold_raw"] = [Double.greatestFiniteMagnitude, 0.4]
        changed["trials"] = trials
        try rejects { _ = try parse(changed) }
        changed = original; changed["trials"] = ["count": 2]
        try rejects { _ = try parse(changed) }
        changed = original; changed["kind"] = "local_concurrency_diagnostic"
        try rejects { _ = try parse(changed) }
        changed = original; changed["meta"] = ["cached_ttft_warning": 1]
        let noWarnings = try parse(changed)
        try expect(noWarnings.warnings.isEmpty, "A numeric lookalike became a recorded Boolean warning")
        changed = original; changed["trials"] = ["count": 1, "ttft_cold_raw": [0.0]]
        let single = try parse(changed)
        try expect(single.count == 1 && single.series.count == 1 && single.series[0].values == [0],
            "A single or zero-valued observation was hidden")
        changed = original; var badMetrics = changed["metrics"] as! [String: Any]
        badMetrics["ttft_cold"] = ["mean": true]; changed["metrics"] = badMetrics
        try rejects { _ = try parse(changed) }
        let file = root.appendingPathComponent("chart-refresh.json")
        try Data(fixture.utf8).write(to: file)
        _ = try BenchmarkTrialData.load(file)
        changed = original; changed["model"] = ["name": "updated model"]
        try JSONSerialization.data(withJSONObject: changed).write(to: file)
        let updated = try BenchmarkTrialData.load(file)
        try expect(updated.model == "updated model", "Chart loading reused stale data")
        try FileManager.default.removeItem(at: file)
        // The public archive exercises the same viewer with real legacy samples.
        let archive = URL(fileURLWithPath: #filePath).deletingLastPathComponent()
            .appendingPathComponent("../../../results/submitted").standardizedFileURL
        let archived = try FileManager.default.contentsOfDirectory(at: archive, includingPropertiesForKeys: nil)
            .filter { $0.pathExtension == "json" }
        try expect(!archived.isEmpty, "Public archive fixtures are unavailable")
        for file in archived {
            let historical = try BenchmarkTrialData.load(file)
            try expect(historical.series.allSatisfy { $0.values.count == historical.count },
                "Historical trial alignment was lost: \(file.lastPathComponent)")
        }
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
