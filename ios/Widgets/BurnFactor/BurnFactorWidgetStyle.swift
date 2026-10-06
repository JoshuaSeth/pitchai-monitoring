import WidgetKit

internal enum BurnFactorWidgetStyle {
    /// Round gauge, corner arc, card and inline text; the corner exists only on watchOS.
    internal static var poolFamilies: [WidgetFamily] {
        var families: [WidgetFamily] = []
        families.append(.accessoryCircular)
        families.append(.accessoryRectangular)
        families.append(.accessoryInline)
        #if os(watchOS)
            families.append(.accessoryCorner)
        #endif
        return families
    }

    internal static var overviewFamilies: [WidgetFamily] {
        var families: [WidgetFamily] = []
        families.append(.accessoryRectangular)
        return families
    }
}
