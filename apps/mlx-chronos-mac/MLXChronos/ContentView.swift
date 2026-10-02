import AppKit
import SwiftUI

struct ContentView: View {
    @EnvironmentObject private var store: ChronosStore
    @Environment(\.colorScheme) private var colorScheme
    @State private var selection: AppSection = .setup
    @State private var columnVisibility: NavigationSplitViewVisibility = .all
    var body: some View {
        NavigationSplitView(columnVisibility: $columnVisibility) {
            VStack(alignment: .leading, spacing: 0) {
                HStack(spacing: 10) {
                    Image("ChronosLogo")
                        .resizable().interpolation(.high).frame(width: 38, height: 38)
                        .accessibilityHidden(true)
                    VStack(alignment: .leading, spacing: 3) {
                        Text("MLX Chronos").font(.system(size: 17, weight: .semibold))
                            .accessibilityIdentifier("layout.brandTitle")
                        Text("LOCAL BENCHMARKS").font(.system(size: 9, weight: .semibold))
                            .tracking(1.2).foregroundStyle(ChronosStyle.secondary)
                    }
                }
                .padding(.horizontal, 18).padding(.top, 36).padding(.bottom, 20)
                .frame(height: ChronosStyle.headerHeight, alignment: .bottomLeading)
                List(AppSection.allCases, selection: $selection) { section in
                    VStack(alignment: .leading, spacing: 4) {
                        Text(section.title).font(.system(size: 14, weight: .medium))
                        Text(sectionDescription(section)).font(.system(size: 11))
                            .foregroundStyle(.secondary)
                    }
                    .padding(.vertical, 7)
                    .tag(section)
                }
                .listStyle(.sidebar)
                .contentMargins(.top, 0, for: .scrollContent)
                .scrollContentBackground(.hidden)
                .accessibilityIdentifier("navigation.sections")
                VStack(alignment: .leading, spacing: 5) {
                    Text("Measured by mlx-chronos").font(ChronosStyle.help)
                    Text("Your models. Your Mac.").font(.system(size: 11))
                }
                .foregroundStyle(ChronosStyle.secondary)
                .padding(.horizontal, 20).padding(.bottom, 20)
            }
            .background(ChronosStyle.inset)
            .ignoresSafeArea(.container, edges: .top)
            .toolbar(removing: .sidebarToggle)
            .navigationSplitViewColumnWidth(min: 205, ideal: 220, max: 250)
        } detail: {
            VStack(spacing: 0) {
                HStack(alignment: .center, spacing: 20) {
                    VStack(alignment: .leading, spacing: 8) {
                        Text(selection.title).font(ChronosStyle.pageTitle)
                            .tracking(-0.5).accessibilityAddTraits(.isHeader)
                            .offset(y: ChronosStyle.headerTitleLowering)
                            .accessibilityIdentifier("layout.pageTitle")
                        Text(runtimeLabel).font(ChronosStyle.help)
                            .foregroundStyle(ChronosStyle.secondary).lineLimit(2)
                            .help(runtimeLabel).accessibilityIdentifier("layout.runtimeLabel")
                    }
                    Spacer()
                    if let operation = store.operation {
                        HStack(spacing: 10) {
                            ProgressView().controlSize(.small)
                            Text(store.isStopping ? "Stopping…" : operation)
                                .font(ChronosStyle.help).foregroundStyle(ChronosStyle.secondary)
                            Button("Stop") { store.stop() }.disabled(store.isStopping)
                                .accessibilityIdentifier("operation.stop")
                        }
                        .padding(10).background(ChronosStyle.inset, in: RoundedRectangle(cornerRadius: 10))
                    }
                }
                .padding(.horizontal, 28)
                // Remove space below the text without moving it toward the
                // traffic lights when the sidebar is hidden.
                .padding(.top, ChronosStyle.headerContentTop)
                .frame(height: ChronosStyle.headerHeight, alignment: .top)
                .background(ChronosStyle.surface)
                .accessibilityElement(children: .contain)
                .accessibilityIdentifier("layout.pageHeader")
                Rectangle().fill(ChronosStyle.rule).frame(height: 1)
                if let error = store.lastError {
                    HStack(alignment: .top, spacing: 16) {
                        VStack(alignment: .leading, spacing: 6) {
                            Text("Action needs attention").font(ChronosStyle.label)
                            Text(error).font(ChronosStyle.body).textSelection(.enabled)
                                .accessibilityIdentifier("operation.error")
                        }
                        Spacer()
                        Button("Dismiss") { store.lastError = nil }
                    }
                    .padding(16).background(ChronosStyle.accent.opacity(0.10), in: RoundedRectangle(cornerRadius: 10))
                    .overlay(alignment: .leading) {
                        RoundedRectangle(cornerRadius: 2).fill(ChronosStyle.accent).frame(width: 3)
                            .allowsHitTesting(false)
                    }
                    .padding(.horizontal, 24).padding(.top, 16)
                }
                switch selection {
                case .setup: SetupView()
                case .benchmark: BenchmarkView()
                case .results: ResultsView()
                case .logs: LogsView()
                }
            }
            .background(ChronosStyle.canvas)
            .ignoresSafeArea(.container, edges: .top)
        }
        .focusedSceneValue(\.chronosSidebarVisibility, $columnVisibility)
        .background(ChronosWindowConfiguration().frame(width: 0, height: 0))
        .font(ChronosStyle.body)
        .tint(ChronosStyle.accent)
        .frame(minWidth: 960, minHeight: 680)
        .task { store.scanOnFirstAppearance() }
        .onChange(of: colorScheme, initial: true) { _, scheme in
            updateLegacyAppIcon(for: scheme)
        }
        .alert(item: $store.pendingAction) { action in
            Alert(title: Text(action.title), message: Text(action.message),
                  primaryButton: action.destructive
                    ? .destructive(Text(action.button), action: action.perform)
                    : .default(Text(action.button), action: action.perform),
                  secondaryButton: .cancel())
        }
    }
    private func sectionDescription(_ section: AppSection) -> String {
        switch section {
        case .setup: "Runtime, Mac & engines"
        case .benchmark: "Configure & measure"
        case .results: "Inspect, compare & share"
        case .logs: "Live command output"
        }
    }

    private func updateLegacyAppIcon(for scheme: ColorScheme) {
        // Newer macOS versions select the native Icon Composer variants themselves.
        guard #unavailable(macOS 26.0) else { return }
        let name = scheme == .dark ? "ApplicationIconDark" : "ApplicationIconLight"
        if let image = NSImage(named: name) {
            NSApp.applicationIconImage = image
        }
    }

    private var runtimeLabel: String {
        guard let runtime = store.selectedRuntime else { return "Select an installation in Environment" }
        return runtime.title + (runtime.probe.map { " · Python \($0.pythonVersion)" } ?? " · setup required")
    }
}

struct InfoLine: View {
    var title: String
    var value: String
    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 18) {
            Text(title).font(ChronosStyle.label).foregroundStyle(ChronosStyle.secondary)
                .frame(width: 190, alignment: .leading)
            Text(value).font(ChronosStyle.body).textSelection(.enabled)
                .fixedSize(horizontal: false, vertical: true)
                .frame(maxWidth: .infinity, alignment: .leading)
        }
    }
}

struct CommandOutcomeView: View {
    var outcome: CommandOutcome
    var body: some View {
        ChronosCard("Command result") {
            HStack {
                Text(outcome.succeeded ? "\(outcome.title) completed" : "\(outcome.title) failed")
                    .font(ChronosStyle.label)
                    .accessibilityIdentifier("operation.outcome")
                Spacer()
                ChronosStatus(text: outcome.succeeded ? "Completed" : "Failed", emphasized: outcome.succeeded)
            }
            ConsoleTextView(text: outcome.output)
                .frame(minHeight: 180, maxHeight: 320)
                .clipShape(RoundedRectangle(cornerRadius: 8))
                .overlay { RoundedRectangle(cornerRadius: 8).strokeBorder(ChronosStyle.rule, lineWidth: 1).allowsHitTesting(false) }
        }
    }
}
