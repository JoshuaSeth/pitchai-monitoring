import SwiftUI
import WidgetKit

@main
internal struct CodexStatusWatchWidgets: WidgetBundle {
    internal var body: some Widget {
        CodexStatusWatchWidget()
        CodexBurnFactorWidget()
        ClaudeBurnFactorWidget()
        OpenCodeBurnFactorWidget()
        BurnFactorOverviewWidget()
    }
}
