import SwiftUI

struct CommandForm: View {
    @EnvironmentObject private var store: ChronosStore
    var command: CLICommand
    @State private var advanced = false
    @State private var preview = false
    private var formOptions: [CLIOption] {
        command.name == "upgrade" ? [] : command.options.filter {
            command.name != "run" || !["config", "save_config"].contains($0.name)
        }
    }
    private var basicOptions: [CLIOption] { formOptions.filter { !OptionPresentation.isAdvanced($0.name, command: command.name) } }
    private var advancedOptions: [CLIOption] { formOptions.filter { OptionPresentation.isAdvanced($0.name, command: command.name) } }
    var body: some View {
        VStack(alignment: .leading, spacing: 22) {
            ChronosCard(command.name == "upgrade" ? "Update app-managed CLI" : command.title, subtitle: guidance) {
                if command.supportsRunConfigurations {
                    ChronosActions {
                        Button("Load configuration…") { store.loadRunConfiguration(command) }
                            .disabled(store.isRunning || !store.selectedReady)
                            .accessibilityIdentifier("command.run.loadConfiguration")
                        Button("Save configuration…") { store.saveRunConfiguration(command) }
                            .disabled(store.isRunning || !store.selectedReady)
                            .accessibilityIdentifier("command.run.saveConfiguration")
                    }
                    if let notice = store.runConfigurationNotice { ChronosHelp(notice) }
                }
                VStack(alignment: .leading, spacing: 24) {
                    ForEach(basicOptions) { option in OptionField(option: option, command: command) }
                }
                if !advancedOptions.isEmpty {
                    DisclosureGroup("Additional settings", isExpanded: $advanced) {
                        VStack(alignment: .leading, spacing: 24) {
                            ForEach(advancedOptions) { option in OptionField(option: option, command: command) }
                        }
                    }
                    .font(ChronosStyle.label)
                    .disclosureGroupStyle(ChronosDisclosureStyle(identifier: "command.\(command.name).additional"))
                }
                Divider()
                ChronosActions {
                    Button(actionTitle) { store.run(command) }
                        .buttonStyle(.borderedProminent).controlSize(.large)
                        .tint(ChronosStyle.primaryButton).foregroundStyle(.white)
                        .disabled(store.isRunning || !store.selectedReady)
                        .accessibilityIdentifier("command.\(command.name).run")
                    if command.name != "upgrade" {
                        Button("Restore CLI defaults") {
                            store.drafts[command.name] = nil
                            if command.name == "run" { store.runConfigurationNotice = nil }
                        }
                            .disabled(store.isRunning)
                        Toggle("Show command", isOn: $preview).toggleStyle(.checkbox)
                    }
                }
                if preview && command.name != "upgrade" {
                    Text(commandPreview).font(ChronosStyle.code).textSelection(.enabled)
                        .accessibilityIdentifier("command.preview")
                        .fixedSize(horizontal: false, vertical: true)
                        .padding(14).frame(maxWidth: .infinity, alignment: .leading)
                        .background(ChronosStyle.inset, in: RoundedRectangle(cornerRadius: 8))
                }
            }
            if let outcome = store.outcome { CommandOutcomeView(outcome: outcome) }
        }
        .onChange(of: store.runConfigurationNotice) { _, notice in
            if command.supportsRunConfigurations, notice != nil { advanced = true }
        }
    }
    private var actionTitle: String {
        if command.name == "submit" { return store.values(for: command)["dry_run"] == "true" ? "Validate result" : "Review and send…" }
        if command.name == "upgrade" { return "Check compatible CLI" }
        return command.section == .benchmark ? "Start test" : "Run check"
    }
    private var commandPreview: String {
        do { return "mlx-chronos " + CommandBuilder.display(try CommandBuilder.arguments(command, values: store.executionValues(for: command))) }
        catch { return error.localizedDescription }
    }
    private var guidance: String {
        switch command.name {
        case "run": return "Baseline measures repeated requests; sustained uses a longer generation to observe sustained performance. Public-ready mode validates the standard protocol; it does not send a result. Leave numeric overrides blank to use the selected CLI's profile defaults."
        case "matrix": return "Run an explicit engine/model mapping with preflight, rotated order and cooldown. This local sweep records conditions; it does not prove that different model IDs use identical weights."
        case "context": return "Measure time to first token as approximate input length increases. Buckets are character-based; input tokens are recorded only when the engine reports them. Local diagnostic."
        case "concurrency": return "Measure aggregate throughput with simultaneous requests. Larger levels can exhaust memory or overwhelm a server; begin with 1,2 on a small Mac. Every measured request has a unique prompt. Local diagnostic."
        case "energy": return "Experimental local estimate of macmon-reported whole-system energy. Includes a separate no-request phase; it is not model-only energy or a calibrated wall-plug measurement. Requires macmon."
        case "doctor": return "Diagnose hardware and server setup. Adding a model performs an inference probe. Public-ready checks also inspect protocol prerequisites."
        case "validate": return "Check the engine and server. Adding a model sends a small completion request; the server may load that model if configured for automatic loading."
        case "submit": return "Validate a sealed standard benchmark for the community leaderboard. Validation-only is selected by default. Contact email and contributor attribution are optional; sending requires a separate confirmation. Local diagnostics cannot be submitted."
        case "compare": return OptionPresentation.compareGuidance
        case "history": return "List the standard benchmark results in a folder, newest first. The browser above also includes local diagnostics and matrix manifests."
        case "upgrade": return "Prepare the newest verified compatible CLI in a private app environment. External installations are preserved. Compatibility and thermal support are checked before activation."
        default: return command.help
        }
    }
}

private struct OptionField: View {
    @EnvironmentObject private var store: ChronosStore
    var option: CLIOption
    var command: CLICommand
    private var value: Binding<String> {
        Binding(get: { store.values(for: command)[option.name] ?? "" },
                set: { store.setValue($0, option: option.name, command: command) })
    }
    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            if option.kind == "boolean" {
                Toggle(OptionPresentation.title(option.name), isOn: Binding(
                    get: { value.wrappedValue == "true" }, set: { value.wrappedValue = $0 ? "true" : "false" }
                )).toggleStyle(.checkbox).font(ChronosStyle.label).accessibilityIdentifier(identifier)
            } else if !option.choices.isEmpty {
                Text(OptionPresentation.title(option.name)).font(ChronosStyle.label)
                Picker(OptionPresentation.title(option.name), selection: value) {
                    if !option.required { Text("CLI default").tag("") }
                    ForEach(option.choices, id: \.self) { choice in Text(choice).tag(choice) }
                }
                .labelsHidden().pickerStyle(.menu).controlSize(.large)
                .frame(maxWidth: .infinity, alignment: .leading)
                .accessibilityLabel(OptionPresentation.title(option.name))
                .accessibilityIdentifier(identifier)
            } else {
                HStack(alignment: .firstTextBaseline, spacing: 10) {
                    Text(OptionPresentation.title(option.name) + (option.required || (command.name == "run" && option.name == "model") ? " *" : ""))
                        .font(ChronosStyle.label)
                    Spacer()
                    if ["file", "files", "output_dir"].contains(option.name) {
                        Button("Choose…") { store.chooseFiles(option: option, command: command) }
                    }
                    if option.name == "model" { modelMenu }
                    if option.name == "engine_model" { matrixMenu }
                }
                if option.kind == "repeat" || option.multiple || option.name == "notes" {
                    TextEditor(text: value).font(option.name == "notes" ? ChronosStyle.body : ChronosStyle.code)
                        .accessibilityIdentifier(identifier)
                        .scrollContentBackground(.hidden)
                        .padding(8)
                        .frame(height: option.name == "notes" ? 90 : 115)
                        .background(ChronosStyle.inset, in: RoundedRectangle(cornerRadius: 8))
                        .overlay { RoundedRectangle(cornerRadius: 8).strokeBorder(ChronosStyle.rule, lineWidth: 1).allowsHitTesting(false) }
                } else {
                    TextField(placeholder, text: value).textFieldStyle(.roundedBorder)
                        .font(ChronosStyle.body).controlSize(.large)
                        .accessibilityLabel(OptionPresentation.title(option.name))
                        .accessibilityIdentifier(identifier)
                }
            }
            ChronosHelp(option.help)
            if option.name == "output_dir" && command.section == .benchmark {
                ChronosHelp("If blank, use the app's default test folder (with a subfolder for local diagnostics).")
            }
            if option.kind == "repeat" || option.multiple {
                ChronosHelp("One entry per line. Order is preserved.")
            }
        }.disabled(store.isRunning)
    }
    private var identifier: String { "option.\(command.name).\(option.name)" }
    private var placeholder: String {
        option.defaultValue.map { "CLI default: \($0)" } ?? (option.required ? "Required" : "Optional — leave blank")
    }
    @ViewBuilder private var modelMenu: some View {
        let engine = store.values(for: command)["engine"] ?? ""
        if let models = store.engineStatuses.first(where: { $0.name == engine })?.models, !models.isEmpty {
            Menu("Use detected model") {
                ForEach(models, id: \.self) { model in Button(model) { value.wrappedValue = model } }
            }
        }
    }
    private var matrixMenu: some View {
        Menu("Add detected engine/model") {
            ForEach(store.engineStatuses.filter { !$0.models.isEmpty }) { engine in
                Menu(engine.displayName) {
                    ForEach(engine.models, id: \.self) { model in
                        Button(model) {
                            let prefix = value.wrappedValue.trimmingCharacters(in: .whitespacesAndNewlines)
                            value.wrappedValue = (prefix.isEmpty ? "" : prefix + "\n") + engine.name + "=" + model
                        }
                    }
                }
            }
        }
    }
}
