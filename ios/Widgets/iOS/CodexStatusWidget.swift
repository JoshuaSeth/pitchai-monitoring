import SwiftUI
import WidgetKit

internal enum CapacityWidgetStyle {
    internal static let gradientTopRed: Double = 0.06
    internal static let gradientTopGreen: Double = 0.2
    internal static let gradientTopBlue: Double = 0.28
    internal static let gradientBottomRed: Double = 0.02
    internal static let gradientBottomGreen: Double = 0.07
    internal static let gradientBottomBlue: Double = 0.11
    internal static let compactSpacing: CGFloat = 7
    internal static let regularSpacing: CGFloat = 10
    internal static let accessorySpacing: CGFloat = 2
    internal static let compactValueFontSize: CGFloat = 23
    internal static let regularValueFontSize: CGFloat = 28
    internal static let staleBadgeFontSize: CGFloat = 8
    internal static let staleValueOpacity: Double = 0.68
    internal static let detailOpacity: Double = 0.7
    internal static let recoveryOpacity: Double = 0.8
    internal static let timelineRefreshInterval: TimeInterval = 900
    internal static let fullPercent: Double = 100

    internal static var gradient: LinearGradient {
        LinearGradient(
            colors: [gradientTop, gradientBottom],
            startPoint: .topLeading,
            endPoint: .bottomTrailing
        )
    }

    private static var gradientTop: Color {
        Color(red: gradientTopRed, green: gradientTopGreen, blue: gradientTopBlue)
    }

    private static var gradientBottom: Color {
        Color(red: gradientBottomRed, green: gradientBottomGreen, blue: gradientBottomBlue)
    }

    internal static var supportedFamilies: [WidgetFamily] {
        var families: [WidgetFamily] = []
        families.append(.systemSmall)
        families.append(.systemMedium)
        families.append(.accessoryCircular)
        families.append(.accessoryRectangular)
        families.append(.accessoryInline)
        return families
    }

    internal static func fraction(of percent: Double?) -> Double {
        min(max((percent ?? 0) / fullPercent, 0), 1)
    }

    internal static func clampedPercent(_ percent: Double?) -> Double {
        min(max(percent ?? 0, 0), fullPercent)
    }
}

internal struct CapacityTimelineEntry: TimelineEntry {
    internal let date: Date
    internal let snapshot: CodexSnapshot?
}

internal struct CapacityTimelineProvider: TimelineProvider {
    internal func placeholder(in _: Context) -> CapacityTimelineEntry {
        CapacityTimelineEntry(date: Date(), snapshot: .fixture)
    }

    internal func getSnapshot(
        in context: Context,
        completion: @escaping (CapacityTimelineEntry) -> Void
    ) {
        completion(
            CapacityTimelineEntry(
                date: Date(),
                snapshot: context.isPreview ? .fixture : SnapshotCache.load()
            )
        )
    }

    internal func getTimeline(
        in _: Context,
        completion: @escaping (Timeline<CapacityTimelineEntry>) -> Void
    ) {
        let entry: CapacityTimelineEntry = .init(date: Date(), snapshot: SnapshotCache.load())
        let interval: TimeInterval = CapacityWidgetStyle.timelineRefreshInterval
        let refresh: Date = .init(timeIntervalSinceNow: interval)
        completion(Timeline(entries: [entry], policy: .after(refresh)))
    }
}

internal struct AccessoryCapacityGauge: View {
    internal let snapshot: CodexSnapshot

    internal var body: some View {
        Gauge(
            value: CapacityWidgetStyle.clampedPercent(snapshot.selectedAggregate?.remainingPercent),
            in: 0...CapacityWidgetStyle.fullPercent
        ) {
            Image(systemName: "bolt.shield.fill")
        } currentValueLabel: {
            Text("\(snapshot.summary.usableNow)")
                .font(.headline)
                .monospacedDigit()
        }
        .gaugeStyle(.accessoryCircularCapacity)
    }
}

internal struct AccessoryCapacityRectangle: View {
    internal let snapshot: CodexSnapshot

    internal var body: some View {
        VStack(alignment: .leading, spacing: CapacityWidgetStyle.accessorySpacing) {
            Label("Codex capacity", systemImage: symbol)
                .font(.headline)
            Text(summary)
                .font(.caption)
            ProgressView(
                value: CapacityWidgetStyle.fraction(
                    of: snapshot.selectedAggregate?.remainingPercent
                )
            )
        }
    }

    private var symbol: String {
        snapshot.isStale ? "clock.badge.exclamationmark" : "checkmark.shield.fill"
    }

    private var summary: String {
        let ready: String =
            "\(snapshot.summary.usableNow) of \(snapshot.summary.enabledAccounts) ready"
        let capacity: String = CapacityFormatting.percent(
            snapshot.selectedAggregate?.remainingPercent
        )
        return "\(ready) · \(capacity) left"
    }
}

internal struct SystemCapacityWidget: View {
    internal let snapshot: CodexSnapshot
    internal let compact: Bool

    internal var body: some View {
        VStack(alignment: .leading, spacing: spacing) {
            header
            readiness
            ProgressView(
                value: CapacityWidgetStyle.fraction(
                    of: snapshot.selectedAggregate?.remainingPercent
                )
            )
            .tint(.cyan)
            footer
            recovery
        }
    }

    @ViewBuilder private var recovery: some View {
        if !compact, let next = snapshot.summary.nextUsefulCapacityAt {
            Label(CapacityFormatting.relative(next), systemImage: "clock.arrow.circlepath")
                .font(.caption2)
                .foregroundStyle(.white.opacity(CapacityWidgetStyle.recoveryOpacity))
        }
    }

    private var spacing: CGFloat {
        compact ? CapacityWidgetStyle.compactSpacing : CapacityWidgetStyle.regularSpacing
    }

    private var valueFontSize: CGFloat {
        compact
            ? CapacityWidgetStyle.compactValueFontSize : CapacityWidgetStyle.regularValueFontSize
    }

    private var header: some View {
        HStack {
            Label("CODEX", systemImage: "checkmark.shield.fill")
                .font(.caption2.bold())
                .foregroundStyle(snapshot.isStale ? .orange : .mint)
            Spacer()
            staleBadge
        }
    }

    @ViewBuilder private var staleBadge: some View {
        if snapshot.isStale {
            Text("STALE")
                .font(.system(size: CapacityWidgetStyle.staleBadgeFontSize, weight: .bold))
                .foregroundStyle(.orange)
        }
    }

    private var readiness: some View {
        VStack(alignment: .leading, spacing: CapacityWidgetStyle.accessorySpacing) {
            Text("\(snapshot.summary.usableNow) ready")
                .font(.system(size: valueFontSize, weight: .bold, design: .rounded))
                .foregroundStyle(.white)
                .monospacedDigit()
            Text("of \(snapshot.summary.enabledAccounts) accounts")
                .font(.caption)
                .foregroundStyle(.white.opacity(CapacityWidgetStyle.staleValueOpacity))
        }
    }

    private var footer: some View {
        HStack {
            Text(
                CapacityFormatting.percent(snapshot.selectedAggregate?.remainingPercent)
                    + " capacity"
            )
            Spacer()
            updatedLabel
        }
        .font(.caption2)
        .foregroundStyle(.white.opacity(CapacityWidgetStyle.detailOpacity))
    }

    @ViewBuilder private var updatedLabel: some View {
        if !compact {
            Text(CapacityFormatting.updated(snapshot.generatedDate))
        }
    }
}

internal struct CodexStatusWidgetView: View {
    @Environment(\.widgetFamily)
    private var family: WidgetFamily

    internal let entry: CapacityTimelineEntry

    internal var body: some View {
        content
            .containerBackground(for: .widget) { CapacityWidgetStyle.gradient }
    }

    @ViewBuilder private var content: some View {
        if let snapshot = entry.snapshot {
            snapshotContent(for: snapshot)
        } else {
            Label("Open Codex Status", systemImage: "lock.shield")
                .font(.caption.weight(.semibold))
                .multilineTextAlignment(.center)
        }
    }

    @ViewBuilder
    private func snapshotContent(for snapshot: CodexSnapshot) -> some View {
        switch family {
        case .accessoryCircular:
            AccessoryCapacityGauge(snapshot: snapshot)

        case .accessoryInline:
            Text("Codex: \(snapshot.summary.usableNow)/\(snapshot.summary.enabledAccounts) ready")

        case .accessoryRectangular:
            AccessoryCapacityRectangle(snapshot: snapshot)

        default:
            SystemCapacityWidget(snapshot: snapshot, compact: family == .systemSmall)
        }
    }
}

@main
internal struct CodexStatusWidget: Widget {
    internal let kind: String = "CodexStatusWidget"

    internal var body: some WidgetConfiguration {
        StaticConfiguration(kind: kind, provider: CapacityTimelineProvider()) { entry in
            CodexStatusWidgetView(entry: entry)
        }
        .configurationDisplayName("Codex Capacity")
        .description("See verified broker capacity and available accounts at a glance.")
        .supportedFamilies(CapacityWidgetStyle.supportedFamilies)
    }
}
