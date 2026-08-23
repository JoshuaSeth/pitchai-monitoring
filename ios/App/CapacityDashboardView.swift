import SwiftUI

struct CapacityDashboardView: View {
    @EnvironmentObject private var store: SnapshotStore

    var body: some View {
        NavigationStack {
            ScrollView {
                LazyVStack(spacing: 16) {
                    if let snapshot = store.snapshot {
                        CapacityHero(snapshot: snapshot)

                        if case let .failed(message) = store.state {
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

                        if let notice = store.refreshNotice {
                            ServiceMessageCard(
                                symbol: "checkmark.circle.fill",
                                title: "Refresh",
                                message: notice,
                                tint: .teal
                            )
                        }

                        if snapshot.summary.usableNow == 0 {
                            ServiceMessageCard(
                                symbol: "person.crop.circle.badge.exclamationmark",
                                title: "No accounts available",
                                message: "The broker currently has no selectable Codex account. Review warnings or wait for the next reset.",
                                tint: .red
                            )
                        }

                        WarningStrip(warnings: snapshot.warnings)

                        VStack(alignment: .leading, spacing: 10) {
                            SectionHeading(
                                title: "Accounts",
                                detail: "\(snapshot.summary.usableNow) of \(snapshot.summary.enabledAccounts) ready"
                            )
                            ForEach(snapshot.accounts) { account in
                                AccountCapacityCard(account: account)
                            }
                        }

                        PrivacyFooter()
                    } else {
                        EmptyCapacityState(
                            message: failureMessage,
                            isLoading: store.state == .loading
                        )
                    }
                }
                .padding(.horizontal, 16)
                .padding(.top, 10)
                .padding(.bottom, 28)
            }
            .background(Color(uiColor: .systemGroupedBackground))
            .navigationTitle("Codex Status")
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button {
                        Task { await store.refresh(manual: true) }
                    } label: {
                        if store.state == .loading {
                            ProgressView()
                        } else {
                            Image(systemName: "arrow.clockwise")
                        }
                    }
                    .disabled(store.state == .loading)
                    .accessibilityLabel("Refresh broker capacity")
                }
            }
            .refreshable {
                await store.refresh(manual: true)
            }
        }
        .tint(.cyan)
    }

    private var failureMessage: String? {
        if case let .failed(message) = store.state { return message }
        return nil
    }
}

private struct CapacityHero: View {
    let snapshot: CodexSnapshot

    private var aggregate: WindowAggregate? { snapshot.selectedAggregate }
    private var percentage: Double { aggregate?.remainingPercent ?? 0 }

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            HStack(alignment: .top, spacing: 16) {
                ZStack {
                    Circle()
                        .stroke(.white.opacity(0.14), lineWidth: 10)
                    Circle()
                        .trim(from: 0, to: min(max(percentage / 100, 0), 1))
                        .stroke(
                            AngularGradient(
                                colors: [.mint, .cyan, .blue],
                                center: .center
                            ),
                            style: StrokeStyle(lineWidth: 10, lineCap: .round)
                        )
                        .rotationEffect(.degrees(-90))
                    VStack(spacing: 0) {
                        Text(CapacityFormatting.percent(aggregate?.remainingPercent))
                            .font(.system(size: 22, weight: .bold, design: .rounded))
                            .monospacedDigit()
                        Text("remaining")
                            .font(.caption2)
                            .foregroundStyle(.white.opacity(0.65))
                    }
                }
                .frame(width: 106, height: 106)

                VStack(alignment: .leading, spacing: 7) {
                    HStack(spacing: 6) {
                        Image(systemName: snapshot.isStale ? "exclamationmark.triangle.fill" : "checkmark.shield.fill")
                        Text(snapshot.isStale ? "STALE" : "LIVE · VERIFIED")
                    }
                    .font(.caption2.weight(.bold))
                    .foregroundStyle(snapshot.isStale ? .orange : .mint)

                    Text("\(snapshot.summary.usableNow) ready")
                        .font(.system(size: 29, weight: .bold, design: .rounded))
                        .foregroundStyle(.white)
                    Text("of \(snapshot.summary.enabledAccounts) enabled accounts")
                        .font(.subheadline)
                        .foregroundStyle(.white.opacity(0.72))
                    Text(CapacityFormatting.updated(snapshot.generatedDate))
                        .font(.caption)
                        .foregroundStyle(.white.opacity(0.58))
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            }

            Divider().overlay(.white.opacity(0.15))

            HStack(spacing: 12) {
                MetricPill(
                    title: snapshot.summary.capacityBasis.label ?? "Capacity",
                    value: CapacityFormatting.points(aggregate?.remainingPoints) + " pts"
                )
                MetricPill(
                    title: "Next recovery",
                    value: CapacityFormatting.relative(snapshot.summary.nextUsefulCapacityAt)
                        .replacingOccurrences(of: "Resets ", with: "")
                )
            }
        }
        .padding(20)
        .background(
            LinearGradient(
                colors: [Color(red: 0.07, green: 0.22, blue: 0.31), Color(red: 0.03, green: 0.08, blue: 0.13)],
                startPoint: .topLeading,
                endPoint: .bottomTrailing
            ),
            in: RoundedRectangle(cornerRadius: 24, style: .continuous)
        )
        .overlay {
            RoundedRectangle(cornerRadius: 24, style: .continuous)
                .stroke(.white.opacity(0.08), lineWidth: 1)
        }
        .accessibilityElement(children: .combine)
        .accessibilityLabel(
            "\(snapshot.summary.usableNow) of \(snapshot.summary.enabledAccounts) accounts ready. "
            + "\(CapacityFormatting.percent(aggregate?.remainingPercent)) capacity remaining."
        )
    }
}

private struct MetricPill: View {
    let title: String
    let value: String

    var body: some View {
        VStack(alignment: .leading, spacing: 3) {
            Text(title.uppercased())
                .font(.system(size: 9, weight: .bold))
                .tracking(0.7)
                .foregroundStyle(.white.opacity(0.5))
            Text(value)
                .font(.subheadline.weight(.semibold))
                .foregroundStyle(.white)
                .lineLimit(1)
                .minimumScaleFactor(0.72)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.horizontal, 12)
        .padding(.vertical, 10)
        .background(.white.opacity(0.07), in: RoundedRectangle(cornerRadius: 12))
    }
}

private struct WarningStrip: View {
    let warnings: [CapacityWarning]

    private var important: [CapacityWarning] {
        warnings.filter { $0.severity == "critical" || $0.severity == "warning" }
    }

    var body: some View {
        if !important.isEmpty {
            VStack(alignment: .leading, spacing: 9) {
                SectionHeading(
                    title: "Attention",
                    detail: "\(important.count) warning\(important.count == 1 ? "" : "s")"
                )
                ForEach(important.prefix(3)) { warning in
                    HStack(alignment: .top, spacing: 10) {
                        Image(systemName: warning.severity == "critical" ? "exclamationmark.octagon.fill" : "exclamationmark.triangle.fill")
                            .foregroundStyle(warning.severity == "critical" ? .red : .orange)
                        VStack(alignment: .leading, spacing: 2) {
                            if let label = warning.accountLabel {
                                Text(label)
                                    .font(.caption.weight(.semibold))
                            }
                            Text(warning.message ?? "Broker warning")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                    }
                }
            }
            .padding(15)
            .background(Color(uiColor: .secondarySystemGroupedBackground), in: RoundedRectangle(cornerRadius: 16))
        }
    }
}

private struct AccountCapacityCard: View {
    let account: CodexAccount

    private var tint: Color {
        switch account.status {
        case "available": .green
        case "auth_invalid": .red
        case "five_hour_limited", "weekly_limited": .orange
        case "disabled": .gray
        default: .yellow
        }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack(alignment: .top, spacing: 11) {
                Image(systemName: CapacityFormatting.statusSymbol(account.status))
                    .font(.title3)
                    .foregroundStyle(tint)
                    .frame(width: 26)

                VStack(alignment: .leading, spacing: 3) {
                    HStack(spacing: 7) {
                        Text(account.label)
                            .font(.headline)
                            .lineLimit(1)
                        if account.routingPreferred {
                            Text("PREFERRED")
                                .font(.system(size: 8, weight: .bold))
                                .tracking(0.5)
                                .padding(.horizontal, 6)
                                .padding(.vertical, 3)
                                .background(.cyan.opacity(0.12), in: Capsule())
                                .foregroundStyle(.cyan)
                        }
                    }
                    Text(CapacityFormatting.statusTitle(account.status))
                        .font(.subheadline.weight(.semibold))
                        .foregroundStyle(tint)
                    Text(account.statusReason)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                Spacer(minLength: 4)
                Text(account.planType?.uppercased() ?? "")
                    .font(.caption2.weight(.bold))
                    .foregroundStyle(.tertiary)
            }

            VStack(spacing: 10) {
                CapacityWindowRow(title: "5-hour", window: account.fiveHour, tint: tint)
                CapacityWindowRow(title: "Weekly", window: account.weekly, tint: .blue)
            }

            if account.stale || account.probeError != nil {
                Label(
                    account.probeError == nil ? "Broker state is stale" : "Freshness probe failed",
                    systemImage: "clock.badge.exclamationmark"
                )
                .font(.caption.weight(.medium))
                .foregroundStyle(.orange)
            }
        }
        .padding(16)
        .background(Color(uiColor: .secondarySystemGroupedBackground), in: RoundedRectangle(cornerRadius: 18, style: .continuous))
        .overlay(alignment: .leading) {
            RoundedRectangle(cornerRadius: 2)
                .fill(tint)
                .frame(width: 3)
                .padding(.vertical, 14)
        }
        .accessibilityElement(children: .combine)
    }
}

private struct CapacityWindowRow: View {
    let title: String
    let window: UsageWindow
    let tint: Color

    private var progress: Double {
        min(max((window.remainingPercent ?? 0) / 100, 0), 1)
    }

    var body: some View {
        VStack(spacing: 6) {
            HStack {
                Text(title)
                    .font(.caption.weight(.semibold))
                Spacer()
                Text(CapacityFormatting.percent(window.remainingPercent))
                    .font(.caption.weight(.bold))
                    .monospacedDigit()
                Text("·")
                    .foregroundStyle(.tertiary)
                Text(CapacityFormatting.relative(window.resetAt))
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            ProgressView(value: progress)
                .tint(window.reported ? tint : .gray)
        }
        .opacity(window.reported ? 1 : 0.62)
    }
}

private struct ServiceMessageCard: View {
    let symbol: String
    let title: String
    let message: String
    let tint: Color

    var body: some View {
        HStack(alignment: .top, spacing: 11) {
            Image(systemName: symbol)
                .foregroundStyle(tint)
            VStack(alignment: .leading, spacing: 2) {
                Text(title)
                    .font(.subheadline.weight(.semibold))
                Text(message)
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            Spacer()
        }
        .padding(13)
        .background(tint.opacity(0.09), in: RoundedRectangle(cornerRadius: 14))
    }
}

private struct SectionHeading: View {
    let title: String
    let detail: String

    var body: some View {
        HStack(alignment: .firstTextBaseline) {
            Text(title)
                .font(.title3.bold())
            Spacer()
            Text(detail)
                .font(.caption)
                .foregroundStyle(.secondary)
        }
    }
}

private struct EmptyCapacityState: View {
    let message: String?
    let isLoading: Bool

    var body: some View {
        ContentUnavailableView {
            Label(
                isLoading ? "Verifying this iPhone" : "Live status unavailable",
                systemImage: isLoading ? "checkmark.shield" : "wifi.exclamationmark"
            )
        } description: {
            Text(message ?? "Establishing a hardware-backed connection to the capacity service.")
        }
        .frame(minHeight: 430)
    }
}

private struct PrivacyFooter: View {
    var body: some View {
        VStack(spacing: 6) {
            Label("Read-only · Verified by App Attest", systemImage: "lock.shield.fill")
                .font(.caption.weight(.semibold))
            Text("Only redacted capacity and account-state fields are cached for the Watch and widgets.")
                .font(.caption2)
                .multilineTextAlignment(.center)
        }
        .foregroundStyle(.secondary)
        .padding(.top, 4)
        .padding(.horizontal, 24)
    }
}

#Preview {
    CapacityDashboardView()
        .environmentObject(SnapshotStore(fixtureMode: true))
}
