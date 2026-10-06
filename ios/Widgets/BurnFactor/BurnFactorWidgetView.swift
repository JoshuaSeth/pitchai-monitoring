import SwiftUI
import WidgetKit

internal struct BurnFactorWidgetView: View {
    @Environment(\.widgetFamily)
    private var family: WidgetFamily

    internal let entry: BurnFactorEntry
    internal let choice: BurnFactorPoolChoice

    internal var body: some View {
        if let pool = entry.burnFactors?.pool(choice.rawValue) {
            content(for: pool)
        } else {
            Label("Open iPhone app", systemImage: "iphone")
                .font(.caption)
        }
    }

    @ViewBuilder
    private func content(for pool: BurnFactorPool) -> some View {
        switch family {
        case .accessoryInline:
            inline(for: pool)

        case .accessoryRectangular:
            BurnFactorRectangularView(title: choice.displayName, pool: pool, isStale: entry.isStale)

        default:
            roundFamily(for: pool)
        }
    }

    @ViewBuilder
    private func roundFamily(for pool: BurnFactorPool) -> some View {
        #if os(watchOS)
            if family == .accessoryCorner {
                corner(for: pool)
            } else {
                circular(for: pool)
            }
        #else
            circular(for: pool)
        #endif
    }

    private func circular(for pool: BurnFactorPool) -> some View {
        Gauge(
            value: BurnFactorFormatting.gaugeValue(pool.longTerm),
            in: 0...BurnFactorFormatting.gaugeMaximum
        ) {
            Text(choice.shortLabel)
        } currentValueLabel: {
            Text(BurnFactorFormatting.compactFactor(pool.longTerm))
                .monospacedDigit()
        }
        .gaugeStyle(.accessoryCircular)
        .tint(BurnFactorFormatting.gaugeGradient)
    }

    #if os(watchOS)
        private func corner(for pool: BurnFactorPool) -> some View {
            Text(BurnFactorFormatting.compactFactor(pool.longTerm))
                .font(.title3.bold())
                .monospacedDigit()
                .widgetCurvesContent()
                .widgetLabel {
                    Gauge(
                        value: BurnFactorFormatting.gaugeValue(pool.longTerm),
                        in: 0...BurnFactorFormatting.gaugeMaximum
                    ) {
                        Text(choice.shortLabel)
                    } currentValueLabel: {
                        Text(BurnFactorFormatting.compactFactor(pool.longTerm))
                    } minimumValueLabel: {
                        Text(choice.shortLabel)
                    } maximumValueLabel: {
                        Text("2")
                    }
                    .tint(BurnFactorFormatting.gaugeGradient)
                }
        }
    #endif

    private func inline(for pool: BurnFactorPool) -> some View {
        let status: String = pool.longTerm?.status ?? ""
        let factor: String = BurnFactorFormatting.compactFactor(pool.longTerm)
        return Label(
            "\(choice.displayName) \(factor) · 6d",
            systemImage: BurnFactorFormatting.statusSymbol(status)
        )
    }
}
