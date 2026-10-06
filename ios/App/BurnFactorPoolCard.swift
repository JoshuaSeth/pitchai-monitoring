import SwiftUI

internal struct BurnFactorPoolCard: View {
    internal enum Style {
        internal static let stackSpacing: CGFloat = 12
        internal static let tileSpacing: CGFloat = 10
        internal static let padding: CGFloat = 16
        internal static let cornerRadius: CGFloat = 18
        internal static let accentCornerRadius: CGFloat = 2
        internal static let accentWidth: CGFloat = 3
        internal static let accentVerticalPadding: CGFloat = 14
    }

    internal let pool: BurnFactorPool

    internal var body: some View {
        VStack(alignment: .leading, spacing: Style.stackSpacing) {
            header
            HStack(alignment: .top, spacing: Style.tileSpacing) {
                BurnFactorTile(title: "30 min → 24 h", result: pool.shortTerm, money: pool.isMoney)
                BurnFactorTile(title: "24 h → 6 days", result: pool.longTerm, money: pool.isMoney)
            }
        }
        .padding(Style.padding)
        .background(
            Color(uiColor: .secondarySystemGroupedBackground),
            in: RoundedRectangle(cornerRadius: Style.cornerRadius, style: .continuous)
        )
        .overlay(alignment: .leading) {
            RoundedRectangle(cornerRadius: Style.accentCornerRadius)
                .fill(BurnFactorFormatting.tint(pool.longTerm?.status ?? ""))
                .frame(width: Style.accentWidth)
                .padding(.vertical, Style.accentVerticalPadding)
        }
    }

    private var header: some View {
        HStack(alignment: .firstTextBaseline) {
            Text(pool.label)
                .font(.headline)
            Spacer()
            Text(detail)
                .font(.caption)
                .foregroundStyle(.secondary)
        }
    }

    private var detail: String {
        if pool.isMoney {
            return "Balance " + BurnFactorFormatting.amount(pool.balanceUSD, money: true)
        }
        return "Weekly points"
    }
}
