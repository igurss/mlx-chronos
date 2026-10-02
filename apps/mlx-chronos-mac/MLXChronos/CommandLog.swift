import Combine
import Foundation

@MainActor
final class CommandLog: ObservableObject {
    @Published private(set) var text = ""
    private var pending = ""
    private var flushTask: Task<Void, Never>?
    private let limit = 120_000
    func append(_ chunk: String) {
        pending += chunk
        if pending.count > limit { pending = String(pending.suffix(limit)) }
        if flushTask == nil {
            flushTask = Task {
                try? await Task.sleep(for: .milliseconds(100))
                flush()
            }
        }
    }
    func flush() {
        flushTask?.cancel(); flushTask = nil
        guard !pending.isEmpty else { return }
        text += pending
        pending = ""
        if text.count > limit { text = String(text.suffix(limit)) }
    }
    func clear() {
        flushTask?.cancel(); flushTask = nil; pending = ""; text = ""
    }
}
