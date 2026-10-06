import SwiftUI

internal struct BurnFactorOverviewView: View {
    internal enum Style {
        internal static let spacing: CGFloat = 1
        internal static let rowSpacing: CGFloat = 4
        internal static let spacerMinimum: CGFloat = 2
    }

    internal let entry: BurnFactorEntry

    internal var body: some View {
        if let burnFactors = entry.burnFactors {
            VStack(alignment: .leading, spacing: Style.spacing) {
                Text(entry.isStale ? "Burn 24h → 6d · stale" : "Burn 24h → 6d")
                    .font(.caption2.weight(.semibold))
                    .foregroundStyle(.secondary)
                ForEach(BurnFactorPoolChoice.displayOrder, id: \.self) { choice in
                    row(for: choice, pool: burnFactors.pool(choice.rawValue))
                }
            }
        } else {
            Label("Open iPhone app", systemImage: "iphone")
                .font(.caption)
        }
    }

    private func row(for choice: BurnFactorPoolChoice, pool: BurnFactorPool?) -> some View {
        let status: String = pool?.longTerm?.status ?? "unknown"
        return HStack(spacing: Style.rowSpacing) {
            Image(systemName: BurnFactorFormatting.statusSymbol(status))
                .foregroundStyle(BurnFactorFormatting.tint(status))
            Text(choice.displayName)
                .font(.caption)
                .lineLimit(1)
            Spacer(minLength: Style.spacerMinimum)
            Text(BurnFactorFormatting.compactFactor(pool?.longTerm))
                .font(.caption.bold())
                .monospacedDigit()
        }
    }
}
