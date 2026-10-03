import SwiftUI

struct SetupView: View {
    @EnvironmentObject private var store: ChronosStore
    @State private var utility = "doctor"
    var body: some View {
        ScrollView {
            LazyVStack(alignment: .leading, spacing: 22) {
                ChronosCard("mlx-chronos and Python", subtitle: "The app-managed copy is the default. You can choose any detected installed copy or explicitly add a source checkout.") {
                    VStack(alignment: .leading, spacing: 18) {
                        Picker("Active installation", selection: Binding(
                            get: { store.selectedRuntimeID }, set: { store.selectRuntime($0) }
                        )) {
                            ForEach(store.runtimes) { runtime in
                                Text(runtime.title + " · " + runtime.candidate.pythonPath).tag(runtime.id)
                            }
                        }.disabled(store.isRunning).accessibilityIdentifier("environment.runtime")
                        ChronosActions {
                            Button("Detect installations") { store.scan() }
                            Button("Add Python / environment…") { store.choosePython() }
                            Button("Add source checkout…") { store.chooseSource() }
                        }.disabled(store.isRunning)
                        if let runtime = store.selectedRuntime {
                            VStack(alignment: .leading, spacing: 12) { runtimeDetails(runtime) }
                                .padding(16)
                                .background(ChronosStyle.inset, in: RoundedRectangle(cornerRadius: 10))
                        }
                        Divider()
                        Text("App-managed setup").font(ChronosStyle.label)
                        Toggle("Check and update the app-managed CLI at launch", isOn: $store.automaticRuntimeUpdates)
                            .toggleStyle(.checkbox).disabled(store.isRunning)
                        ChronosActions {
                            Button("Check / prepare compatible CLI") { store.prepareManagedRuntime() }
                                .buttonStyle(.borderedProminent).controlSize(.large)
                                .tint(ChronosStyle.primaryButton).foregroundStyle(.white)
                            Button("Repair private CLI") { store.prepareManagedRuntime(force: true) }
                            Button("Restore previous CLI") { store.rollbackManagedRuntime() }
                        }.disabled(store.isRunning)
                        ChronosHelp(store.runtimeUpdateNotice)
                        ChronosHelp("Private Python and compatible mlx-chronos are downloaded automatically. Existing Python installations are kept separate. First setup requires Internet; installed copies work offline.")
                        if let url = store.appReleaseURL, let version = store.appReleaseVersion {
                            Link("App \(version) available — open download page", destination: url)
                            ChronosHelp("The app download is separate from CLI updates.")
                        }
                        DisclosureGroup("Detected Python interpreters and installations") {
                            ForEach(store.runtimes) { runtime in
                                VStack(alignment: .leading, spacing: 7) {
                                    Text(runtime.candidate.pythonPath).font(ChronosStyle.code).textSelection(.enabled)
                                    Text(runtime.probe.map {
                                        "Python \($0.pythonVersion) · \($0.architecture) · " +
                                        ($0.compatible ? "compatible" : "requires Python 3.10 or newer") +
                                        ($0.packageVersion.map { " · mlx-chronos \($0)" } ?? " · mlx-chronos absent")
                                    } ?? runtime.error ?? "Not prepared")
                                    .font(ChronosStyle.help).foregroundStyle(ChronosStyle.secondary)
                                }.padding(.vertical, 8)
                            }
                        }.font(ChronosStyle.label)
                    }
                }
                ChronosCard("Mac and measurement conditions") {
                    VStack(alignment: .leading, spacing: 14) {
                        VStack(alignment: .leading, spacing: 10) {
                            Button("Refresh Mac and engines") { store.checkEnvironment() }
                                .disabled(store.isRunning || !store.selectedReady)
                            ChronosHelp("Detection does not load models or make inference requests.")
                        }
                        if let h = store.hardware {
                            InfoLine(title: "Chip / Mac", value: "\(h.chip) · \(h.machineModel)")
                            InfoLine(title: "Unified memory", value: "\(h.memoryGB) GB")
                            InfoLine(title: "macOS / architecture", value: "\(h.macOSVersion) · \(h.architecture)")
                            InfoLine(title: "Thermal state", value: h.thermalState)
                            InfoLine(title: "Power source / Low Power Mode", value: "\(h.powerSource) · \(h.lowPowerMode)")
                            InfoLine(title: "macmon (energy diagnostic)", value: store.macmonAvailable ? "Available" : "Not detected on PATH")
                        } else { ChronosHelp("Refresh to read the selected runtime and Mac conditions.") }
                    }
                }
                EnginesView()
                if !store.commands.isEmpty {
                    ChronosCard("Checks and maintenance") {
                        VStack(alignment: .leading, spacing: 20) {
                            Picker("Action", selection: $utility) {
                                ForEach(store.commands.filter { $0.section == .setup && $0.name != "wizard" }) { command in
                                    Text(command.title).tag(command.name)
                                }
                            }.accessibilityIdentifier("environment.command")
                        }
                    }
                    if let command = store.commands.first(where: { $0.name == utility }) {
                        CommandForm(command: command)
                    }
                }
            }
            .frame(maxWidth: 1100, alignment: .leading)
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(24)
        }.accessibilityIdentifier("environment.form")
    }

    @ViewBuilder
    private func runtimeDetails(_ runtime: RuntimeInstallation) -> some View {
        InfoLine(title: "Python executable", value: runtime.candidate.pythonPath)
        if let source = runtime.candidate.sourcePath { InfoLine(title: "Source checkout", value: source) }
        if let probe = runtime.probe {
            InfoLine(title: "Python", value: "\(probe.pythonVersion) · \(probe.architecture)")
            InfoLine(title: "mlx-chronos", value: probe.packageVersion ?? "Not installed")
            if let path = probe.packagePath { InfoLine(title: "Package location", value: path) }
            if !probe.packageOwned && probe.packageVersion != nil {
                Text("This package is inherited from another environment; it cannot be removed from this Python.")
                    .font(ChronosStyle.help).foregroundStyle(ChronosStyle.secondary)
            }
            if probe.environmentManager != "python" {
                Text("This environment is managed by \(probe.environmentManager); use that manager to remove its installation.")
                    .font(ChronosStyle.help).foregroundStyle(ChronosStyle.secondary)
            }
            InfoLine(title: "Thermal support", value: probe.thermalAvailable ? "Verified · \(probe.thermalState ?? "")" : "Not available in this Python")
            if let error = probe.error { ChronosHelp(error) }
            if let contract = probe.appContract, let issue = AppRuntimePolicy.issue(contract) { ChronosHelp(issue) }
            if !runtime.isBuiltIn && runtime.candidate.sourcePath == nil {
                ChronosActions {
                    Button("Use app-managed CLI instead") { store.installInSelectedRuntime() }
                        .disabled(store.isRunning)
                    Button("Remove this mlx-chronos copy", role: .destructive) { store.uninstallSelectedRuntime() }
                        .foregroundStyle(ChronosStyle.secondary)
                        .disabled(store.isRunning || !runtime.canUninstall)
                }
            }
        }
        if let error = runtime.error, runtime.probe == nil { Text(error).foregroundStyle(.secondary).textSelection(.enabled) }
    }
}
