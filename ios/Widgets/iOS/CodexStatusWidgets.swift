import SwiftUI
import WidgetKit

@main
internal struct CodexStatusWidgets: WidgetBundle {
    internal var body: some Widget {
        CodexStatusWidget()
        CodexBurnFactorWidget()
        ClaudeBurnFactorWidget()
        OpenCodeBurnFactorWidget()
        BurnFactorOverviewWidget()
    }
}
