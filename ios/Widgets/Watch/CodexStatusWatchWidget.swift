import SwiftUI
import WidgetKit

struct WatchCapacityEntry: TimelineEntry {
    let date: Date
    let snapshot: CodexSnapshot?
}

struct WatchCapacityProvider: TimelineProvider {
    func placeholder(in context: Context) -> WatchCapacityEntry {
        WatchCapacityEntry(date: Date(), snapshot: .fixture)
    }

    func getSnapshot(in context: Context, completion: @escaping (WatchCapacityEntry) -> Void) {
        completion(
            WatchCapacityEntry(
                date: Date(),
                snapshot: context.isPreview ? .fixture : SnapshotCache.load()
            )
        )
    }

    func getTimeline(in context: Context, completion: @escaping (Timeline<WatchCapacityEntry>) -> Void) {
        completion(
            Timeline(
                entries: [WatchCapacityEntry(date: Date(), snapshot: SnapshotCache.load())],
                policy: .after(Date(timeIntervalSinceNow: 15 * 60))
            )
        )
    }
}

struct WatchCapacityWidgetView: View {
    @Environment(\.widgetFamily) private var family
    let entry: WatchCapacityEntry

    private func stateText(for snapshot: CodexSnapshot) -> String {
        if snapshot.isStale { return "stale" }
        if snapshot.summary.usableNow == 0 { return "no capacity" }
        if snapshot.importantWarningCount > 0 { return "attention" }
        return "verified"
    }

    private func stateSymbol(for snapshot: CodexSnapshot) -> String {
        snapshot.requiresAttention
            ? "exclamationmark.triangle.fill"
            : "checkmark.shield.fill"
    }

    private func stateTint(for snapshot: CodexSnapshot) -> Color {
        if snapshot.summary.usableNow == 0 { return .red }
        if snapshot.requiresAttention { return .orange }
        return .green
    }

    var body: some View {
        if let snapshot = entry.snapshot {
            switch family {
            case .accessoryCircular:
                Gauge(
                    value: min(max(snapshot.selectedAggregate?.remainingPercent ?? 0, 0), 100),
                    in: 0 ... 100
                ) {
                    Image(systemName: "bolt.shield.fill")
                } currentValueLabel: {
                    Text("\(snapshot.summary.usableNow)")
                        .font(.headline)
                        .monospacedDigit()
                }
                .gaugeStyle(.accessoryCircularCapacity)
                .tint(stateTint(for: snapshot))
            case .accessoryInline:
                Label(
                    "Codex \(snapshot.summary.usableNow)/\(snapshot.summary.enabledAccounts) ready",
                    systemImage: stateSymbol(for: snapshot)
                )
            default:
                VStack(alignment: .leading, spacing: 3) {
                    Label(
                        "Codex · \(stateText(for: snapshot))",
                        systemImage: stateSymbol(for: snapshot)
                    )
                    .font(.headline)
                    .foregroundStyle(stateTint(for: snapshot))
                    Text("\(snapshot.summary.usableNow) of \(snapshot.summary.enabledAccounts) accounts ready")
                        .font(.caption)
                    Text(CapacityFormatting.percent(snapshot.selectedAggregate?.remainingPercent) + " capacity left")
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                    Label(
                        CapacityFormatting.relative(snapshot.summary.nextUsefulCapacityAt),
                        systemImage: "clock.arrow.circlepath"
                    )
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                }
            }
        } else {
            Label("Open iPhone app", systemImage: "iphone")
                .font(.caption)
        }
    }
}

@main
struct CodexStatusWatchWidget: Widget {
    let kind = "CodexStatusWatchWidget"

    var body: some WidgetConfiguration {
        StaticConfiguration(kind: kind, provider: WatchCapacityProvider()) { entry in
            WatchCapacityWidgetView(entry: entry)
                .containerBackground(.fill.tertiary, for: .widget)
        }
        .configurationDisplayName("Codex Capacity")
        .description("Verified capacity and ready-account count in the Smart Stack.")
        .supportedFamilies([
            .accessoryCircular,
            .accessoryRectangular,
            .accessoryInline
        ])
    }
}
