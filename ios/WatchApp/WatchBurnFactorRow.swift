import SwiftUI

internal struct WatchBurnFactorRow: View {
    internal enum Style {
        internal static let stackSpacing: CGFloat = 5
        internal static let rowSpacing: CGFloat = 6
        internal static let padding: CGFloat = 9
        internal static let cornerRadius: CGFloat = 11
        internal static let fillOpacity: Double = 0.55
        internal static let detailFontSize: CGFloat = 9
        internal static let spacerMinimum: CGFloat = 2
        internal static let detailLineLimit: Int = 2
    }

    internal let pool: BurnFactorPool

    internal var body: some View {
        VStack(alignment: .leading, spacing: Style.stackSpacing) {
            summary
            ProgressView(
                value: BurnFactorFormatting.gaugeValue(pool.longTerm),
                total: BurnFactorFormatting.gaugeMaximum
            )
            .tint(tint)
            Text(detail)
                .font(.system(size: Style.detailFontSize))
                .foregroundStyle(.secondary)
                .lineLimit(Style.detailLineLimit)
        }
        .padding(Style.padding)
        .background(
            .quaternary.opacity(Style.fillOpacity),
            in: RoundedRectangle(cornerRadius: Style.cornerRadius)
        )
        .accessibilityElement(children: .combine)
    }

    private var status: String {
        pool.longTerm?.status ?? "unknown"
    }

    private var tint: Color {
        BurnFactorFormatting.tint(status)
    }

    private var summary: some View {
        HStack(spacing: Style.rowSpacing) {
            Image(systemName: BurnFactorFormatting.statusSymbol(status))
                .foregroundStyle(tint)
            Text(pool.label)
                .font(.caption.bold())
                .lineLimit(1)
            Spacer(minLength: Style.spacerMinimum)
            Text(BurnFactorFormatting.factor(pool.longTerm))
                .font(.caption.bold())
                .monospacedDigit()
                .foregroundStyle(tint)
        }
    }

    private var detail: String {
        let shortTerm: String = BurnFactorFormatting.factor(pool.shortTerm)
        let outlook: String = BurnFactorFormatting.outlook(pool.longTerm, money: pool.isMoney)
        return "30m→24h \(shortTerm) · " + outlook
    }
}
