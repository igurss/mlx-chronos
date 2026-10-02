import SwiftUI

@main
struct MLXChronosApp: App {
    @StateObject private var store = ChronosStore()
    @NSApplicationDelegateAdaptor(ChronosApplicationDelegate.self) private var delegate

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(store)
                .onAppear { delegate.store = store }
        }
        .windowStyle(.hiddenTitleBar)
        .defaultSize(width: 1160, height: 800)
        .commands {
            CommandGroup(replacing: .newItem) { }
            ChronosSidebarCommands()
        }
    }

}

private struct ChronosSidebarVisibilityKey: FocusedValueKey {
    typealias Value = Binding<NavigationSplitViewVisibility>
}

extension FocusedValues {
    var chronosSidebarVisibility: Binding<NavigationSplitViewVisibility>? {
        get { self[ChronosSidebarVisibilityKey.self] }
        set { self[ChronosSidebarVisibilityKey.self] = newValue }
    }
}

/// Operate on the focused split view directly. Removing its toolbar item must
/// not leave a responder-chain sidebar action disconnected from that view.
private struct ChronosSidebarCommands: Commands {
    @FocusedBinding(\.chronosSidebarVisibility) private var visibility
    var body: some Commands {
        CommandGroup(replacing: .sidebar) {
            Button(visibility == .detailOnly ? "Show Sidebar" : "Hide Sidebar") {
                guard let visibility else { return }
                self.visibility = visibility == .detailOnly ? .all : .detailOnly
            }
            .keyboardShortcut("s", modifiers: [.control, .command])
            .disabled(visibility == nil)
        }
    }
}

/// Retain background window dragging on every supported macOS version,
/// including macOS 14, without adding a replacement toolbar or custom controls.
struct ChronosWindowConfiguration: NSViewRepresentable {
    func makeNSView(context: Context) -> NSView { WindowAnchor() }
    func updateNSView(_ view: NSView, context: Context) {
        view.window?.isMovableByWindowBackground = true
    }
    private final class WindowAnchor: NSView {
        override func viewDidMoveToWindow() {
            super.viewDidMoveToWindow()
            window?.isMovableByWindowBackground = true
        }
    }
}

@MainActor
final class ChronosApplicationDelegate: NSObject, NSApplicationDelegate {
    weak var store: ChronosStore?
    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        guard let store, store.isRunning else { return .terminateNow }
        store.stop()
        Task {
            while store.isRunning { try? await Task.sleep(for: .milliseconds(100)) }
            sender.reply(toApplicationShouldTerminate: true)
        }
        return .terminateLater
    }
}
