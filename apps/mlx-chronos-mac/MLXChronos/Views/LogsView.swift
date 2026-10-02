import AppKit
import SwiftUI

struct LogsView: View {
    @EnvironmentObject private var store: ChronosStore
    var body: some View {
        ActivityPanel(log: store.log, isRunning: store.isRunning)
    }
}

private struct ActivityPanel: View {
    @ObservedObject var log: CommandLog
    var isRunning: Bool
    var body: some View {
        GeometryReader { geometry in
            ChronosCard("Command output") {
                HStack {
                    ChronosStatus(text: isRunning ? "Live output" : "Idle", emphasized: isRunning)
                    Spacer()
                    Button("Copy") {
                        NSPasteboard.general.clearContents()
                        NSPasteboard.general.setString(log.text, forType: .string)
                    }
                    Button("Clear") { log.clear() }.disabled(isRunning)
                }
                ConsoleTextView(text: log.text)
                    // A native text view must not determine the window's
                    // ideal height from its potentially very long log.
                    // Reserve room for the card heading, actions and help.
                    .frame(height: max(120, geometry.size.height - 240))
                    .clipShape(RoundedRectangle(cornerRadius: 8))
                    .overlay { RoundedRectangle(cornerRadius: 8).strokeBorder(ChronosStyle.rule, lineWidth: 1).allowsHitTesting(false) }
                ChronosHelp("The view keeps the latest 120,000 characters. The CLI saves full benchmark data in the result files.")
            }.padding(24)
        }
    }
}

/// Native text storage appends output without relaying out the entire SwiftUI tree.
struct ConsoleTextView: NSViewRepresentable {
    var text: String
    func makeNSView(context: Context) -> NSScrollView {
        let scroll = NSScrollView()
        scroll.hasVerticalScroller = true
        scroll.hasHorizontalScroller = false
        scroll.borderType = .noBorder
        scroll.drawsBackground = true
        scroll.backgroundColor = ChronosStyle.consoleBackground
        let view = NSTextView()
        view.isEditable = false
        view.isSelectable = true
        view.isRichText = false
        view.font = .monospacedSystemFont(ofSize: 12, weight: .regular)
        view.textColor = .textColor
        view.backgroundColor = ChronosStyle.consoleBackground
        view.textContainerInset = NSSize(width: 14, height: 14)
        view.autoresizingMask = [.width]
        view.isVerticallyResizable = true
        view.isHorizontallyResizable = false
        view.textContainer?.widthTracksTextView = true
        scroll.documentView = view
        return scroll
    }
    func updateNSView(_ scroll: NSScrollView, context: Context) {
        guard let view = scroll.documentView as? NSTextView, view.string != text else { return }
        let atBottom = scroll.contentView.bounds.maxY >= view.bounds.maxY - 24
        let old = view.string
        if text.hasPrefix(old) {
            let tail = String(text.dropFirst(old.count))
            view.textStorage?.append(NSAttributedString(string: tail, attributes: [
                .font: NSFont.monospacedSystemFont(ofSize: 12, weight: .regular),
                .foregroundColor: NSColor.textColor
            ]))
        } else { view.string = text }
        if atBottom { view.scrollToEndOfDocument(nil) }
    }
}
