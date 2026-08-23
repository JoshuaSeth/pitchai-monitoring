import SwiftUI

struct WatchCapacityView: View {
    @EnvironmentObject private var store: WatchSnapshotStore

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: 10) {
                    if let snapshot = store.snapshot {
                        WatchHero(snapshot: snapshot)

                        if let message = store.message {
                            Label(message, systemImage: "info.circle.fill")
                                .font(.caption2)
                                .foregroundStyle(.orange)
                                .multilineTextAlignment(.leading)
                                .frame(maxWidth: .infinity, alignment: .leading)
                                .padding(8)
                                .background(.orange.opacity(0.1), in: RoundedRectangle(cornerRadius: 10))
                        }

                        ForEach(snapshot.accounts) { account in
                            WatchAccountRow(account: account)
                        }

                        Button {
                            store.refresh()
                        } label: {
                            if store.isRefreshing {
                                ProgressView()
                                    .frame(maxWidth: .infinity)
                            } else {
                                Label("Refresh via iPhone", systemImage: "arrow.clockwise")
                                    .frame(maxWidth: .infinity)
                            }
                        }
                        .buttonStyle(.borderedProminent)
                        .tint(.cyan)
                        .disabled(store.isRefreshing)
                    } else {
                        ContentUnavailableView(
                            "No snapshot",
                            systemImage: "iphone.and.arrow.forward",
                            description: Text(store.message ?? "Open Codex Status on the paired iPhone first.")
                        )
                    }
                }
                .padding(.horizontal, 2)
            }
            .navigationTitle("Codex")
        }
    }
}

private struct WatchHero: View {
    let snapshot: CodexSnapshot

    private var percentage: Double {
        snapshot.selectedAggregate?.remainingPercent ?? 0
    }

    var body: some View {
        HStack(spacing: 10) {
            Gauge(value: min(max(percentage, 0), 100), in: 0 ... 100) {
                EmptyView()
            } currentValueLabel: {
                Text(CapacityFormatting.percent(percentage))
                    .font(.caption2.bold())
                    .monospacedDigit()
            }
            .gaugeStyle(.accessoryCircularCapacity)
            .tint(Gradient(colors: [.mint, .cyan]))
            .frame(width: 54, height: 54)

            VStack(alignment: .leading, spacing: 2) {
                Text("\(snapshot.summary.usableNow) of \(snapshot.summary.enabledAccounts)")
                    .font(.title3.bold())
                    .monospacedDigit()
                Text("accounts ready")
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                Label(
                    snapshot.isStale ? "Stale" : "Verified",
                    systemImage: snapshot.isStale ? "clock.badge.exclamationmark" : "checkmark.shield.fill"
                )
                .font(.system(size: 9, weight: .semibold))
                .foregroundStyle(snapshot.isStale ? .orange : .green)
            }
            Spacer(minLength: 0)
        }
        .padding(10)
        .background(
            LinearGradient(
                colors: [.cyan.opacity(0.2), .blue.opacity(0.08)],
                startPoint: .topLeading,
                endPoint: .bottomTrailing
            ),
            in: RoundedRectangle(cornerRadius: 14)
        )
    }
}

private struct WatchAccountRow: View {
    let account: CodexAccount

    private var tint: Color {
        switch account.status {
        case "available": .green
        case "auth_invalid": .red
        case "five_hour_limited", "weekly_limited": .orange
        default: .gray
        }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 6) {
                Image(systemName: CapacityFormatting.statusSymbol(account.status))
                    .foregroundStyle(tint)
                Text(account.label)
                    .font(.caption.bold())
                    .lineLimit(1)
                Spacer(minLength: 2)
                Text(CapacityFormatting.percent(account.fiveHour.remainingPercent))
                    .font(.caption2.bold())
                    .monospacedDigit()
            }
            ProgressView(value: min(max((account.fiveHour.remainingPercent ?? 0) / 100, 0), 1))
                .tint(tint)
            Text(CapacityFormatting.relative(account.fiveHour.resetAt))
                .font(.system(size: 9))
                .foregroundStyle(.secondary)
        }
        .padding(9)
        .background(.quaternary.opacity(0.55), in: RoundedRectangle(cornerRadius: 11))
        .accessibilityElement(children: .combine)
    }
}

#Preview {
    WatchCapacityView()
        .environmentObject(WatchSnapshotStore())
}
