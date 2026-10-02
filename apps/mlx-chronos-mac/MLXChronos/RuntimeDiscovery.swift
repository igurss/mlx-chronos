import Foundation

enum RuntimeDiscovery {
    static var applicationDirectory: URL {
        FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/Application Support/MLXChronos", isDirectory: true)
    }
    static var managedCandidate: RuntimeCandidate {
        RuntimeCandidate(pythonPath: applicationDirectory.appendingPathComponent("venv/bin/python").path)
    }
    static func candidates(registered: [RuntimeCandidate]) -> [RuntimeCandidate] {
        let fm = FileManager.default, home = fm.homeDirectoryForCurrentUser
        var paths = [managedCandidate] + registered
        let inherited = (ProcessInfo.processInfo.environment["PATH"] ?? "").split(separator: ":").map(String.init)
        for directory in ["/opt/homebrew/bin", "/usr/local/bin", "/usr/bin"] + inherited {
            for filename in ["python3"] + (10...15).map({ "python3.\($0)" }) {
                paths.append(RuntimeCandidate(pythonPath: URL(fileURLWithPath: directory).appendingPathComponent(filename).path))
            }
        }
        let roots = ["/Library/Frameworks/Python.framework/Versions", home.appendingPathComponent(".pyenv/versions").path,
                     home.appendingPathComponent(".local/share/uv/python").path, home.appendingPathComponent(".conda/envs").path,
                     home.appendingPathComponent("miniconda3/envs").path, home.appendingPathComponent("anaconda3/envs").path,
                     home.appendingPathComponent(".local/share/pipx/venvs").path, home.appendingPathComponent(".local/pipx/venvs").path]
        for root in roots {
            let children = (try? fm.contentsOfDirectory(atPath: root)) ?? []
            for child in children.sorted().prefix(40) {
                paths.append(RuntimeCandidate(pythonPath: URL(fileURLWithPath: root).appendingPathComponent(child + "/bin/python3").path))
                paths.append(RuntimeCandidate(pythonPath: URL(fileURLWithPath: root).appendingPathComponent(child + "/bin/python").path))
            }
        }
        for relative in ["miniconda3/bin/python3", "anaconda3/bin/python3", "Desktop/mlx-chronos/.venv/bin/python"] {
            paths.append(RuntimeCandidate(pythonPath: home.appendingPathComponent(relative).path))
        }
        var seen = Set<String>()
        return paths.filter { candidate in
            if candidate.pythonPath == "/usr/bin/python3" {
                let available = fm.isExecutableFile(atPath: "/Library/Developer/CommandLineTools/usr/bin/python3") ||
                    fm.isExecutableFile(atPath: "/Applications/Xcode.app/Contents/Developer/usr/bin/python3")
                // Avoid triggering Apple's developer-tools installation prompt.
                guard available else { return false }
            }
            guard fm.isExecutableFile(atPath: candidate.pythonPath) else { return false }
            let python = URL(fileURLWithPath: candidate.pythonPath)
            let root = python.deletingLastPathComponent().deletingLastPathComponent()
            // Different venvs can symlink to the same executable: preserve them.
            let identity = fm.fileExists(atPath: root.appendingPathComponent("pyvenv.cfg").path)
                ? root.standardizedFileURL.path : python.resolvingSymlinksInPath().path
            return seen.insert(identity + "|" + (candidate.sourcePath ?? "")).inserted
        }.prefix(128).map { $0 }
    }

    static func environment(extraBinPaths: [String] = [], ports: [String: String] = [:]) -> [String: String] {
        var environment = ProcessInfo.processInfo.environment
        for key in ["PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV", "CONDA_PREFIX", "MLX_CHRONOS_SUBMITTER_EMAIL", "MLX_CHRONOS_SUBMIT_ENDPOINT"] { environment.removeValue(forKey: key) }
        let home = FileManager.default.homeDirectoryForCurrentUser
        let paths = extraBinPaths + ["/opt/homebrew/bin", "/usr/local/bin", home.appendingPathComponent(".local/bin").path,
                                    home.appendingPathComponent(".cargo/bin").path, home.appendingPathComponent(".lmstudio/bin").path,
                                    "/usr/bin", "/bin", "/usr/sbin", "/sbin"]
            + (environment["PATH"] ?? "").split(separator: ":").map(String.init)
        var seen = Set<String>()
        environment["PATH"] = paths.filter { seen.insert($0).inserted }.joined(separator: ":")
        environment["PYTHONUNBUFFERED"] = "1"
        environment["NO_COLOR"] = "1"
        environment["MLX_CHRONOS_DISABLE_UPDATE_CHECK"] = "1"
        for (name, value) in ports {
            let key = "MLX_CHRONOS_" + name.uppercased().replacingOccurrences(of: "-", with: "_") + "_PORT"
            if let port = Int(value), (1...65535).contains(port) { environment[key] = value }
        }
        return environment
    }

    static func bridgeArguments(_ candidate: RuntimeCandidate, bridge: URL, action: String, arguments: [String] = []) -> [String] {
        var args = ["-I", "-B", "-u", bridge.path]
        if let source = candidate.sourcePath { args += ["--source", source] }
        return args + [action] + arguments
    }
}
