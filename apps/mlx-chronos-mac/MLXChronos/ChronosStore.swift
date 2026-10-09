import AppKit
import Combine
import Foundation

@MainActor
final class ChronosStore: ObservableObject {
    @Published var runtimes: [RuntimeInstallation] = []
    @Published var selectedRuntimeID: String {
        didSet {
            UserDefaults.standard.set(selectedRuntimeID, forKey: "MLXChronos.selectedRuntime")
            hardware = nil; engineStatuses = []; outcome = nil
        }
    }
    @Published var outputDirectory: URL {
        didSet {
            UserDefaults.standard.set(outputDirectory.path, forKey: "MLXChronos.outputDirectoryPath")
            browseResults(at: outputDirectory)
        }
    }
    @Published private(set) var resultsDirectory: URL
    @Published var ports: [String: String] {
        didSet {
            UserDefaults.standard.set(ports, forKey: "MLXChronos.ports")
            if ports != oldValue { engineStatuses = [] }
        }
    }
    @Published var hardware: HardwareInfo?
    @Published var engineStatuses: [EngineStatus] = []
    @Published var macmonAvailable = false
    @Published var results: [ResultSummary] = []
    @Published private(set) var resultsRevision = UUID()
    @Published private(set) var resultsNotice: String?
    private let resultCache = ResultSummaryCache()
    @Published var drafts: [String: [String: String]] = [:]
    @Published var runConfigurationNotice: String?
    @Published var operation: String?
    @Published var isStopping = false
    @Published var lastError: String?
    @Published var outcome: CommandOutcome?
    @Published var pendingAction: PendingAction?
    let log = CommandLog()

    private var registered: [RuntimeCandidate]
    private var runners: [ProcessRunner] = []
    private var task: Task<Void, Never>?
    private var resultsTask: Task<Void, Never>?
    private var resultRevision = UUID()
    private var hasScanned = false
    private let runtimeManager = RuntimeManager()
    @Published private(set) var runtimeUpdateNotice = "Updates have not been checked yet."
    @Published private(set) var appReleaseURL: URL?
    @Published private(set) var appReleaseVersion: String?
    @Published var automaticRuntimeUpdates = UserDefaults.standard.object(forKey: "MLXChronos.automaticRuntimeUpdates") as? Bool ?? true {
        didSet { UserDefaults.standard.set(automaticRuntimeUpdates, forKey: "MLXChronos.automaticRuntimeUpdates") }
    }

    var isRunning: Bool { operation != nil }
    var selectedRuntime: RuntimeInstallation? { runtimes.first { $0.id == selectedRuntimeID } }
    var commands: [CLICommand] { selectedRuntime?.probe?.commands ?? [] }
    var selectedReady: Bool { selectedRuntime?.probe?.ready == true }

    init() {
        let defaults = UserDefaults.standard
        selectedRuntimeID = defaults.string(forKey: "MLXChronos.selectedRuntime") ?? RuntimeDiscovery.managedCandidate.id
        let initialOutput = defaults.string(forKey: "MLXChronos.outputDirectoryPath").map(URL.init(fileURLWithPath:))
            ?? RuntimeDiscovery.applicationDirectory.appendingPathComponent("results", isDirectory: true)
        outputDirectory = initialOutput
        resultsDirectory = URL(fileURLWithPath: defaults.string(forKey: "MLXChronos.resultsDirectoryPath")
            ?? initialOutput.path, isDirectory: true)
        ports = defaults.dictionary(forKey: "MLXChronos.ports") as? [String: String] ?? [:]
        registered = defaults.data(forKey: "MLXChronos.registeredRuntimes")
            .flatMap { try? JSONDecoder().decode([RuntimeCandidate].self, from: $0) } ?? []
        // Migrate an explicitly selected interpreter from the first prototype.
        if let path = defaults.string(forKey: "MLXChronos.pythonPath") {
            let candidate = RuntimeCandidate(pythonPath: path)
            if !registered.contains(candidate) { registered.append(candidate) }
        }
        runtimes = [RuntimeInstallation(candidate: RuntimeDiscovery.managedCandidate, isBuiltIn: true)]
        loadResults()
    }

    func scanOnFirstAppearance() {
        guard !hasScanned else { return }
        hasScanned = true
        start("Detecting installations and checking updates") {
            try await self.scanInstallations()
            if self.automaticRuntimeUpdates { await self.synchronizeManagedRuntime() }
            if let release = await self.runtimeManager.checkAppRelease() {
                self.appReleaseVersion = release.0; self.appReleaseURL = release.1
            }
            if self.selectedReady { try await self.readEnvironment() }
        }
    }

    func scan() {
        start("Detecting installations") {
            try await self.scanInstallations()
            if self.selectedReady { try await self.readEnvironment() }
        }
    }

    private func scanInstallations() async throws {
        let bridge = try bridgeURL()
        let candidates = RuntimeDiscovery.candidates(registered: registered)
        var found: [RuntimeInstallation] = []
        let environment = RuntimeDiscovery.environment(ports: ports)
        for start in stride(from: 0, to: candidates.count, by: 3) {
            try Task.checkCancellation()
            let batch = candidates[start..<min(start + 3, candidates.count)]
            let work = batch.map { ($0, ProcessRunner()) }
            runners += work.map { $0.1 }
            let installations = await withTaskGroup(of: RuntimeInstallation.self) { group in
                for (candidate, runner) in work {
                    group.addTask {
                        let response = await runner.run(
                            executable: candidate.pythonPath,
                            arguments: RuntimeDiscovery.bridgeArguments(candidate, bridge: bridge, action: "probe"),
                            directory: FileManager.default.temporaryDirectory,
                            environment: environment, timeout: 20
                        )
                        let probe = response.succeeded ? response.stdout.data(using: .utf8)
                            .flatMap { try? JSONDecoder().decode(RuntimeProbe.self, from: $0) } : nil
                        let error = probe == nil ? (response.timedOut ? "Python detection timed out." : String(response.stderr.suffix(2000))) : probe?.error
                        return RuntimeInstallation(candidate: candidate, probe: probe, error: error,
                            isBuiltIn: RuntimeDiscovery.isManaged(candidate))
                    }
                }
                var values: [RuntimeInstallation] = []
                for await value in group { values.append(value) }
                return values
            }
            found += installations
            runners.removeAll { runner in work.contains { $0.1 === runner } }
        }
        try Task.checkCancellation()
        if !found.contains(where: \.isBuiltIn) {
            found.insert(RuntimeInstallation(candidate: RuntimeDiscovery.managedCandidate, isBuiltIn: true), at: 0)
        }
        if !found.contains(where: { $0.id == selectedRuntimeID }),
           let missing = runtimes.first(where: { $0.id == selectedRuntimeID }) {
            var value = missing; value.probe = nil; value.error = "The selected installation is no longer available."
            found.append(value)
        }
        runtimes = found.sorted {
            if $0.isBuiltIn != $1.isBuiltIn { return $0.isBuiltIn }
            return ($0.probe?.ready == true ? "0" : "1") + $0.id < ($1.probe?.ready == true ? "0" : "1") + $1.id
        }
        log.append("Detected \(found.filter { $0.probe?.packageVersion != nil }.count) mlx-chronos installations.\n")
    }

    func selectRuntime(_ id: String) {
        guard !isRunning else { return }
        selectedRuntimeID = id
        drafts = [:]
        if selectedReady { checkEnvironment() }
    }

    func checkEnvironment() {
        start("Checking Mac and engines") { try await self.readEnvironment() }
    }

    private func readEnvironment() async throws {
        guard let runtime = selectedRuntime, runtime.probe?.ready == true else {
            throw CommandError.invalid("Prepare the app-managed installation or select a working mlx-chronos installation.")
        }
        let result = try await execute(runtime.candidate, action: "snapshot", timeout: 75, stream: false)
        guard let data = result.stdout.data(using: .utf8),
              let snapshot = try? JSONDecoder().decode(EnvironmentSnapshot.self, from: data) else {
            throw CommandError.invalid("Environment detection returned invalid data. Details are in Activity.")
        }
        hardware = snapshot.hardware
        macmonAvailable = snapshot.macmonAvailable
        engineStatuses = snapshot.engines.map { status in
            var status = status
            if !status.installed {
                let evidence = runtimes.filter { $0.probe?.enginePackages[status.name] != nil }
                if let found = evidence.first {
                    status.installed = true
                    status.installationEvidence = found.candidate.pythonPath
                    if status.clientVersion == nil || status.clientVersion == "unknown" {
                        status.clientVersion = found.probe?.enginePackages[status.name]
                    }
                }
            }
            return status
        }
        log.append("Mac and engine information refreshed; no models were loaded or probed with inference.\n")
    }

    func choosePython() {
        guard !isRunning else { return }
        let panel = NSOpenPanel()
        panel.title = "Choose Python or a virtual environment"
        panel.canChooseDirectories = true; panel.canChooseFiles = true
        if panel.runModal() == .OK, let url = panel.url {
            var directory: ObjCBool = false
            FileManager.default.fileExists(atPath: url.path, isDirectory: &directory)
            let python = directory.boolValue ? url.appendingPathComponent("bin/python") : url
            guard FileManager.default.isExecutableFile(atPath: python.path) else {
                lastError = "Choose an executable Python file, or an environment containing bin/python."; return
            }
            register(RuntimeCandidate(pythonPath: python.path))
            scan()
        }
    }

    func chooseSource() {
        guard !isRunning else { return }
        let panel = NSOpenPanel()
        panel.title = "Choose an mlx-chronos source checkout"
        panel.canChooseDirectories = true; panel.canChooseFiles = false
        guard let python = selectedRuntime?.candidate.pythonPath,
              FileManager.default.isExecutableFile(atPath: python) else {
            lastError = "Select a detected Python interpreter first."; return
        }
        if panel.runModal() == .OK, let url = panel.url {
            guard FileManager.default.fileExists(atPath: url.appendingPathComponent("mlx_chronos/cli.py").path),
                  FileManager.default.fileExists(atPath: url.appendingPathComponent("pyproject.toml").path) else {
                lastError = "This folder is not an mlx-chronos source checkout."; return
            }
            let candidate = RuntimeCandidate(pythonPath: python, sourcePath: url.path)
            register(candidate); selectedRuntimeID = candidate.id
            scan()
        }
    }

    private func register(_ candidate: RuntimeCandidate) {
        if !registered.contains(candidate) { registered.append(candidate) }
        UserDefaults.standard.set(try? JSONEncoder().encode(registered), forKey: "MLXChronos.registeredRuntimes")
    }

    func prepareManagedRuntime(force: Bool = false) {
        start("Checking app-managed runtime") {
            await self.synchronizeManagedRuntime(force: force, select: true)
            if self.selectedReady { try await self.readEnvironment() }
        }
    }

    private func synchronizeManagedRuntime(force: Bool = false, select: Bool = false) async {
        let wasManaged = selectedRuntime.map { RuntimeDiscovery.isManaged($0.candidate) } ?? true
        let logger = log
        do {
            let result = try await runtimeManager.synchronize(bridge: bridgeURL(), force: force,
                status: { self.operation = $0 }, log: { text in Task { @MainActor in logger.append(text) } })
            runtimeUpdateNotice = result.notice
            try await scanInstallations()
            if let candidate = result.candidate, wasManaged || select {
                selectedRuntimeID = candidate.id; drafts = [:]
            }
        } catch is CancellationError {
            runtimeUpdateNotice = "Runtime setup stopped. The previous copy was kept."
        } catch {
            runtimeUpdateNotice = "Could not prepare or check updates: " + error.localizedDescription
            log.append(runtimeUpdateNotice + "\n")
        }
    }

    func rollbackManagedRuntime() {
        start("Restoring previous CLI") {
            let candidate = try await self.runtimeManager.rollback(bridge: self.bridgeURL())
            self.automaticRuntimeUpdates = false
            try await self.scanInstallations()
            self.selectedRuntimeID = candidate.id; self.drafts = [:]
            self.runtimeUpdateNotice = "Previous CLI restored. Automatic CLI updates are paused; enable them when ready."
            if self.selectedReady { try await self.readEnvironment() }
        }
    }

    func installInSelectedRuntime() {
        // Installation always targets the private app copy. External Python,
        // source checkouts and package-manager environments are never upgraded.
        prepareManagedRuntime()
    }

    func uninstallSelectedRuntime() {
        guard let runtime = selectedRuntime, runtime.canUninstall else {
            lastError = "Only a verified external pip installation can be removed here. App-managed packages, source files and Python interpreters are protected."; return
        }
        pendingAction = PendingAction(title: "Remove this mlx-chronos installation?",
            message: "Remove only the mlx-chronos package from:\n\(runtime.probe?.packagePath ?? "")\n\nPython, other packages, source checkouts and saved results are kept.",
            button: "Remove mlx-chronos", destructive: true) {
            self.start("Removing mlx-chronos") {
                // Probe again immediately before the destructive operation.
                let current = try await self.execute(runtime.candidate, action: "probe", timeout: 20, stream: false)
                guard let data = current.stdout.data(using: .utf8),
                      let probe = try? JSONDecoder().decode(RuntimeProbe.self, from: data),
                      RuntimeInstallation(candidate: runtime.candidate, probe: probe).canUninstall,
                      probe.packagePath == runtime.probe?.packagePath else {
                    throw CommandError.invalid("The installation changed since detection. Detect it again before removing it.")
                }
                _ = try await self.execute(runtime.candidate, action: "pip", arguments: ["uninstall", "-y", "mlx-chronos"], timeout: 120)
                try await self.scanInstallations()
            }
        }
    }

    func values(for command: CLICommand) -> [String: String] {
        drafts[command.name] ?? CommandBuilder.initialValues(command,
            outputRoot: command.name == "history" ? resultsDirectory : outputDirectory)
    }
    func executionValues(for command: CLICommand) -> [String: String] {
        var values = values(for: command)
        if command.section == .benchmark,
           (values["output_dir"] ?? "").trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
           let defaultFolder = CommandBuilder.initialValues(command, outputRoot: outputDirectory)["output_dir"] {
            values["output_dir"] = defaultFolder
        }
        return values
    }
    func setValue(_ value: String, option: String, command: CLICommand) {
        var values = values(for: command)
        if option == "engine", values[option] != value { values["model"] = "" }
        values[option] = value
        drafts[command.name] = values
        if command.name == "run" { runConfigurationNotice = nil }
    }

    func loadRunConfiguration(_ command: CLICommand) {
        guard !isRunning, command.supportsRunConfigurations,
              let runtime = selectedRuntime, runtime.probe?.ready == true else { return }
        let panel = NSOpenPanel()
        panel.canChooseDirectories = false; panel.allowsMultipleSelection = false
        panel.allowedContentTypes = [.json]
        guard panel.runModal() == .OK, let url = panel.url else { return }
        start("Load run configuration") {
            let response = try await self.execute(runtime.candidate, action: "config-read",
                arguments: [url.path], timeout: 30, stream: false)
            let imported = try JSONDecoder().decode(RunConfigurationDraft.self, from: Data(response.stdout.utf8))
            let values = try CommandBuilder.applyingConfiguration(imported.values, to: command,
                current: self.values(for: command))
            self.drafts[command.name] = values
            self.runConfigurationNotice = "Loaded \(url.lastPathComponent). Review the settings, then choose Start test."
            let notice = response.stderr.trimmingCharacters(in: .whitespacesAndNewlines)
            if !notice.isEmpty { self.runConfigurationNotice? += "\n" + notice }
        }
    }

    func saveRunConfiguration(_ command: CLICommand) {
        guard !isRunning, command.supportsRunConfigurations,
              let runtime = selectedRuntime, runtime.probe?.ready == true else { return }
        do {
            let values = executionValues(for: command)
            let arguments = try CommandBuilder.arguments(command, values: values)
            let panel = NSSavePanel()
            panel.allowedContentTypes = [.json]; panel.nameFieldStringValue = "mlx-chronos-run.json"
            guard panel.runModal() == .OK, let url = panel.url else { return }
            start("Save run configuration") {
                let response = try await self.execute(runtime.candidate, action: "config-save",
                    arguments: [url.path] + arguments, timeout: 30, stream: false)
                let imported = try JSONDecoder().decode(RunConfigurationDraft.self, from: Data(response.stdout.utf8))
                self.drafts[command.name] = try CommandBuilder.applyingConfiguration(imported.values,
                    to: command, current: values)
                self.runConfigurationNotice = "Saved \(url.lastPathComponent). No test was started."
            }
        } catch { lastError = error.localizedDescription }
    }
    func chooseFiles(option: CLIOption, command: CLICommand) {
        let panel = NSOpenPanel()
        panel.canChooseFiles = option.name != "output_dir"
        panel.canChooseDirectories = option.name == "output_dir"
        panel.canCreateDirectories = option.name == "output_dir"
        panel.allowsMultipleSelection = option.multiple
        if panel.runModal() == .OK {
            setValue(panel.urls.map(\.path).joined(separator: "\n"), option: option.name, command: command)
        }
    }
    func chooseOutputDirectory() {
        let panel = NSOpenPanel()
        panel.canChooseDirectories = true; panel.canChooseFiles = false; panel.canCreateDirectories = true
        panel.directoryURL = resultsDirectory
        if panel.runModal() == .OK, let url = panel.url { outputDirectory = url; drafts = [:] }
    }

    func run(_ command: CLICommand) {
        guard !isRunning else { return }
        if command.name == "upgrade" { prepareManagedRuntime(); return }
        do {
            let values = executionValues(for: command)
            let arguments = try CommandBuilder.arguments(command, values: values)
            guard let runtime = selectedRuntime, runtime.probe?.ready == true else {
                throw CommandError.invalid("Choose a working mlx-chronos installation in Environment.")
            }
            if command.name == "energy" && !macmonAvailable {
                throw CommandError.invalid("Energy requires macmon on PATH. Install macmon, then refresh Environment.")
            }
            let timeout = CommandBuilder.timeout(command, values: values)
            let resultDirectory = CommandBuilder.resultDirectory(command, values: values,
                workingDirectory: FileManager.default.temporaryDirectory)
            let commandPorts = try CommandBuilder.serverPorts(command, values: values, configured: ports)
            let action = { self.executeCommand(command, arguments: arguments, candidate: runtime.candidate,
                timeout: timeout, resultDirectory: resultDirectory, portOverrides: commandPorts) }
            if command.name == "submit" && values["dry_run"] != "true" {
                pendingAction = PendingAction(title: "Send this result?",
                    message: "The CLI validates and sends the full result JSON to:\n\(values["endpoint"].flatMap { $0.isEmpty ? nil : $0 } ?? "the mlx-chronos project inbox")\n\nFile: \(values["file"] ?? "")\nContact: \(values["email"].flatMap { $0.isEmpty ? nil : $0 } ?? "anonymous")",
                    button: "Send result", perform: action)
            } else { action() }
        } catch { lastError = error.localizedDescription }
    }

    private func executeCommand(_ command: CLICommand, arguments: [String], candidate: RuntimeCandidate,
                                timeout: TimeInterval?, resultDirectory: URL?, portOverrides: [String: String]) {
        start(command.title) {
            // Partial results and failed-matrix manifests are useful too. Refresh
            // on success, failure or Stop, without changing future test defaults.
            defer {
                if let resultDirectory { self.browseResults(at: resultDirectory) }
                else { self.loadResults() }
            }
            let response = try await self.execute(candidate, action: "cli", arguments: arguments,
                timeout: timeout, requireSuccess: false, portOverrides: portOverrides)
            self.outcome = CommandOutcome(title: command.title,
                output: String((response.stdout + response.stderr).suffix(120_000)), succeeded: response.succeeded)
            if !response.succeeded { throw CommandError.invalid(self.failure(response)) }

        }
    }

    private func start(_ label: String, body: @escaping @MainActor () async throws -> Void) {
        guard !isRunning else { return }
        operation = label; isStopping = false; lastError = nil; outcome = nil
        task = Task {
            do { try await body() }
            catch is CancellationError { log.append("Stopped.\n") }
            catch { lastError = error.localizedDescription; log.append("Error: \(error.localizedDescription)\n") }
            log.flush(); runners = []; operation = nil; isStopping = false; task = nil
        }
    }

    private func execute(_ candidate: RuntimeCandidate, action: String, arguments: [String] = [],
                         timeout: TimeInterval?, stream: Bool = true, requireSuccess: Bool = true,
                         portOverrides: [String: String] = [:]) async throws -> ProcessResult {
        try Task.checkCancellation()
        let operationPorts = action == "snapshot" ? try CommandBuilder.validatedPorts(ports) : portOverrides
        let bridge = try bridgeURL(), runner = ProcessRunner()
        runners.append(runner)
        defer { runners.removeAll { $0 === runner } }
        if stream { log.append("$ \(CommandBuilder.display([candidate.pythonPath, action] + arguments))\n") }
        let logger = log
        let bins = runtimes.compactMap { $0.probe?.enginePackages.isEmpty == false ? URL(fileURLWithPath: $0.candidate.pythonPath).deletingLastPathComponent().path : nil }
        let result = await runner.run(executable: candidate.pythonPath,
            arguments: RuntimeDiscovery.bridgeArguments(candidate, bridge: bridge, action: action, arguments: arguments),
            directory: FileManager.default.temporaryDirectory,
            environment: RuntimeDiscovery.environment(extraBinPaths: bins, ports: operationPorts), timeout: timeout,
            onOutput: { text in if stream { Task { @MainActor in logger.append(text) } } })
        if !stream && !result.succeeded { log.append(result.stderr + "\n") }
        if result.cancelled || Task.isCancelled { throw CancellationError() }
        if requireSuccess && !result.succeeded { throw CommandError.invalid(failure(result)) }
        return result
    }

    private func failure(_ result: ProcessResult) -> String {
        if result.timedOut { return "The operation exceeded its time limit and was stopped. See Activity." }
        if result.outputTruncated { return "The command produced too much output; captured data was limited. See Activity." }
        let text = result.stderr.trimmingCharacters(in: .whitespacesAndNewlines)
        return text.isEmpty ? "The CLI exited with code \(result.exitCode). See Activity." : String(text.suffix(3000))
    }

    func stop() {
        guard isRunning else { return }
        isStopping = true; task?.cancel(); runtimeManager.stop(); runners.forEach { $0.stop() }
    }

    func browseResults(at directory: URL) {
        let normalized = URL(fileURLWithPath: directory.path, isDirectory: true).standardizedFileURL
        if resultsDirectory.path != normalized.path { results = [] }
        resultsDirectory = normalized
        UserDefaults.standard.set(resultsDirectory.path, forKey: "MLXChronos.resultsDirectoryPath")
        if var history = drafts["history"] {
            history["output_dir"] = resultsDirectory.path
            drafts["history"] = history
        }
        loadResults()
    }

    func showDefaultResults() { browseResults(at: outputDirectory) }

    func loadResults() {
        resultRevision = UUID()
        let revision = resultRevision, root = resultsDirectory
        resultsTask?.cancel()
        let cache = resultCache
        resultsTask = Task {
            let worker = Task.detached(priority: .utility) {
                try ResultRepository.scan(root, cache: cache, checkCancellation: { try Task.checkCancellation() })
            }
            do {
                let listing = try await withTaskCancellationHandler {
                    try await worker.value
                } onCancel: { worker.cancel() }
                guard !Task.isCancelled, revision == resultRevision else { return }
                results = listing.results
                resultsNotice = listing.notice
                resultsRevision = revision
            } catch is CancellationError {
                // A newer refresh owns the displayed list.
            } catch {
                guard !Task.isCancelled, revision == resultRevision else { return }
                resultsNotice = "Could not scan results: " + error.localizedDescription
            }
        }
    }

    func reveal(_ url: URL) { NSWorkspace.shared.activateFileViewerSelecting([url]) }
    private func bridgeURL() throws -> URL {
        guard let url = Bundle.main.url(forResource: "chronos_bridge", withExtension: "py", subdirectory: "Resources") else {
            throw CommandError.invalid("The app's CLI adapter is missing. Rebuild or reinstall the app.")
        }
        return url
    }

}
