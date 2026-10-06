import SwiftUI

internal struct WatchCapacityView: View {
    internal enum Style {
        internal static let stackSpacing: CGFloat = 10
        internal static let horizontalPadding: CGFloat = 2
        internal static let labelPadding: CGFloat = 8
        internal static let messagePadding: CGFloat = 8
        internal static let messageFillOpacity: Double = 0.1
        internal static let messageCornerRadius: CGFloat = 10
    }

    @EnvironmentObject private var store: WatchSnapshotStore

    internal var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: Style.stackSpacing) {
                    if let snapshot = store.snapshot {
                        snapshotContent(for: snapshot)
                    } else {
                        emptyState
                    }
                }
                .padding(.horizontal, Style.horizontalPadding)
            }
            .navigationTitle("Codex")
        }
    }

    @ViewBuilder private var messageLabel: some View {
        if let message = store.message {
            Label(message, systemImage: "info.circle.fill")
                .font(.caption2)
                .foregroundStyle(.orange)
                .multilineTextAlignment(.leading)
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(Style.messagePadding)
                .background(
                    .orange.opacity(Style.messageFillOpacity),
                    in: RoundedRectangle(cornerRadius: Style.messageCornerRadius)
                )
        }
    }

    private var emptyState: some View {
        ContentUnavailableView(
            "No snapshot",
            systemImage: "iphone.and.arrow.forward",
            description: Text(store.message ?? "Open Codex Status on the paired iPhone first.")
        )
    }

    private var refreshButton: some View {
        Button {
            store.refresh()
        } label: {
            refreshButtonLabel
        }
        .buttonStyle(.borderedProminent)
        .tint(.cyan)
        .disabled(store.isRefreshing)
    }

    @ViewBuilder private var refreshButtonLabel: some View {
        if store.isRefreshing {
            ProgressView()
                .frame(maxWidth: .infinity)
        } else {
            Label("Refresh via iPhone", systemImage: "arrow.clockwise")
                .frame(maxWidth: .infinity)
        }
    }

    @ViewBuilder
    private func snapshotContent(for snapshot: CodexSnapshot) -> some View {
        WatchHero(snapshot: snapshot)
        burnFactorRows(for: snapshot)
        recoveryLabel(for: snapshot)
        attentionCards(for: snapshot)
        messageLabel
        ForEach(snapshot.accounts) { account in
            WatchAccountRow(account: account)
        }
        refreshButton
    }

    @ViewBuilder
    private func burnFactorRows(for snapshot: CodexSnapshot) -> some View {
        if let burnFactors = snapshot.burnFactors {
            Text("Burn factor · 24h → 6d")
                .font(.caption2.weight(.semibold))
                .foregroundStyle(.secondary)
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.horizontal, Style.labelPadding)
            ForEach(burnFactors.pools) { pool in
                WatchBurnFactorRow(pool: pool)
            }
        }
    }

    private func recoveryLabel(for snapshot: CodexSnapshot) -> some View {
        Label(
            CapacityFormatting.relative(snapshot.summary.nextUsefulCapacityAt),
            systemImage: "clock.arrow.circlepath"
        )
        .font(.caption2.weight(.semibold))
        .foregroundStyle(.secondary)
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.horizontal, Style.labelPadding)
    }

    @ViewBuilder
    private func attentionCards(for snapshot: CodexSnapshot) -> some View {
        if snapshot.summary.usableNow == 0 {
            WatchAttentionCard(text: "No account can be selected now", tint: .red)
        } else if snapshot.importantWarningCount > 0 {
            WatchAttentionCard(text: warningDescription(for: snapshot), tint: .orange)
        }
    }

    private func warningDescription(for snapshot: CodexSnapshot) -> String {
        let plural: String = snapshot.importantWarningCount == 1 ? "" : "s"
        return "\(snapshot.importantWarningCount) broker warning\(plural)"
    }
}

#Preview {
    WatchCapacityView()
        .environmentObject(WatchSnapshotStore())
}
