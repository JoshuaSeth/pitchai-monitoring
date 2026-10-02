import SwiftUI

internal struct WatchAccountRow: View {
    internal enum Style {
        internal static let stackSpacing: CGFloat = 6
        internal static let rowSpacing: CGFloat = 6
        internal static let padding: CGFloat = 9
        internal static let cornerRadius: CGFloat = 11
        internal static let fillOpacity: Double = 0.55
        internal static let resetFontSize: CGFloat = 9
        internal static let spacerMinimum: CGFloat = 2
        internal static let fullPercent: Double = 100
    }

    internal let account: CodexAccount

    internal var body: some View {
        VStack(alignment: .leading, spacing: Style.stackSpacing) {
            summary
            ProgressView(value: progress)
                .tint(tint)
            Text(CapacityFormatting.relative(account.fiveHour.resetAt))
                .font(.system(size: Style.resetFontSize))
                .foregroundStyle(.secondary)
        }
        .padding(Style.padding)
        .background(
            .quaternary.opacity(Style.fillOpacity),
            in: RoundedRectangle(cornerRadius: Style.cornerRadius)
        )
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

        default:
            return .gray
        }
    }

    private var summary: some View {
        HStack(spacing: Style.rowSpacing) {
            Image(systemName: CapacityFormatting.statusSymbol(account.status))
                .foregroundStyle(tint)
            Text(account.label)
                .font(.caption.bold())
                .lineLimit(1)
            Spacer(minLength: Style.spacerMinimum)
            Text(CapacityFormatting.percent(account.fiveHour.remainingPercent))
                .font(.caption2.bold())
                .monospacedDigit()
        }
    }

    private var progress: Double {
        min(max((account.fiveHour.remainingPercent ?? 0) / Style.fullPercent, 0), 1)
    }
}
