import SwiftUI
import WidgetKit

internal enum WatchWidgetStyle {
    internal static let detailsSpacing: CGFloat = 3
    internal static let timelineRefreshInterval: TimeInterval = 900
    internal static let fullPercent: Double = 100

    internal static var supportedFamilies: [WidgetFamily] {
        var families: [WidgetFamily] = []
        families.append(.accessoryCircular)
        families.append(.accessoryRectangular)
        families.append(.accessoryInline)
        return families
    }

    internal static func clampedPercent(_ percent: Double?) -> Double {
        min(max(percent ?? 0, 0), fullPercent)
    }
}

internal struct WatchCapacityEntry: TimelineEntry {
    internal let date: Date
    internal let snapshot: CodexSnapshot?
}

internal struct WatchCapacityProvider: TimelineProvider {
    internal func placeholder(in _: Context) -> WatchCapacityEntry {
        WatchCapacityEntry(date: Date(), snapshot: .fixture)
    }

    internal func getSnapshot(
        in context: Context,
        completion: @escaping (WatchCapacityEntry) -> Void
    ) {
        completion(
            WatchCapacityEntry(
                date: Date(),
                snapshot: context.isPreview ? .fixture : SnapshotCache.load()
            )
        )
    }

    internal func getTimeline(
        in _: Context,
        completion: @escaping (Timeline<WatchCapacityEntry>) -> Void
    ) {
        let entry: WatchCapacityEntry = .init(date: Date(), snapshot: SnapshotCache.load())
        let interval: TimeInterval = WatchWidgetStyle.timelineRefreshInterval
        let refresh: Date = .init(timeIntervalSinceNow: interval)
        completion(Timeline(entries: [entry], policy: .after(refresh)))
    }
}

internal struct WatchCapacityWidgetView: View {
    @Environment(\.widgetFamily)
    private var family: WidgetFamily

    internal let entry: WatchCapacityEntry

    internal var body: some View {
        if let snapshot = entry.snapshot {
            snapshotContent(for: snapshot)
        } else {
            Label("Open iPhone app", systemImage: "iphone")
                .font(.caption)
        }
    }

    @ViewBuilder
    private func snapshotContent(for snapshot: CodexSnapshot) -> some View {
        switch family {
        case .accessoryCircular:
            gauge(for: snapshot)

        case .accessoryInline:
            Label(inlineSummary(for: snapshot), systemImage: stateSymbol(for: snapshot))

        default:
            details(for: snapshot)
        }
    }

    private func gauge(for snapshot: CodexSnapshot) -> some View {
        Gauge(
            value: WatchWidgetStyle.clampedPercent(snapshot.selectedAggregate?.remainingPercent),
            in: 0...WatchWidgetStyle.fullPercent
        ) {
            Image(systemName: "bolt.shield.fill")
        } currentValueLabel: {
            Text("\(snapshot.summary.usableNow)")
                .font(.headline)
                .monospacedDigit()
        }
        .gaugeStyle(.accessoryCircularCapacity)
        .tint(stateTint(for: snapshot))
    }

    private func details(for snapshot: CodexSnapshot) -> some View {
        VStack(alignment: .leading, spacing: WatchWidgetStyle.detailsSpacing) {
            Label(
                "Codex · \(stateText(for: snapshot))",
                systemImage: stateSymbol(for: snapshot)
            )
            .font(.headline)
            .foregroundStyle(stateTint(for: snapshot))
            Text(readinessSummary(for: snapshot))
                .font(.caption)
            Text(capacitySummary(for: snapshot))
                .font(.caption2)
                .foregroundStyle(.secondary)
            recoveryLabel(for: snapshot)
        }
    }

    @ViewBuilder
    private func recoveryLabel(for snapshot: CodexSnapshot) -> some View {
        Label(
            CapacityFormatting.relative(snapshot.summary.nextUsefulCapacityAt),
            systemImage: "clock.arrow.circlepath"
        )
        .font(.caption2)
        .foregroundStyle(.secondary)
    }

    private func readinessSummary(for snapshot: CodexSnapshot) -> String {
        "\(snapshot.summary.usableNow) of \(snapshot.summary.enabledAccounts) accounts ready"
    }

    private func capacitySummary(for snapshot: CodexSnapshot) -> String {
        CapacityFormatting.percent(snapshot.selectedAggregate?.remainingPercent) + " capacity left"
    }

    private func inlineSummary(for snapshot: CodexSnapshot) -> String {
        "Codex \(snapshot.summary.usableNow)/\(snapshot.summary.enabledAccounts) ready"
    }

    private func stateText(for snapshot: CodexSnapshot) -> String {
        if snapshot.isStale {
            return "stale"
        }
        if snapshot.summary.usableNow == 0 {
            return "no capacity"
        }
        if snapshot.importantWarningCount > 0 {
            return "attention"
        }
        return "verified"
    }

    private func stateSymbol(for snapshot: CodexSnapshot) -> String {
        snapshot.requiresAttention
            ? "exclamationmark.triangle.fill"
            : "checkmark.shield.fill"
    }

    private func stateTint(for snapshot: CodexSnapshot) -> Color {
        if snapshot.summary.usableNow == 0 {
            return .red
        }
        if snapshot.requiresAttention {
            return .orange
        }
        return .green
    }
}

@main
internal struct CodexStatusWatchWidget: Widget {
    internal let kind: String = "CodexStatusWatchWidget"

    internal var body: some WidgetConfiguration {
        StaticConfiguration(kind: kind, provider: WatchCapacityProvider()) { entry in
            WatchCapacityWidgetView(entry: entry)
                .containerBackground(.fill.tertiary, for: .widget)
        }
        .configurationDisplayName("Codex Capacity")
        .description("Verified capacity and ready-account count in the Smart Stack.")
        .supportedFamilies(WatchWidgetStyle.supportedFamilies)
    }
}
