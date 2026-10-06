import SwiftUI

internal struct BurnFactorRectangularView: View {
    internal enum Style {
        internal static let spacing: CGFloat = 1
        internal static let rowSpacing: CGFloat = 4
        internal static let spacerMinimum: CGFloat = 2
    }

    internal let title: String
    internal let pool: BurnFactorPool
    internal let isStale: Bool

    internal var body: some View {
        VStack(alignment: .leading, spacing: Style.spacing) {
            header
            factorRow
            Text(footnote)
                .font(.caption2)
                .foregroundStyle(.secondary)
                .lineLimit(1)
        }
    }

    private var header: some View {
        HStack(spacing: Style.rowSpacing) {
            Image(systemName: BurnFactorFormatting.statusSymbol(status))
                .foregroundStyle(tint)
            Text(title)
                .font(.headline)
                .lineLimit(1)
            Spacer(minLength: Style.spacerMinimum)
            Text(BurnFactorFormatting.statusTitle(status))
                .font(.caption2.weight(.semibold))
                .foregroundStyle(tint)
        }
    }

    private var factorRow: some View {
        HStack(alignment: .firstTextBaseline, spacing: Style.rowSpacing) {
            Text(BurnFactorFormatting.factor(pool.longTerm))
                .font(.title3.bold())
                .monospacedDigit()
            Text("24h → 6d")
                .font(.caption2)
                .foregroundStyle(.secondary)
        }
    }

    private var status: String {
        pool.longTerm?.status ?? "unknown"
    }

    private var tint: Color {
        BurnFactorFormatting.tint(status)
    }

    private var footnote: String {
        if isStale {
            return "Stale · open the iPhone app"
        }
        let shortTerm: String = BurnFactorFormatting.compactFactor(pool.shortTerm)
        let outlook: String = BurnFactorFormatting.outlook(pool.longTerm, money: pool.isMoney)
        return "30m→24h \(shortTerm) · " + outlook
    }
}
