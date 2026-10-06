import SwiftUI

internal struct BurnFactorSection: View {
    internal enum Style {
        internal static let sectionSpacing: CGFloat = 10
    }

    internal let burnFactors: BurnFactorSet

    internal var body: some View {
        VStack(alignment: .leading, spacing: Style.sectionSpacing) {
            SectionHeading(
                title: "Burn factor",
                detail: CapacityFormatting.updated(burnFactors.generatedDate)
            )
            ForEach(burnFactors.pools) { pool in
                BurnFactorPoolCard(pool: pool)
            }
            Text(
                "Burn over the rolling window × future window ÷ capacity in that window. "
                    + "Below 1 is margin; 1 or more runs short."
            )
            .font(.caption2)
            .foregroundStyle(.secondary)
        }
    }
}
