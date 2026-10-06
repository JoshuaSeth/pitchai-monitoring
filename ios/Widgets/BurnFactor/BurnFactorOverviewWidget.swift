import SwiftUI
import WidgetKit

internal struct BurnFactorOverviewWidget: Widget {
    internal let kind: String = "BurnFactor.overview"

    internal var body: some WidgetConfiguration {
        StaticConfiguration(kind: kind, provider: BurnFactorProvider()) { entry in
            BurnFactorOverviewView(entry: entry)
                .containerBackground(.fill.tertiary, for: .widget)
        }
        .configurationDisplayName("Burn factors")
        .description("Codex, Claude and OpenCode: 24 h of burn against the next 6 days.")
        .supportedFamilies(BurnFactorWidgetStyle.overviewFamilies)
    }
}
