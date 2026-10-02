import SwiftUI

internal struct AccountCapacityCard: View {
    internal enum Style {
        internal static let stackSpacing: CGFloat = 14
        internal static let rowSpacing: CGFloat = 11
        internal static let textSpacing: CGFloat = 3
        internal static let badgeSpacing: CGFloat = 7
        internal static let badgeFontSize: CGFloat = 8
        internal static let badgeTracking: CGFloat = 0.5
        internal static let badgeHorizontalPadding: CGFloat = 6
        internal static let badgeVerticalPadding: CGFloat = 3
        internal static let badgeFillOpacity: Double = 0.12
        internal static let windowSpacing: CGFloat = 10
        internal static let padding: CGFloat = 16
        internal static let cornerRadius: CGFloat = 18
        internal static let accentCornerRadius: CGFloat = 2
        internal static let accentWidth: CGFloat = 3
        internal static let accentVerticalPadding: CGFloat = 14
        internal static let symbolWidth: CGFloat = 26
        internal static let spacerMinimum: CGFloat = 4
    }

    internal let account: CodexAccount

    internal var body: some View {
        VStack(alignment: .leading, spacing: Style.stackSpacing) {
            header
            windows
            if account.stale || account.probeError != nil {
                freshnessLabel
            }
        }
        .padding(Style.padding)
        .background(
            Color(uiColor: .secondarySystemGroupedBackground),
            in: RoundedRectangle(cornerRadius: Style.cornerRadius, style: .continuous)
        )
        .overlay(alignment: .leading) {
            RoundedRectangle(cornerRadius: Style.accentCornerRadius)
                .fill(tint)
                .frame(width: Style.accentWidth)
                .padding(.vertical, Style.accentVerticalPadding)
        }
        .accessibilityElement(children: .combine)
    }

    private var tint: Color {
        switch account.status {
        case "available":
            return .green

        case "auth_invalid":
            return .red

        case "five_hour_limited", "weekly_limited":
            return .orange

        case "disabled":
            return .gray

        default:
            return .yellow
        }
    }

    private var header: some View {
        HStack(alignment: .top, spacing: Style.rowSpacing) {
            Image(systemName: CapacityFormatting.statusSymbol(account.status))
                .font(.title3)
                .foregroundStyle(tint)
                .frame(width: Style.symbolWidth)
            summary
            Spacer(minLength: Style.spacerMinimum)
            Text(account.planType?.uppercased() ?? "")
                .font(.caption2.weight(.bold))
                .foregroundStyle(.tertiary)
        }
    }

    private var summary: some View {
        VStack(alignment: .leading, spacing: Style.textSpacing) {
            HStack(spacing: Style.badgeSpacing) {
                Text(account.label)
                    .font(.headline)
                    .lineLimit(1)
                if account.routingPreferred {
                    preferredBadge
                }
            }
            Text(CapacityFormatting.statusTitle(account.status))
                .font(.subheadline.weight(.semibold))
                .foregroundStyle(tint)
            Text(account.statusReason)
                .font(.caption)
                .foregroundStyle(.secondary)
        }
    }

    private var preferredBadge: some View {
        Text("PREFERRED")
            .font(.system(size: Style.badgeFontSize, weight: .bold))
            .tracking(Style.badgeTracking)
            .padding(.horizontal, Style.badgeHorizontalPadding)
            .padding(.vertical, Style.badgeVerticalPadding)
            .background(.cyan.opacity(Style.badgeFillOpacity), in: Capsule())
            .foregroundStyle(.cyan)
    }

    private var windows: some View {
        VStack(spacing: Style.windowSpacing) {
            CapacityWindowRow(title: "5-hour", window: account.fiveHour, tint: tint)
            CapacityWindowRow(title: "Weekly", window: account.weekly, tint: .blue)
        }
    }

    private var freshnessLabel: some View {
        Label(freshnessDescription, systemImage: "clock.badge.exclamationmark")
            .font(.caption.weight(.medium))
            .foregroundStyle(.orange)
    }

    private var freshnessDescription: String {
        account.probeError == nil ? "Broker state is stale" : "Freshness probe failed"
    }
}
