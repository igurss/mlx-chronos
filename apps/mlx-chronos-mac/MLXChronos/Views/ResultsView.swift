import SwiftUI

struct ResultsView: View {
    @EnvironmentObject private var store: ChronosStore
    @State private var selection = Set<URL>()
    @State private var action = "history"
    @State private var reference: URL?
    @State private var preview: String?
    @State private var previewTitle = ""
    @State private var previewRevision = UUID()
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 22) {
                ChronosCard("Saved results", subtitle: store.resultsDirectory.path) {
                    ChronosActions {
                        Button("Choose default folder…") { store.chooseOutputDirectory() }.disabled(store.isRunning)
                        Button("Refresh") { store.loadResults() }
                        Button("Show in Finder") { store.reveal(store.resultsDirectory) }
                    }
                    if store.resultsDirectory.path != store.outputDirectory.path {
                        VStack(alignment: .leading, spacing: 8) {
                            ChronosHelp("Default test folder: " + store.outputDirectory.path)
                            Button("Show default folder") { store.showDefaultResults() }
                        }
                    }
                    Table(store.results, selection: $selection) {
                        TableColumn("Model") { result in
                            Text(result.model).font(ChronosStyle.label).lineLimit(1).help(result.url.lastPathComponent)
                        }
                        TableColumn("Engine", value: \.engine).width(min: 70, ideal: 85)
                        TableColumn("Profile / diagnostic", value: \.displayProfile).width(min: 90, ideal: 140)
                        TableColumn("tok/s") { result in
                            Text(format(result.throughput)).monospacedDigit().font(ChronosStyle.label)
                        }.width(70)
                        TableColumn("Date", value: \.timestamp).width(min: 125, ideal: 165)
                    }
                    .font(ChronosStyle.help)
                    .frame(height: 220)
                    .accessibilityIdentifier("results.table")
                    .clipShape(RoundedRectangle(cornerRadius: 8))
                    .overlay { RoundedRectangle(cornerRadius: 8).strokeBorder(ChronosStyle.rule, lineWidth: 1).allowsHitTesting(false) }
                    .overlay {
                        if store.results.isEmpty {
                            VStack(spacing: 8) {
                                Text("No results in this folder").font(ChronosStyle.label)
                                ChronosHelp("Run a test or choose a folder containing saved JSON results.")
                            }.padding(20).allowsHitTesting(false)
                        }
                    }
                    ChronosActions {
                        Button("Inspect all recorded data") { inspectSelected() }.disabled(selection.count != 1)
                        Button("Compare selected") { useForComparison() }
                            .disabled(store.isRunning || selectedBenchmarks.count < 2)
                        Button("Use selected for sharing") { useForSharing() }
                            .disabled(store.isRunning || selectedBenchmarks.count != 1)
                    }
                    if selectedBenchmarks.count > 1 {
                        Picker("Reference", selection: $reference) {
                            Text("Choose reference").tag(nil as URL?)
                            ForEach(selectedBenchmarks) { result in Text(result.url.lastPathComponent).tag(result.url as URL?) }
                        }.accessibilityIdentifier("results.reference")
                    }
                    ChronosHelp("Browsing does not validate a file's seal or public eligibility. Compare and validation-only sharing perform the CLI checks.")
                }
                let commands = store.commands.filter { $0.section == .results }
                ChronosCard("Work with results") {
                    if commands.isEmpty {
                        ChronosHelp("Select a working mlx-chronos installation to compare, validate or share results.")
                    } else {
                        Picker("Result action", selection: $action) {
                            ForEach(commands) { command in Text(command.title).tag(command.name) }
                        }.font(ChronosStyle.label).accessibilityIdentifier("results.command")
                    }
                }
                if let command = commands.first(where: { $0.name == action }) { CommandForm(command: command) }
            }
            .frame(maxWidth: 1100, alignment: .leading)
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(24)
        }
        .accessibilityIdentifier("results.form")
        .onChange(of: selection) { _, selected in
            if !selected.contains(reference ?? URL(fileURLWithPath: "/")) { reference = nil }
        }
        .onChange(of: store.resultsDirectory) { _, _ in
            selection = []; reference = nil; closePreview()
        }
        .sheet(isPresented: Binding(get: { preview != nil }, set: { if !$0 { closePreview() } })) {
            VStack(alignment: .leading, spacing: 12) {
                HStack { Text(previewTitle).font(ChronosStyle.sectionTitle); Spacer(); Button("Done") { closePreview() } }
                ConsoleTextView(text: preview ?? "").frame(minWidth: 800, minHeight: 550)
                    .clipShape(RoundedRectangle(cornerRadius: 8))
                    .overlay { RoundedRectangle(cornerRadius: 8).strokeBorder(ChronosStyle.rule, lineWidth: 1).allowsHitTesting(false) }
            }.padding(24).background(ChronosStyle.surface)
        }
    }
    private var selectedBenchmarks: [ResultSummary] {
        store.results.filter { selection.contains($0.url) && $0.isBenchmark }
    }
    private func format(_ value: Double?) -> String { value.map { String(format: "%.2f", $0) } ?? "—" }
    private func useForComparison() {
        guard let command = store.commands.first(where: { $0.name == "compare" }) else { return }
        let selected = selectedBenchmarks
        let baseline = reference ?? selected.first?.url
        let ordered = selected.sorted { lhs, rhs in
            if lhs.url == rhs.url { return false }
            if lhs.url == baseline { return true }
            if rhs.url == baseline { return false }
            return lhs.timestamp > rhs.timestamp
        }
        store.setValue(ordered.map(\.url.path).joined(separator: "\n"), option: "files", command: command)
        action = "compare"
    }
    private func useForSharing() {
        guard let command = store.commands.first(where: { $0.name == "submit" }),
              let result = selectedBenchmarks.first else { return }
        store.setValue(result.url.path, option: "file", command: command)
        store.setValue("true", option: "dry_run", command: command)
        action = "submit"
    }
    private func inspectSelected() {
        guard let file = selection.first else { return }
        let revision = UUID()
        previewRevision = revision
        previewTitle = file.lastPathComponent
        preview = "Reading…"
        Task {
            let text = await Task.detached(priority: .utility) { ResultRepository.preview(file) }.value
            if preview != nil && previewRevision == revision { preview = text }
        }
    }
    private func closePreview() { previewRevision = UUID(); preview = nil }
}
