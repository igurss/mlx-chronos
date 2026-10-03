import CoreFoundation
import Foundation

struct ResultListing {
    var results: [ResultSummary]
    var total: Int
    var skippedDirectories: Int
    var notice: String? {
        var messages: [String] = []
        if total > results.count { messages.append("Showing the newest \(results.count) of \(total) JSON files.") }
        if skippedDirectories > 0 { messages.append("Could not scan \(skippedDirectories) subfolders.") }
        return messages.isEmpty ? nil : messages.joined(separator: " ")
    }
}

fileprivate struct ResultFingerprint: Equatable {
    var size: Int?
    var modified: Date?
}
fileprivate struct ResultEntry {
    var summary: ResultSummary
    var fingerprint: ResultFingerprint
}

// This cache contains display summaries only. CLI validation always rereads
// the complete file and verifies its schema/seal independently.
final class ResultSummaryCache: @unchecked Sendable {
    private let lock = NSLock()
    private var entries: [URL: ResultEntry] = [:]
    fileprivate func find(_ url: URL, _ fingerprint: ResultFingerprint) -> ResultEntry? {
        lock.lock(); defer { lock.unlock() }
        guard let entry = entries[url], entry.fingerprint == fingerprint else { return nil }
        return entry
    }
    fileprivate func replace(_ entries: [ResultEntry]) {
        lock.lock(); defer { lock.unlock() }
        self.entries = Dictionary(uniqueKeysWithValues: entries.map { ($0.summary.url, $0) })
    }
}

enum ResultRepository {
    static let fileLimit = 10 * 1024 * 1024
    static let displayLimit = 5000
    static func load(_ root: URL) -> [ResultSummary] {
        (try? scan(root).results) ?? []
    }
    static func scan(_ root: URL, limit: Int = displayLimit,
                     cache: ResultSummaryCache? = nil,
                     checkCancellation: () throws -> Void = {}) throws -> ResultListing {
        precondition(limit > 0)
        let fm = FileManager.default
        try checkCancellation()
        let children = try fm.contentsOfDirectory(at: root, includingPropertiesForKeys: [.isDirectoryKey], options: [.skipsHiddenFiles])
        let directories = [root] + children.filter {
            (try? $0.resourceValues(forKeys: [.isDirectoryKey]).isDirectory) == true
        }.sorted { $0.path < $1.path }
        let precise = ISO8601DateFormatter()
        precise.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        let ordinary = ISO8601DateFormatter()
        let parseDate: (String) -> Date? = { precise.date(from: $0) ?? ordinary.date(from: $0) }
        // A heap with the oldest retained item at the root bounds summaries to
        // O(limit), while inspecting every candidate's actual recorded date.
        var heap: [ResultEntry] = []
        var total = 0, skipped = 0
        for directory in directories {
            try checkCancellation()
            guard let enumerator = fm.enumerator(at: directory,
                includingPropertiesForKeys: [.fileSizeKey, .contentModificationDateKey, .isDirectoryKey],
                options: [.skipsHiddenFiles, .skipsSubdirectoryDescendants],
                errorHandler: { _, _ in skipped += 1; return false }) else { skipped += 1; continue }
            for case let url as URL in enumerator {
                try checkCancellation()
                guard url.pathExtension.lowercased() == "json",
                      (try? url.resourceValues(forKeys: [.isDirectoryKey]).isDirectory) != true else { continue }
                total += 1
                let values = try? url.resourceValues(forKeys: [.fileSizeKey, .contentModificationDateKey])
                let fingerprint = ResultFingerprint(size: values?.fileSize, modified: values?.contentModificationDate)
                let entry = cache?.find(url, fingerprint) ?? ResultEntry(
                    summary: summary(url, parseDate: parseDate), fingerprint: fingerprint)
                if heap.count < limit {
                    heap.append(entry)
                    var child = heap.count - 1
                    while child > 0 {
                        let parent = (child - 1) / 2
                        if !newer(heap[parent], heap[child]) { break }
                        heap.swapAt(parent, child); child = parent
                    }
                } else if newer(entry, heap[0]) {
                    heap[0] = entry
                    var parent = 0
                    while parent * 2 + 1 < heap.count {
                        var child = parent * 2 + 1
                        if child + 1 < heap.count && newer(heap[child], heap[child + 1]) { child += 1 }
                        if !newer(heap[parent], heap[child]) { break }
                        heap.swapAt(parent, child); parent = child
                    }
                }
            }
        }
        try checkCancellation()
        cache?.replace(heap)
        return ResultListing(results: heap.sorted(by: newer).map(\.summary), total: total, skippedDirectories: skipped)
    }
    private static func newer(_ left: ResultEntry, _ right: ResultEntry) -> Bool {
        if left.summary.recordedAt != right.summary.recordedAt { return left.summary.recordedAt > right.summary.recordedAt }
        return left.summary.url.path < right.summary.url.path
    }

    static func read(_ url: URL) throws -> Data {
        let values = try url.resourceValues(forKeys: [.fileSizeKey, .isRegularFileKey])
        guard values.isRegularFile == true, (values.fileSize ?? Int.max) <= fileLimit else {
            throw CommandError.invalid("This file is not a regular JSON file smaller than 10 MB.")
        }
        let handle = try FileHandle(forReadingFrom: url)
        defer { try? handle.close() }
        let data = try handle.read(upToCount: fileLimit + 1) ?? Data()
        guard data.count <= fileLimit else { throw CommandError.invalid("The result file grew beyond the 10 MB viewing limit.") }
        return data
    }
    static func preview(_ url: URL) -> String {
        do {
            let json = try JSONSerialization.jsonObject(with: read(url))
            let data = try JSONSerialization.data(withJSONObject: json, options: [.prettyPrinted, .sortedKeys, .withoutEscapingSlashes])
            return String(decoding: data, as: UTF8.self)
        } catch { return "Could not read this result: \(error.localizedDescription)" }
    }
    private static func summary(_ url: URL, parseDate: (String) -> Date?) -> ResultSummary {
        let raw = (try? read(url)).flatMap { try? JSONSerialization.jsonObject(with: $0) as? [String: Any] } ?? [:]
        let engine = raw["engine"] as? [String: Any] ?? [:]
        let model = raw["model"] as? [String: Any] ?? [:]
        let meta = raw["meta"] as? [String: Any] ?? [:]
        let metrics = raw["metrics"] as? [String: Any] ?? [:]
        let throughput = (metrics["request_tokens_per_second"] ?? metrics["tokens_per_second"]) as? [String: Any]
        let cold = metrics["ttft_cold"] as? [String: Any]
        let cached = metrics["ttft_cached"] as? [String: Any]
        let kind = resultKind(raw, engine: engine, model: model, metrics: metrics)
        let timestamp = (meta["timestamp"] ?? raw["timestamp"] ?? raw["created_at"]) as? String
        let recordedAt = timestamp.flatMap(parseDate)
            ?? (try? url.resourceValues(forKeys: [.contentModificationDateKey]).contentModificationDate)
            ?? .distantPast
        return ResultSummary(
            url: url, kind: kind,
            engine: engine["name"] as? String ?? "—", model: model["name"] as? String ?? "—",
            timestamp: timestamp ?? url.lastPathComponent, recordedAt: recordedAt,
            throughput: number(throughput?["mean"]), coldTTFT: number(cold?["mean"]), cachedTTFT: number(cached?["mean"]),
            systemRAMGrowth: number(metrics["system_ram_delta_gb"]), swapGrowth: number(metrics["swap_growth_gb"]),
            profile: meta["benchmark_profile"] as? String ?? kind
        )
    }
    private static func resultKind(_ raw: [String: Any], engine: [String: Any],
                                   model: [String: Any], metrics: [String: Any]) -> String {
        if raw.isEmpty { return "unreadable" }
        if let kind = raw["kind"] as? String { return kind }
        // CLI 0.5 concurrency reports have a version/protocol marker, not `kind`.
        // This is display classification, never schema or eligibility validation.
        if let version = raw["concurrency_profile_version"] as? String, !version.isEmpty,
           let protocolInfo = raw["protocol"] as? [String: Any],
           protocolInfo["name"] as? String == "cache_minimized_concurrency",
           protocolInfo["version"] as? String == version,
           let levels = raw["levels"] as? [[String: Any]], !levels.isEmpty,
           let engineName = engine["name"] as? String, !engineName.isEmpty,
           let modelName = model["name"] as? String, !modelName.isEmpty {
            return "local_concurrency_diagnostic"
        }
        return !engine.isEmpty && !model.isEmpty && !metrics.isEmpty ? "benchmark" : "unknown"
    }
    private static func number(_ value: Any?) -> Double? {
        guard let value = value as? NSNumber, CFGetTypeID(value) != CFBooleanGetTypeID(), value.doubleValue.isFinite else { return nil }
        return value.doubleValue
    }
}
