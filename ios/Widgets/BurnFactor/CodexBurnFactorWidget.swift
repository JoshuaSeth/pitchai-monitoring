import SwiftUI
import WidgetKit

internal struct CodexBurnFactorWidget: Widget {
    internal var body: some WidgetConfiguration {
        BurnFactorWidgetConfiguration.pool(.codex)
    }
}
