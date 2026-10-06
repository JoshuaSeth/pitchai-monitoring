import Foundation
import WidgetKit

internal struct BurnFactorEntry: TimelineEntry {
    internal static let staleAfterSeconds: TimeInterval = 3_600

    internal let date: Date
    internal let burnFactors: BurnFactorSet?

    internal var isStale: Bool {
        guard let generated = burnFactors?.generatedDate else {
            return true
        }
        return date.timeIntervalSince(generated) > Self.staleAfterSeconds
    }
}
