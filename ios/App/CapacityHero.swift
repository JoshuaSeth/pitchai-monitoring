import SwiftUI

internal struct CapacityHero: View {
    internal enum Style {
        internal static let stackSpacing: CGFloat = 18
        internal static let rowSpacing: CGFloat = 16
        internal static let pillSpacing: CGFloat = 12
        internal static let padding: CGFloat = 20
        internal static let cornerRadius: CGFloat = 24
        internal static let edgeOpacity: Double = 0.08
        internal static let edgeWidth: CGFloat = 1
        internal static let topRed: Double = 0.07
        internal static let topGreen: Double = 0.22
        internal static let topBlue: Double = 0.31
        internal static let bottomRed: Double = 0.03
        internal static let bottomGreen: Double = 0.08
        internal static let bottomBlue: Double = 0.13
    }

    internal let snapshot: CodexSnapshot

    private var aggregate: WindowAggregate? {
        snapshot.selectedAggregate
    }

    private var percentage: Double {
        aggregate?.remainingPercent ?? 0
    }

    internal var body: some View {
        VStack(alignment: .leading, spacing: Style.stackSpacing) {
            HStack(alignment: .top, spacing: Style.rowSpacing) {
                CapacityGaugeRing(percentage: percentage)
                CapacityHeroSummary(snapshot: snapshot)
            }
            Divider()
                .overlay(.white.opacity(Style.edgeOpacity))
            metricPills
        }
        .padding(Style.padding)
        .background(
            background,
            in: RoundedRectangle(cornerRadius: Style.cornerRadius, style: .continuous)
        )
        .overlay {
            RoundedRectangle(cornerRadius: Style.cornerRadius, style: .continuous)
                .stroke(.white.opacity(Style.edgeOpacity), lineWidth: Style.edgeWidth)
        }
        .accessibilityElement(children: .combine)
        .accessibilityLabel(accessibilityDescription)
    }

    private var metricPills: some View {
        HStack(spacing: Style.pillSpacing) {
            MetricPill(
                title: snapshot.summary.capacityBasis.label ?? "Capacity",
                value: CapacityFormatting.points(aggregate?.remainingPoints) + " pts"
            )
            MetricPill(title: "Next recovery", value: recoveryDescription)
        }
    }

    private var recoveryDescription: String {
        CapacityFormatting.relative(snapshot.summary.nextUsefulCapacityAt)
            .replacingOccurrences(of: "Resets ", with: "")
    }

    private var background: LinearGradient {
        LinearGradient(
            colors: [topColor, bottomColor],
            startPoint: .topLeading,
            endPoint: .bottomTrailing
        )
    }

    private var topColor: Color {
        Color(red: Style.topRed, green: Style.topGreen, blue: Style.topBlue)
    }

    private var bottomColor: Color {
        Color(red: Style.bottomRed, green: Style.bottomGreen, blue: Style.bottomBlue)
    }

    private var accessibilityDescription: String {
        let readiness: String =
            "\(snapshot.summary.usableNow) of \(snapshot.summary.enabledAccounts) accounts ready. "
        let capacity: String = CapacityFormatting.percent(aggregate?.remainingPercent)
        return readiness + "\(capacity) capacity remaining."
    }
}
