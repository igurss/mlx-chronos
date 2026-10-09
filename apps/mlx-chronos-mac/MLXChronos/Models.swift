import Foundation

enum AppSection: String, CaseIterable, Identifiable {
    case setup, benchmark, results, logs
    var id: String { rawValue }
    var title: String {
        switch self {
        case .setup: "Environment"
        case .benchmark: "Tests"
        case .results: "Results"
        case .logs: "Activity"
        }
    }
}

struct CLIOption: Decodable, Identifiable, Equatable {
    var name: String
    var flag: String?
    var kind: String
    var required: Bool
    var multiple: Bool
    var choices: [String]
    var defaultValue: String?
    var help: String
    var id: String { name }
    enum CodingKeys: String, CodingKey {
        case name, flag, kind, required, multiple, choices, help
        case defaultValue = "default"
    }
}

struct CLICommand: Decodable, Identifiable, Equatable {
    var name: String
    var help: String
    var options: [CLIOption]
    var id: String { name }
    var supportsRunConfigurations: Bool {
        name == "run" && ["config", "save_config"].allSatisfy { name in
            options.contains { $0.name == name }
        }
    }
    var title: String {
        ["run": "Standard benchmark", "matrix": "Multiple engines", "context": "Context length",
         "concurrency": "Concurrent requests", "energy": "System energy",
         "doctor": "Setup diagnosis", "validate": "Engine and model check",
         "models": "List models", "engines": "List engines", "history": "Result history",
         "compare": "Compare results", "submit": "Share a result", "upgrade": "Update mlx-chronos",
         "wizard": "Guided setup"][name] ?? name
    }
    var section: AppSection {
        if ["history", "compare", "submit"].contains(name) { return .results }
        if ["run", "matrix", "context", "concurrency", "energy"].contains(name) { return .benchmark }
        return .setup
    }
}

struct RunConfigurationDraft: Decodable {
    var values: [String: String]
}

struct RuntimeCandidate: Codable, Equatable, Identifiable {
    var pythonPath: String
    var sourcePath: String?
    var id: String { pythonPath + "|" + (sourcePath ?? "") }
}

struct RuntimeProbe: Decodable, Equatable {
    var pythonVersion: String
    var architecture: String
    var executable: String
    var prefix: String
    var basePrefix: String
    var isVirtualenv: Bool
    var externallyManaged: Bool
    var pipAvailable: Bool
    var packageVersion: String?
    var packagePath: String?
    var installer: String?
    var packageOwned: Bool
    var environmentManager: String
    var thermalState: String?
    var sourcePath: String?
    var enginePackages: [String: String]
    var commands: [CLICommand]
    var appContract: AppRuntimeContract?
    var error: String?
    var compatible: Bool {
        let parts = pythonVersion.split(separator: ".").compactMap { Int($0) }
        return parts.count >= 2 && parts[0] == 3 && parts[1] >= 10
    }
    var ready: Bool { compatible && packageVersion != nil && !commands.isEmpty && error == nil
        && (appContract.map { AppRuntimePolicy.issue($0) == nil } ?? true) }
    var thermalAvailable: Bool { ["nominal", "fair", "serious", "critical"].contains(thermalState ?? "") }
    enum CodingKeys: String, CodingKey {
        case architecture, executable, prefix, installer, commands, error
        case pythonVersion = "python_version", basePrefix = "base_prefix"
        case isVirtualenv = "is_virtualenv", externallyManaged = "externally_managed"
        case pipAvailable = "pip_available", packageVersion = "package_version"
        case packagePath = "package_path", thermalState = "thermal_state"
        case sourcePath = "source_path", enginePackages = "engine_packages"
        case appContract = "app_contract"
        case packageOwned = "package_owned", environmentManager = "environment_manager"
    }
}

struct RuntimeInstallation: Identifiable, Equatable {
    var candidate: RuntimeCandidate
    var probe: RuntimeProbe?
    var error: String?
    var isBuiltIn: Bool = false
    var id: String { candidate.id }
    var title: String {
        if isBuiltIn { return "App-managed mlx-chronos" }
        if let source = candidate.sourcePath { return "Source: " + URL(fileURLWithPath: source).lastPathComponent }
        return "mlx-chronos " + (probe?.packageVersion ?? "not installed")
    }
    var canUninstall: Bool {
        !isBuiltIn && candidate.sourcePath == nil && probe?.packagePath != nil && probe?.compatible == true &&
        probe?.pipAvailable == true && probe?.installer == "pip" && probe?.externallyManaged == false
        && probe?.packageOwned == true && probe?.environmentManager == "python"
    }
}

struct EngineStatus: Decodable, Identifiable, Equatable {
    var name: String
    var installed: Bool
    var running: Bool
    var version: String
    var endpoint: String
    var port: Int
    var models: [String]
    var loadedModels: [String]?
    var error: String?
    var installationEvidence: String?
    var applicationVersion: String?
    var clientVersion: String? = nil
    var versionSource: String? = nil
    var id: String { name }
    var displayName: String {
        ["omlx": "oMLX", "rapid-mlx": "Rapid-MLX", "vllm-mlx": "vLLM-MLX",
         "mlx-lm": "mlx-lm", "mlx-serve": "mlx-serve", "ollama": "Ollama", "lmstudio": "LM Studio"][name] ?? name
    }
    var versionLabel: String {
        switch versionSource {
        case "server_api", "runtime_probe", "unavailable": return "Serving engine / runtime version"
        case "client_cli", "client_package": return "Locally detected engine version"
        case "process_package": return "Server installation version (indirect)"
        default: return "Reported version (source unavailable)"
        }
    }
    enum CodingKeys: String, CodingKey {
        case name, installed, running, version, endpoint, port, models, error
        case loadedModels = "loaded_models", installationEvidence = "installation_evidence"
        case applicationVersion = "application_version"
        case clientVersion = "client_version", versionSource = "version_source"
    }
}

struct HardwareInfo: Decodable, Equatable {
    var chip: String
    var machineModel: String
    var memoryGB: Double
    var macOSVersion: String
    var pythonVersion: String
    var architecture: String
    var thermalState: String
    var powerSource: String
    var lowPowerMode: String
    enum CodingKeys: String, CodingKey {
        case chip, architecture
        case machineModel = "machine_model", memoryGB = "memory_gb"
        case macOSVersion = "macos_version", pythonVersion = "python_version"
        case thermalState = "thermal_state", powerSource = "power_source", lowPowerMode = "low_power_mode"
    }
}

struct EnvironmentSnapshot: Decodable {
    var hardware: HardwareInfo
    var engines: [EngineStatus]
    var macmonAvailable: Bool
    enum CodingKeys: String, CodingKey {
        case hardware, engines
        case macmonAvailable = "macmon_available"
    }
}

struct ResultSummary: Identifiable, Equatable {
    var url: URL
    var kind: String
    var engine: String
    var model: String
    var timestamp: String
    var recordedAt: Date
    var throughput: Double?
    var coldTTFT: Double?
    var cachedTTFT: Double?
    var systemRAMGrowth: Double?
    var swapGrowth: Double?
    var profile: String
    var id: URL { url }
    var isBenchmark: Bool { kind == "benchmark" }
    var displayProfile: String {
        switch kind {
        case "local_concurrency_diagnostic": return "Concurrent requests"
        case "local_context_diagnostic": return "Context length"
        case "local_matrix_diagnostic": return "Engine matrix"
        case "local_energy_diagnostic": return "System energy"
        case "unreadable": return "Unreadable JSON"
        case "unknown": return "Unknown JSON"
        default: return profile
        }
    }
}

struct CommandOutcome: Equatable {
    var title: String
    var output: String
    var succeeded: Bool
}

struct PendingAction: Identifiable {
    var id = UUID()
    var title: String
    var message: String
    var button: String
    var destructive: Bool = false
    var perform: () -> Void
}
