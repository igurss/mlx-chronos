import CoreFoundation
import Foundation

enum TrialMetric: String, CaseIterable, Identifiable {
    case cold, cached, request, decode
    var id: String { rawValue }
    var title: String {
        switch self {
        case .cold: return "Cold"
        case .cached: return "Cached"
        case .request: return "Request"
        case .decode: return "Decode"
        }
    }
    var unit: String { isTTFT ? "ms" : "tok/s" }
    var isTTFT: Bool { self == .cold || self == .cached }
    var rawKey: String {
        switch self {
        case .cold: return "ttft_cold_raw"
        case .cached: return "ttft_cached_raw"
        case .request: return "tokens_per_second_raw"
        case .decode: return "decode_tokens_per_second_raw"
        }
    }
    var summaryKey: String {
        switch self {
        case .cold: return "ttft_cold"
        case .cached: return "ttft_cached"
        case .request: return "request_tokens_per_second"
        case .decode: return "decode_tokens_per_second"
        }
    }
}

struct RecordedTrialSeries: Identifiable, Equatable {
    var metric: TrialMetric
    var values: [Double]
    var recordedMean: Double?
    var id: TrialMetric { metric }
}

struct RecordedBenchmarkWarning: Identifiable, Equatable {
    var id: String
    var title: String
    var explanation: String
}

/// A bounded display reader, not a replacement for the CLI's schema/seal checks.
/// Keep trial order and saved means; never synthesize observations or statistics.
struct BenchmarkTrialData: Equatable {
    static let displayTrialLimit = 1_000
    var model: String
    var engine: String
    var conditions: String
    var protocolLabel: String
    var count: Int
    var series: [RecordedTrialSeries]
    var warnings: [RecordedBenchmarkWarning]

    static func load(_ url: URL) throws -> Self { try parse(ResultRepository.read(url)) }

    static func parse(_ data: Data) throws -> Self {
        guard let raw = try JSONSerialization.jsonObject(with: data) as? [String: Any],
              raw["kind"] == nil || raw["kind"] as? String == "benchmark",
              raw["concurrency_profile_version"] == nil,
              let engine = raw["engine"] as? [String: Any],
              let model = raw["model"] as? [String: Any],
              let metrics = raw["metrics"] as? [String: Any] else {
            throw CommandError.invalid("This file is not a standard benchmark. Inspect its recorded data instead.")
        }
        guard let trials = raw["trials"] as? [String: Any],
              let countValue = number(trials["count"]), countValue >= 1,
              countValue <= Double(displayTrialLimit), countValue.rounded() == countValue else {
            throw CommandError.invalid("Trial charts need a recorded trial count between 1 and \(displayTrialLimit). Inspect this file for its available data.")
        }
        let count = Int(countValue)
        var series: [RecordedTrialSeries] = []
        for metric in TrialMetric.allCases {
            guard let rawValues = trials[metric.rawKey], !(rawValues is NSNull) else { continue }
            guard let values = rawValues as? [Any], values.count == count else {
                throw CommandError.invalid("The recorded \(metric.title.lowercased()) samples do not match the trial count. Inspect the file before using its charts.")
            }
            let samples = try values.map { try displayValue($0, metric: metric) }
            let summary = (metrics[metric.summaryKey]
                ?? (metric == .request ? metrics["tokens_per_second"] : nil)) as? [String: Any]
            let mean: Double?
            if let value = summary?["mean"], !(value is NSNull) {
                mean = try displayValue(value, metric: metric)
            } else { mean = nil }
            series.append(RecordedTrialSeries(metric: metric, values: samples, recordedMean: mean))
        }
        guard !series.isEmpty else {
            throw CommandError.invalid("No individual trial samples were saved in this file. Inspect its recorded summaries instead.")
        }
        let meta = raw["meta"] as? [String: Any] ?? [:]
        let hardware = raw["hardware"] as? [String: Any] ?? [:]
        let benchmarkProtocol = meta["benchmark_protocol"] as? [String: Any] ?? [:]
        var conditions = [hardware["chip"] as? String]
        if let memory = number(hardware["memory_gb"]), memory > 0 {
            conditions.append(String(format: "%g GB RAM", memory))
        }
        conditions.append(model["quantization"] as? String)
        conditions.append(meta["benchmark_profile"] as? String)
        let protocolLabel = (benchmarkProtocol["version"] as? String).map {
            "\(benchmarkProtocol["name"] as? String ?? "Protocol") \($0)"
        } ?? "Protocol not recorded"
        let engineLabel = [engine["name"] as? String, engine["version"] as? String]
            .compactMap { $0 }.filter { !$0.isEmpty }.joined(separator: " ")
        return Self(model: model["name"] as? String ?? "Unknown model", engine: engineLabel,
            conditions: conditions.compactMap { $0 }.filter { !$0.isEmpty }.joined(separator: " · "),
            protocolLabel: protocolLabel, count: count, series: series, warnings: recordedWarnings(meta))
    }

    private static func number(_ value: Any?) -> Double? {
        guard let value = value as? NSNumber, CFGetTypeID(value) != CFBooleanGetTypeID(),
              value.doubleValue.isFinite else { return nil }
        return value.doubleValue
    }
    private static func displayValue(_ value: Any, metric: TrialMetric) throws -> Double {
        guard let number = number(value), number >= 0 else {
            throw CommandError.invalid("The recorded \(metric.title.lowercased()) data contains an invalid measurement. No samples have been removed or replaced.")
        }
        let displayed = metric.isTTFT ? number * 1_000 : number
        guard displayed.isFinite else {
            throw CommandError.invalid("The recorded \(metric.title.lowercased()) value is too large to display in \(metric.unit).")
        }
        return displayed
    }
    private static func recordedWarnings(_ meta: [String: Any]) -> [RecordedBenchmarkWarning] {
        let definitions = [
            RecordedBenchmarkWarning(id: "cached_ttft_warning", title: "Cached TTFT warning",
                explanation: "The test recorded cached TTFT close to cold TTFT. These timings alone do not establish a cache miss; review the recorded cache evidence."),
            RecordedBenchmarkWarning(id: "word_fallback_warning", title: "Estimated token counts",
                explanation: "The test recorded word-based token estimates. Throughput should not be treated as an exact token measurement."),
            RecordedBenchmarkWarning(id: "engine_version_warning", title: "Engine version unavailable",
                explanation: "The engine version was not verified for this test. Version differences may limit comparisons."),
            RecordedBenchmarkWarning(id: "sustained_throttling_warning", title: "Sustained performance warning",
                explanation: "The test recorded a late throughput drop alongside a changed or non-nominal thermal state. This observation does not isolate its cause."),
            RecordedBenchmarkWarning(id: "memory_pressure_warning", title: "System memory pressure warning",
                explanation: "The test recorded increased system-wide swap use. Other processes can contribute; this is not the model's own memory usage.")
        ]
        return definitions.filter {
            guard let flag = meta[$0.id] as? NSNumber, CFGetTypeID(flag) == CFBooleanGetTypeID() else { return false }
            return flag.boolValue
        }
    }
}
