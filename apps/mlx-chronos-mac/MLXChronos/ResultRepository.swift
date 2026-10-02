import CoreFoundation
import Foundation

enum ResultRepository {
    static let fileLimit = 10 * 1024 * 1024
    static func load(_ root: URL) -> [ResultSummary] {
        let fm = FileManager.default
        var directories = [root]
        if let children = try? fm.contentsOfDirectory(at: root, includingPropertiesForKeys: [.isDirectoryKey], options: [.skipsHiddenFiles]) {
            directories += children.filter { (try? $0.resourceValues(forKeys: [.isDirectoryKey]).isDirectory) == true }.prefix(30)
        }
        let files = directories.flatMap { (try? fm.contentsOfDirectory(at: $0, includingPropertiesForKeys: [.fileSizeKey], options: [.skipsHiddenFiles])) ?? [] }
            .filter { $0.pathExtension.lowercased() == "json" }.prefix(5000)
        // Local formatters avoid shared mutable state between background reads.
        let precise = ISO8601DateFormatter()
        precise.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        let ordinary = ISO8601DateFormatter()
        let parseDate: (String) -> Date? = { precise.date(from: $0) ?? ordinary.date(from: $0) }
        return files.map { summary($0, parseDate: parseDate) }.sorted {
            if $0.recordedAt != $1.recordedAt { return $0.recordedAt > $1.recordedAt }
            return $0.url.path < $1.url.path
        }
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
