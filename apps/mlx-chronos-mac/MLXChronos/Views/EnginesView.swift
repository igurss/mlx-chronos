import SwiftUI

struct EnginesView: View {
    @EnvironmentObject private var store: ChronosStore
    private var names: [String] {
        store.commands.flatMap(\.options).first(where: { $0.name == "engine" })?.choices ?? []
    }
    var body: some View {
        ChronosCard("Engines and local servers", subtitle: "Ports are explicit overrides for detection and every CLI action. Leave a port blank to use the CLI's configured/default port.") {
            VStack(alignment: .leading, spacing: 16) {
                ForEach(names, id: \.self) { name in
                    VStack(alignment: .leading, spacing: 14) {
                        HStack(spacing: 12) {
                            Text(displayName(name)).font(.system(size: 16, weight: .semibold))
                            if let engine = store.engineStatuses.first(where: { $0.name == name }) {
                                ChronosStatus(text: engine.running ? "Responding" : "No server", emphasized: engine.running)
                            }
                            Spacer()
                            Text("Port").font(ChronosStyle.label).foregroundStyle(ChronosStyle.secondary)
                            TextField("Default port", text: Binding(
                                get: { store.ports[name] ?? "" },
                                set: { store.ports[name] = $0 }
                            )).textFieldStyle(.roundedBorder).frame(width: 110).disabled(store.isRunning)
                                .accessibilityLabel("\(displayName(name)) port")
                                .accessibilityIdentifier("engine.\(name).port")
                        }
                        if let engine = store.engineStatuses.first(where: { $0.name == name }) {
                            InfoLine(title: "Installation", value: engine.installed ? "Detected" : "Not detected")
                            InfoLine(title: engine.versionLabel, value: engine.version)
                            InfoLine(title: "Installed client version", value: engine.clientVersion ?? "unknown")
                            if let version = engine.applicationVersion { InfoLine(title: "Application version", value: version) }
                            InfoLine(title: "Server", value: engine.running ? "Responding · \(engine.endpoint)" : "Not detected at \(engine.endpoint)")
                            if let path = engine.installationEvidence {
                                Text("Detected in another Python: \(path). If the CLI requires the engine module, select that environment and install mlx-chronos there.")
                                    .font(ChronosStyle.help).foregroundStyle(ChronosStyle.secondary).textSelection(.enabled)
                            }
                            if engine.running {
                                InfoLine(title: "Available model IDs", value: "\(engine.models.count)")
                                InfoLine(title: "Loaded in memory", value: engine.loadedModels.map { "\($0.count) verified by API" } ?? "Not exposed reliably by this integration")
                                DisclosureGroup("Model IDs") {
                                    ForEach(engine.models, id: \.self) { model in
                                        Text(model).font(ChronosStyle.code).textSelection(.enabled)
                                            .padding(.vertical, 3)
                                    }
                                }.font(ChronosStyle.label)
                            }
                            if let error = engine.error { ChronosHelp(error) }
                        } else { ChronosHelp("Refresh Environment after changing ports.") }
                    }
                    .padding(16)
                    .background(ChronosStyle.inset, in: RoundedRectangle(cornerRadius: 10))
                }
            }
        }
    }
    private func displayName(_ name: String) -> String {
        store.engineStatuses.first(where: { $0.name == name })?.displayName ?? name
    }
}
