import Charts
import SwiftUI

struct BenchmarkTrialsView: View {
    var file: URL
    var revision: UUID
    @State private var data: BenchmarkTrialData?
    @State private var error: String?
    @State private var showMeans = false

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            Divider()
            if let data {
                VStack(alignment: .leading, spacing: 6) {
                    Text(data.model).font(ChronosStyle.sectionTitle).textSelection(.enabled)
                    ChronosHelp([data.engine, data.conditions].filter { !$0.isEmpty }.joined(separator: " · "))
                }
                ChronosActions {
                    VStack(alignment: .leading, spacing: 4) {
                        Text("Trial measurements").font(ChronosStyle.label)
                        ChronosHelp("\(data.count) \(data.count == 1 ? "trial" : "trials") · \(data.protocolLabel)")
                    }
                    Spacer(minLength: 12)
                    Toggle("Show recorded means", isOn: $showMeans).toggleStyle(.checkbox)
                        .disabled(!data.series.contains { $0.recordedMean != nil })
                        .accessibilityIdentifier("results.trials.means")
                }
                ViewThatFits(in: .horizontal) {
                    HStack(alignment: .top, spacing: 16) {
                        chart(data, ttft: true).frame(minWidth: 330)
                        chart(data, ttft: false).frame(minWidth: 330)
                    }
                    VStack(spacing: 16) {
                        chart(data, ttft: true)
                        chart(data, ttft: false)
                    }
                }
                ChronosHelp("Each point is a recorded trial. Trials can use different prompts; the points do not represent a time series.")
                ForEach(data.warnings) { warning in
                    VStack(alignment: .leading, spacing: 6) {
                        Label(warning.title, systemImage: "info.circle").font(ChronosStyle.label)
                            .foregroundStyle(ChronosStyle.accent)
                        ChronosHelp(warning.explanation)
                    }
                    .frame(maxWidth: .infinity, alignment: .leading).padding(14)
                    .background(ChronosStyle.accent.opacity(0.06), in: RoundedRectangle(cornerRadius: 8))
                }
                ChronosHelp("Source: " + file.lastPathComponent)
            } else if let error {
                Text("Trial charts unavailable").font(ChronosStyle.label)
                ChronosHelp(error)
            } else {
                ProgressView("Reading recorded trials…").font(ChronosStyle.help)
            }
        }
        .task(id: revision) {
            data = nil; error = nil
            let worker = Task.detached(priority: .utility) {
                try Task.checkCancellation()
                let result = try BenchmarkTrialData.load(file)
                try Task.checkCancellation()
                return result
            }
            do {
                let loaded = try await withTaskCancellationHandler {
                    try await worker.value
                } onCancel: { worker.cancel() }
                guard !Task.isCancelled else { return }
                data = loaded
            } catch is CancellationError {
                // The current selection or refresh owns the displayed charts.
            } catch {
                guard !Task.isCancelled else { return }
                self.error = error.localizedDescription
            }
        }
    }
    private func chart(_ data: BenchmarkTrialData, ttft: Bool) -> some View {
        TrialChartView(title: ttft ? "Time to first token" : "Token throughput",
            metrics: ttft ? [.cold, .cached] : [.request, .decode],
            series: data.series.filter { $0.metric.isTTFT == ttft }, count: data.count, showMeans: showMeans)
    }
}

private struct TrialChartPoint: Identifiable {
    var metric: TrialMetric
    var trial: Int
    var value: Double
    var id: String { "\(metric.rawValue)-\(trial)" }
}

private struct TrialChartView: View {
    var title: String
    var metrics: [TrialMetric]
    var series: [RecordedTrialSeries]
    var count: Int
    var showMeans: Bool
    @State private var selectedPoint: String?
    @State private var hoveredPoint: String?

    private var points: [TrialChartPoint] {
        series.flatMap { series in
            series.values.enumerated().map { TrialChartPoint(metric: series.metric, trial: $0.offset + 1, value: $0.element) }
        }
    }
    private var activePointID: String? { hoveredPoint ?? selectedPoint }
    private var activePoint: TrialChartPoint? { points.first { $0.id == activePointID } }
    private var yDomain: ClosedRange<Double> {
        let values = points.map(\.value) + (showMeans ? series.compactMap(\.recordedMean) : [])
        let largest = values.max() ?? 0
        let padded = largest * 1.15
        return 0...(largest == 0 ? 1 : (padded.isFinite ? padded : largest))
    }
    private var trialTicks: [Int] {
        let step = max(1, Int(ceil(Double(count) / 10)))
        return Array(Set(Array(stride(from: 1, through: count, by: step)) + [count])).sorted()
    }
    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text(title).font(ChronosStyle.label).accessibilityAddTraits(.isHeader)
            if let primary = series.first(where: { $0.metric == metrics.first }), let mean = primary.recordedMean {
                HStack(alignment: .firstTextBaseline, spacing: 6) {
                    Text(Self.format(mean)).font(.system(size: 27, weight: .semibold)).monospacedDigit()
                    Text(primary.metric.unit).font(ChronosStyle.help).foregroundStyle(ChronosStyle.secondary)
                    Spacer()
                    ChronosHelp("Recorded \(primary.metric.title.lowercased()) mean")
                }
            } else {
                ChronosHelp("Recorded mean unavailable · \(metrics[0].unit)")
            }
            HStack(spacing: 16) {
                ForEach(metrics) { metric in
                    HStack(spacing: 6) {
                        if primary(metric) { Circle().fill(color(metric)).frame(width: 7, height: 7) }
                        else { Rectangle().fill(color(metric)).frame(width: 6, height: 6).rotationEffect(.degrees(45)) }
                        Text(metric.title + (series.contains { $0.metric == metric } ? "" : " · not recorded"))
                            .font(ChronosStyle.help).foregroundStyle(ChronosStyle.secondary)
                    }
                }
            }
            if series.isEmpty {
                ChronosHelp("No individual samples recorded for this chart.")
                    .frame(height: 210, alignment: .center)
            } else {
                plot.frame(height: 210)
                Picker("Inspect point", selection: $selectedPoint) {
                    Text("Select a point…").tag(nil as String?)
                    ForEach(points) { point in
                        Text("Trial \(point.trial) · \(point.metric.title)").tag(point.id as String?)
                    }
                }
                .font(ChronosStyle.help)
                .help("Hover or click a point, or choose a sample from this menu.")
                .accessibilityLabel(title + ": inspect point")
                .accessibilityIdentifier("results.trials.\(metrics[0].rawValue).inspect")
                if let point = activePoint {
                    Text("Trial \(point.trial) · \(point.metric.title) · \(Self.format(point.value)) \(point.metric.unit)")
                        .font(ChronosStyle.label).monospacedDigit().textSelection(.enabled)
                        .accessibilityIdentifier("results.trials.\(metrics[0].rawValue).value")
                } else {
                    ChronosHelp("Hover or select a point to inspect its recorded value.")
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading).padding(18)
        .background(ChronosStyle.inset, in: RoundedRectangle(cornerRadius: 10))
        .overlay { RoundedRectangle(cornerRadius: 10).strokeBorder(ChronosStyle.rule, lineWidth: 1).allowsHitTesting(false) }
        .onChange(of: series) { _, _ in selectedPoint = nil; hoveredPoint = nil }
    }
    private var plot: some View {
        Chart {
            if showMeans {
                ForEach(series) { series in
                    if let mean = series.recordedMean {
                        RuleMark(y: .value("Recorded mean", mean))
                            .foregroundStyle(color(series.metric).opacity(0.5))
                            .lineStyle(StrokeStyle(lineWidth: 1, dash: [4, 4]))
                            .accessibilityLabel("Recorded \(series.metric.title.lowercased()) mean")
                            .accessibilityValue("\(Self.format(mean)) \(series.metric.unit)")
                    }
                }
            }
            ForEach(points) { point in
                PointMark(x: .value("Trial", point.trial), y: .value(point.metric.unit, point.value))
                    .foregroundStyle(color(point.metric))
                    .symbol(primary(point.metric) ? .circle : .diamond)
                    .symbolSize(point.id == activePointID ? 105 : 55)
                    .accessibilityLabel("\(point.metric.title), trial \(point.trial)")
                    .accessibilityValue("\(Self.format(point.value)) \(point.metric.unit)")
            }
        }
        .chartXScale(domain: 0.5...(Double(count) + 0.5))
        .chartYScale(domain: yDomain)
        .chartXAxis {
            AxisMarks(values: trialTicks) { _ in AxisTick(); AxisValueLabel() }
        }
        .chartXAxisLabel("Trial")
        .chartYAxis {
            AxisMarks(position: .leading, values: .automatic(desiredCount: 4)) { value in
                AxisGridLine().foregroundStyle(ChronosStyle.rule.opacity(0.65))
                AxisValueLabel {
                    if let value = value.as(Double.self) { Text(Self.format(value)) }
                }
            }
        }
        .chartOverlay { proxy in
            GeometryReader { geometry in
                Rectangle().fill(.clear).contentShape(Rectangle())
                    .onContinuousHover { phase in
                        switch phase {
                        case .active(let location): hoveredPoint = nearestPoint(location, proxy: proxy, geometry: geometry)
                        case .ended: hoveredPoint = nil
                        }
                    }
                    .gesture(SpatialTapGesture().onEnded { value in
                        selectedPoint = nearestPoint(value.location, proxy: proxy, geometry: geometry)
                    })
                    .accessibilityHidden(true)
            }
        }
        .accessibilityLabel(title + " in " + metrics[0].unit)
    }
    private func nearestPoint(_ location: CGPoint, proxy: ChartProxy, geometry: GeometryProxy) -> String? {
        guard let anchor = proxy.plotFrame else { return nil }
        let frame = geometry[anchor]
        // A zero sample sits on the axis; include the visible symbol's edge.
        guard frame.insetBy(dx: -8, dy: -8).contains(location) else { return nil }
        let local = CGPoint(x: location.x - frame.minX, y: location.y - frame.minY)
        var closest: (id: String, distance: CGFloat)?
        for point in points {
            guard let x = proxy.position(forX: point.trial), let y = proxy.position(forY: point.value) else { continue }
            let dx = local.x - x, dy = local.y - y
            let distance = dx * dx + dy * dy
            if distance <= 24 * 24 && distance < (closest?.distance ?? .infinity) { closest = (point.id, distance) }
        }
        return closest?.id
    }
    private func primary(_ metric: TrialMetric) -> Bool { metric == .cold || metric == .request }
    private func color(_ metric: TrialMetric) -> Color { primary(metric) ? ChronosStyle.accent : ChronosStyle.secondary }
    private static func format(_ value: Double) -> String {
        if value != 0 && (value < 0.01 || value >= 1_000_000) { return String(format: "%.3g", value) }
        return value.formatted(.number.precision(.fractionLength(0...2)))
    }
}
