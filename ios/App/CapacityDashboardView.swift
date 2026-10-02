import SwiftUI

internal struct CapacityDashboardView: View {
    internal enum Style {
        internal static let stackSpacing: CGFloat = 16
        internal static let horizontalPadding: CGFloat = 16
        internal static let topPadding: CGFloat = 10
        internal static let bottomPadding: CGFloat = 28
        internal static let sectionSpacing: CGFloat = 10
    }

    @EnvironmentObject private var store: SnapshotStore

    internal var body: some View {
        NavigationStack {
            ScrollView {
                dashboardContent
            }
            .background(Color(uiColor: .systemGroupedBackground))
            .navigationTitle("Codex Status")
            .toolbar { refreshToolbar }
            .refreshable {
                await store.refresh(manual: true)
            }
        }
        .tint(.cyan)
    }

    private var dashboardContent: some View {
        LazyVStack(spacing: Style.stackSpacing) {
            if let snapshot = store.snapshot {
                CapacityHero(snapshot: snapshot)
                failureNotice(for: snapshot)
                refreshNotice
                availabilityNotice(for: snapshot)
                WarningStrip(warnings: snapshot.warnings)
                accountsSection(for: snapshot)
                PrivacyFooter()
            } else {
                EmptyCapacityState(message: failureMessage, isLoading: store.state == .loading)
            }
        }
        .padding(.horizontal, Style.horizontalPadding)
        .padding(.top, Style.topPadding)
        .padding(.bottom, Style.bottomPadding)
    }

    private var failureMessage: String? {
        if case .failed(let message) = store.state {
            return message
        }
        return nil
    }

    private var refreshToolbar: some ToolbarContent {
        ToolbarItem(placement: .topBarTrailing) {
            Button {
                Task {
                    await store.refresh(manual: true)
                }
            } label: {
                refreshButtonLabel
            }
            .disabled(store.state == .loading)
            .accessibilityLabel("Refresh broker capacity")
        }
    }

    @ViewBuilder private var refreshNotice: some View {
        if let notice = store.refreshNotice {
            ServiceMessageCard(
                symbol: "checkmark.circle.fill",
                title: "Refresh",
                message: notice,
                tint: .teal
            )
        }
    }

    @ViewBuilder private var refreshButtonLabel: some View {
        if store.state == .loading {
            ProgressView()
        } else {
            Image(systemName: "arrow.clockwise")
        }
    }

    @ViewBuilder
    private func failureNotice(for snapshot: CodexSnapshot) -> some View {
        if case .failed(let message) = store.state {
            ServiceMessageCard(
                symbol: "wifi.exclamationmark",
                title: "Refresh failed",
                message: message,
                tint: .orange
            )
        } else if snapshot.isStale {
            ServiceMessageCard(
                symbol: "clock.badge.exclamationmark",
                title: "Data may be stale",
                message: "The last verified broker state is still shown with its timestamp.",
                tint: .orange
            )
        }
    }

    @ViewBuilder
    private func availabilityNotice(for snapshot: CodexSnapshot) -> some View {
        if snapshot.summary.usableNow == 0 {
            ServiceMessageCard(
                symbol: "person.crop.circle.badge.exclamationmark",
                title: "No accounts available",
                message: "The broker currently has no selectable Codex account. "
                    + "Review warnings or wait for the next reset.",
                tint: .red
            )
        }
    }

    private func accountsSection(for snapshot: CodexSnapshot) -> some View {
        VStack(alignment: .leading, spacing: Style.sectionSpacing) {
            SectionHeading(
                title: "Accounts",
                detail: "\(snapshot.summary.usableNow) of \(snapshot.summary.enabledAccounts) ready"
            )
            ForEach(snapshot.accounts) { account in
                AccountCapacityCard(account: account)
            }
        }
    }
}

#Preview {
    CapacityDashboardView()
        .environmentObject(SnapshotStore(fixtureMode: true))
}
