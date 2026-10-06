import SwiftUI

internal struct BurnFactorTile: View {
    internal enum Style {
        internal static let spacing: CGFloat = 4
        internal static let padding: CGFloat = 10
        internal static let cornerRadius: CGFloat = 12
        internal static let fillOpacity: Double = 0.12
        internal static let factorFontSize: CGFloat = 28
        internal static let factorMinimumScale: CGFloat = 0.6
    }

    internal let title: String
    internal let result: BurnFactorResult?
    internal let money: Bool

    internal var body: some View {
        VStack(alignment: .leading, spacing: Style.spacing) {
            Text(title)
                .font(.caption2.weight(.semibold))
                .foregroundStyle(.secondary)
            factorText
            statusLabel
            Text(BurnFactorFormatting.outlook(result, money: money))
                .font(.caption2)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
            Text(needsSummary)
                .font(.caption2)
                .foregroundStyle(.tertiary)
                .fixedSize(horizontal: false, vertical: true)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(Style.padding)
        .background(
            tint.opacity(Style.fillOpacity),
            in: RoundedRectangle(cornerRadius: Style.cornerRadius, style: .continuous)
        )
        .accessibilityElement(children: .combine)
    }

    private var factorText: some View {
        Text(BurnFactorFormatting.factor(result))
            .font(.system(size: Style.factorFontSize, weight: .bold, design: .rounded))
            .monospacedDigit()
            .minimumScaleFactor(Style.factorMinimumScale)
            .lineLimit(1)
            .foregroundStyle(tint)
    }

    private var statusLabel: some View {
        Label(
            BurnFactorFormatting.statusTitle(status),
            systemImage: BurnFactorFormatting.statusSymbol(status)
        )
        .font(.caption.weight(.semibold))
        .foregroundStyle(tint)
    }

    private var status: String {
        result?.status ?? "unknown"
    }

    private var tint: Color {
        BurnFactorFormatting.tint(status)
    }

    private var needsSummary: String {
        let needed: String = BurnFactorFormatting.amount(result?.demand, money: money)
        let available: String = BurnFactorFormatting.amount(result?.available, money: money)
        return "Needs \(needed) · has \(available)"
    }
}
