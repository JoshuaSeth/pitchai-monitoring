import SwiftUI
import WidgetKit

struct CapacityTimelineEntry: TimelineEntry {
    let date: Date
    let snapshot: CodexSnapshot?
}

struct CapacityTimelineProvider: TimelineProvider {
    func placeholder(in context: Context) -> CapacityTimelineEntry {
        CapacityTimelineEntry(date: Date(), snapshot: .fixture)
    }

    func getSnapshot(in context: Context, completion: @escaping (CapacityTimelineEntry) -> Void) {
        completion(
            CapacityTimelineEntry(
                date: Date(),
                snapshot: context.isPreview ? .fixture : SnapshotCache.load()
            )
        )
    }

    func getTimeline(in context: Context, completion: @escaping (Timeline<CapacityTimelineEntry>) -> Void) {
        let entry = CapacityTimelineEntry(date: Date(), snapshot: SnapshotCache.load())
        completion(
            Timeline(
                entries: [entry],
                policy: .after(Date(timeIntervalSinceNow: 15 * 60))
            )
        )
    }
}

struct CodexStatusWidgetView: View {
    @Environment(\.widgetFamily) private var family
    let entry: CapacityTimelineEntry

    var body: some View {
        Group {
            if let snapshot = entry.snapshot {
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
            } else {
                Label("Open Codex Status", systemImage: "lock.shield")
                    .font(.caption.weight(.semibold))
                    .multilineTextAlignment(.center)
            }
        }
        .containerBackground(for: .widget) {
            LinearGradient(
                colors: [Color(red: 0.06, green: 0.2, blue: 0.28), Color(red: 0.02, green: 0.07, blue: 0.11)],
                startPoint: .topLeading,
                endPoint: .bottomTrailing
            )
        }
    }
}

private struct SystemCapacityWidget: View {
    let snapshot: CodexSnapshot
    let compact: Bool

    private var aggregate: WindowAggregate? { snapshot.selectedAggregate }

    var body: some View {
        VStack(alignment: .leading, spacing: compact ? 7 : 10) {
            HStack {
                Label("CODEX", systemImage: "checkmark.shield.fill")
                    .font(.caption2.bold())
                    .foregroundStyle(snapshot.isStale ? .orange : .mint)
                Spacer()
                if snapshot.isStale {
                    Text("STALE")
                        .font(.system(size: 8, weight: .bold))
                        .foregroundStyle(.orange)
                }
            }

            Text("\(snapshot.summary.usableNow) ready")
                .font(.system(size: compact ? 23 : 28, weight: .bold, design: .rounded))
                .foregroundStyle(.white)
                .monospacedDigit()
            Text("of \(snapshot.summary.enabledAccounts) accounts")
                .font(.caption)
                .foregroundStyle(.white.opacity(0.68))

            ProgressView(value: min(max((aggregate?.remainingPercent ?? 0) / 100, 0), 1))
                .tint(.cyan)

            HStack {
                Text(CapacityFormatting.percent(aggregate?.remainingPercent) + " capacity")
                Spacer()
                if !compact {
                    Text(CapacityFormatting.updated(snapshot.generatedDate))
                }
            }
            .font(.caption2)
            .foregroundStyle(.white.opacity(0.7))

            if !compact, let next = snapshot.summary.nextUsefulCapacityAt {
                Label(CapacityFormatting.relative(next), systemImage: "clock.arrow.circlepath")
                    .font(.caption2)
                    .foregroundStyle(.white.opacity(0.8))
            }
        }
    }
}

private struct AccessoryCapacityGauge: View {
    let snapshot: CodexSnapshot

    var body: some View {
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
    }
}

private struct AccessoryCapacityRectangle: View {
    let snapshot: CodexSnapshot

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            Label("Codex capacity", systemImage: snapshot.isStale ? "clock.badge.exclamationmark" : "checkmark.shield.fill")
                .font(.headline)
            Text("\(snapshot.summary.usableNow) of \(snapshot.summary.enabledAccounts) ready · \(CapacityFormatting.percent(snapshot.selectedAggregate?.remainingPercent)) left")
                .font(.caption)
            ProgressView(value: min(max((snapshot.selectedAggregate?.remainingPercent ?? 0) / 100, 0), 1))
        }
    }
}

@main
struct CodexStatusWidget: Widget {
    let kind = "CodexStatusWidget"

    var body: some WidgetConfiguration {
        StaticConfiguration(kind: kind, provider: CapacityTimelineProvider()) { entry in
            CodexStatusWidgetView(entry: entry)
        }
        .configurationDisplayName("Codex Capacity")
        .description("See verified broker capacity and available accounts at a glance.")
        .supportedFamilies([
            .systemSmall,
            .systemMedium,
            .accessoryCircular,
            .accessoryRectangular,
            .accessoryInline
        ])
    }
}
