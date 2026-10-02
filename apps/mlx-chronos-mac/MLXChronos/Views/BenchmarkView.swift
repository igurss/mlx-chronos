import SwiftUI

struct BenchmarkView: View {
    @EnvironmentObject private var store: ChronosStore
    @State private var selectedCommand = "run"
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 22) {
                let commands = store.commands.filter { $0.section == .benchmark }
                ChronosCard("Choose a test", subtitle: "Select the test type, then configure its engine and exact model ID below. Measurements and validation use the selected Python CLI.") {
                    if commands.isEmpty {
                        ChronosHelp("Prepare or select mlx-chronos in Environment to see the commands provided by that installation.")
                    } else {
                        Picker("Test", selection: $selectedCommand) {
                            ForEach(commands) { command in Text(command.title).tag(command.name) }
                        }.font(ChronosStyle.label).accessibilityIdentifier("tests.command")
                    }
                }
                if !commands.isEmpty {
                    if let command = commands.first(where: { $0.name == selectedCommand }) {
                        CommandForm(command: command)
                    }
                }
            }
            .frame(maxWidth: 1100, alignment: .leading)
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(24)
        }.accessibilityIdentifier("tests.form")
    }
}
