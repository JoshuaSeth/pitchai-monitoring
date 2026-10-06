import SwiftUI
import WidgetKit

internal struct ClaudeBurnFactorWidget: Widget {
    internal var body: some WidgetConfiguration {
        BurnFactorWidgetConfiguration.pool(.claude)
    }
}
