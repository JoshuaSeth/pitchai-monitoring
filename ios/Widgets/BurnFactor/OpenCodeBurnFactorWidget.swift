import SwiftUI
import WidgetKit

internal struct OpenCodeBurnFactorWidget: Widget {
    internal var body: some WidgetConfiguration {
        BurnFactorWidgetConfiguration.pool(.openCode)
    }
}
