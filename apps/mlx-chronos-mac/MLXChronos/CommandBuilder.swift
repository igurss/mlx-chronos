import Foundation

enum CommandError: LocalizedError {
    case invalid(String)
    var errorDescription: String? { if case .invalid(let text) = self { return text }; return nil }
}

enum CommandBuilder {
    static func initialValues(_ command: CLICommand, outputRoot: URL) -> [String: String] {
        var values: [String: String] = [:]
        for option in command.options {
            if option.kind == "boolean" { values[option.name] = "false" }
            else if !option.choices.isEmpty { values[option.name] = option.defaultValue ?? "" }
        }
        if command.options.contains(where: { $0.name == "output_dir" }) {
            let subfolder = ["matrix", "context", "concurrency", "energy"].contains(command.name) ? command.name : ""
            values["output_dir"] = subfolder.isEmpty ? outputRoot.path : outputRoot.appendingPathComponent(subfolder).path
        }
        if command.name == "submit" { values["dry_run"] = "true" }
        return values
    }

    static func arguments(_ command: CLICommand, values: [String: String]) throws -> [String] {
        var arguments = [command.name]
        var positionals: [String] = []
        for option in command.options {
            let value = (values[option.name] ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
            if option.kind == "boolean" {
                if value == "true", let flag = option.flag { arguments.append(flag) }
                continue
            }
            if value.isEmpty {
                if option.required { throw CommandError.invalid("Enter \(OptionPresentation.title(option.name)).") }
                continue
            }
            if !option.choices.isEmpty && !option.choices.contains(value) {
                throw CommandError.invalid("Choose a supported value for \(OptionPresentation.title(option.name)).")
            }
            if option.kind == "integer" && Int(value) == nil {
                throw CommandError.invalid("\(OptionPresentation.title(option.name)) must be a whole number.")
            }
            if option.kind == "number", !(Double(value)?.isFinite ?? false) {
                throw CommandError.invalid("\(OptionPresentation.title(option.name)) must be a finite number.")
            }
            if option.kind == "repeat" || option.multiple {
                let entries = value.components(separatedBy: .newlines).map { $0.trimmingCharacters(in: .whitespaces) }.filter { !$0.isEmpty }
                for entry in entries {
                    if let flag = option.flag { arguments += flagged(flag, entry) }
                    else { positionals.append(entry) }
                }
            } else if let flag = option.flag { arguments += flagged(flag, value) }
            else { positionals.append(value) }
        }
        try validate(command: command, values: values)
        // End of options protects positional filenames that begin with '-'.
        if !positionals.isEmpty { arguments += ["--"] + positionals }
        return arguments
    }

    static func applyingConfiguration(_ imported: [String: String], to command: CLICommand,
                                      current: [String: String]) throws -> [String: String] {
        guard command.supportsRunConfigurations else {
            throw CommandError.invalid("This CLI does not support saved run configurations.")
        }
        let allowed = Set(command.options.map(\.name)).subtracting(["config", "save_config", "output_dir", "submitted_by"])
        guard Set(imported.keys).isSubset(of: allowed) else {
            throw CommandError.invalid("The configuration contains unsupported settings.")
        }
        var values = current.merging(imported) { _, loaded in loaded }
        values.removeValue(forKey: "config")
        values.removeValue(forKey: "save_config")
        _ = try arguments(command, values: values)
        return values
    }

    private static func flagged(_ flag: String, _ value: String) -> [String] {
        // argparse otherwise treats a leading '-' in a literal model ID or
        // note as another option. This is argv construction, not shell syntax.
        value.hasPrefix("-") ? [flag + "=" + value] : [flag, value]
    }

    static func timeout(_ command: CLICommand, values: [String: String]) -> TimeInterval? {
        if command.section == .benchmark { return nil }
        let minimum: TimeInterval = command.name == "upgrade" ? 600 : 180
        let requested = values["timeout"].flatMap(Double.init) ?? 0
        // Preserve a user-selected network timeout rather than clipping it at
        // the app's general utility limit. Stop remains available at all times.
        return max(minimum, requested + 60)
    }

    static func resultDirectory(_ command: CLICommand, values: [String: String],
                                workingDirectory: URL) -> URL? {
        guard command.section == .benchmark,
              command.options.contains(where: { $0.name == "output_dir" }),
              let path = values["output_dir"]?.trimmingCharacters(in: .whitespacesAndNewlines),
              !path.isEmpty else { return nil }
        // Match the CLI's actual working directory; no shell expansion is used.
        let base = URL(fileURLWithPath: workingDirectory.path, isDirectory: true)
        return URL(fileURLWithPath: path, isDirectory: true, relativeTo: base).standardizedFileURL
    }

    private static func validate(command: CLICommand, values: [String: String]) throws {
        if command.name == "run", (values["model"] ?? "").trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            throw CommandError.invalid("Enter the exact model ID or load a run configuration.")
        }
        func numeric(_ key: String) -> Double? {
            let raw = values[key]?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
            if let number = Double(raw) { return number }
            return command.options.first(where: { $0.name == key })?.defaultValue.flatMap(Double.init)
        }
        for key in ["trials", "repeat", "rounds", "trials_per_level", "trials_per_bucket", "max_tokens", "min_tokens", "request_max_tokens", "limit", "timeout", "request_timeout_seconds", "ram_sample_interval", "idle_seconds"] {
            if let n = numeric(key), !n.isFinite || n <= 0 { throw CommandError.invalid("\(OptionPresentation.title(key)) must be greater than zero.") }
        }
        for key in ["cooldown_seconds", "settle_seconds"] {
            if let n = numeric(key), !n.isFinite || n < 0 { throw CommandError.invalid("\(OptionPresentation.title(key)) cannot be negative.") }
        }
        for (key, maxValue) in [("trials", 30), ("repeat", 20), ("rounds", 20), ("trials_per_bucket", 10), ("trials_per_level", 10)] {
            if let n = numeric(key), n > Double(maxValue) { throw CommandError.invalid("\(OptionPresentation.title(key)) cannot exceed \(maxValue).") }
        }
        if let n = numeric("sample_interval_ms"), !(100...1000).contains(n) { throw CommandError.invalid("Power sample interval must be between 100 and 1000 ms.") }
        if let min = numeric("min_tokens"), let max = numeric("max_tokens"), min > max { throw CommandError.invalid("Minimum output tokens cannot exceed maximum output tokens.") }
        for key in ["model_url", "endpoint"] {
            let raw = values[key]?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
            if !raw.isEmpty {
                guard let url = URLComponents(string: raw), ["http", "https"].contains(url.scheme?.lowercased() ?? ""), url.host != nil else { throw CommandError.invalid("\(OptionPresentation.title(key)) must be a complete HTTP or HTTPS URL.") }
            }
        }
        if command.name == "compare" && lines(values["files"]).count < 2 { throw CommandError.invalid("Choose at least two benchmark JSON files. The first is the reference.") }
        if command.name == "compare", let size = numeric("series_a_size"),
           size < 1 || size >= Double(lines(values["files"]).count) {
            throw CommandError.invalid("Series A must contain at least one file and leave at least one file for B.")
        }
        if command.name == "matrix" {
            let rows = lines(values["engine_model"])
            let pairs = rows.map { $0.split(separator: "=", maxSplits: 1, omittingEmptySubsequences: false).map { $0.trimmingCharacters(in: .whitespaces) } }
            let names = pairs.compactMap { $0.first }
            guard !rows.isEmpty, pairs.allSatisfy({ $0.count == 2 && !$0[0].isEmpty && !$0[1].isEmpty }), Set(names).count == rows.count else { throw CommandError.invalid("Add different engines, one ENGINE=MODEL entry per line.") }
        }
        if command.name == "concurrency", let raw = values["levels"], !raw.isEmpty {
            let parts = raw.split(separator: ",", omittingEmptySubsequences: false)
            let levels = parts.compactMap { Int($0.trimmingCharacters(in: .whitespaces)) }
            guard levels.count == parts.count, Set(levels).count == levels.count, levels.allSatisfy({ (1...32).contains($0) }) else { throw CommandError.invalid("Concurrency levels must be distinct whole numbers between 1 and 32, separated by commas.") }
        }
        if command.name == "run", values["publishable"] == "true" {
            if (values["model_url"] ?? "").isEmpty { throw CommandError.invalid("Public-ready runs require the model's reference URL.") }
            if values["format"] == "markdown" || values["connection_mode"] == "per_request" || !(values["min_tokens"] ?? "").isEmpty { throw CommandError.invalid("Public-ready runs require JSON output, persistent connections and no minimum-token override.") }
        }
        if command.name == "doctor", !(values["model"] ?? "").isEmpty, (values["engine"] ?? "").isEmpty { throw CommandError.invalid("Choose an engine when inspecting a model.") }
    }

    static func lines(_ value: String?) -> [String] {
        (value ?? "").components(separatedBy: .newlines).map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }.filter { !$0.isEmpty }
    }

    static func display(_ arguments: [String]) -> String {
        arguments.map { "'" + $0.replacingOccurrences(of: "'", with: "'\\''") + "'" }.joined(separator: " ")
    }
}

enum OptionPresentation {
    static let compareGuidance = "Compare sealed benchmark results against the first file. To compare series with an updated CLI, list A files first, then B files, and enter the number of files in A. Series mode shows medians and observed dispersion; it does not test superiority. Invalid schemas or seals are rejected. Other differences produce warnings, not a block. ~ marks estimated percentages and n/a an unavailable percentage. Output follows the selected CLI."

    static func title(_ name: String) -> String {
        ["engine": "Engine", "model": "Exact model ID", "model_url": "Model reference URL",
         "quantization": "Quantization / format", "profile": "Benchmark profile",
         "publishable": "Public-ready settings", "output_dir": "Result folder", "format": "Report format",
         "engine_model": "Engine → model mapping", "engine_opt": "Declared server settings",
         "files": "Benchmark JSON files", "file": "Benchmark JSON file", "dry_run": "Validate without sending",
         "series_a_size": "Files in series A (optional)",
         "submitted_by": "Contributor handle (optional)", "trials": "Trials", "repeat": "Complete repetitions",
         "max_tokens": "Maximum output tokens", "min_tokens": "Minimum output tokens",
         "ram_sample_interval": "RAM sampling interval (seconds)", "cooldown_seconds": "Cooldown (seconds)",
         "connection_mode": "HTTP connections", "preflight": "Extra model access check",
         "levels": "Concurrent request levels", "request_max_tokens": "Output tokens per request",
         "trials_per_level": "Measured waves per level", "buckets": "Context length buckets",
         "trials_per_bucket": "Trials per bucket", "request_timeout_seconds": "Request timeout (seconds)",
         "settle_seconds": "Settle after warm-up (seconds)", "idle_seconds": "No-request phase (seconds)",
         "sample_interval_ms": "Power sampling interval (milliseconds)", "timeout": "Timeout (seconds)",
         "rounds": "Complete engine sweeps", "seed": "Order seed (optional)", "limit": "Maximum results",
         "email": "Contact email (optional)", "endpoint": "Submission endpoint (optional)", "notes": "Notes"][name]
        ?? name.replacingOccurrences(of: "_", with: " ").capitalized
    }
    static func isAdvanced(_ name: String, command: String) -> Bool {
        if command == "run" { return ["trials", "repeat", "max_tokens", "min_tokens", "ram_sample_interval", "cooldown_seconds", "connection_mode", "preflight", "engine_opt", "submitted_by", "notes"].contains(name) }
        return ["seed", "min_tokens", "ram_sample_interval", "connection_mode", "request_timeout_seconds", "endpoint", "timeout", "submitted_by", "notes"].contains(name)
    }
}
