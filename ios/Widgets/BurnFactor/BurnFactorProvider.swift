import Foundation
import WidgetKit

internal struct BurnFactorProvider: TimelineProvider {
    internal static let refreshInterval: TimeInterval = 900

    internal func placeholder(in _: Context) -> BurnFactorEntry {
        BurnFactorEntry(date: Date(), burnFactors: .fixture)
    }

    internal func getSnapshot(
        in context: Context,
        completion: @escaping (BurnFactorEntry) -> Void
    ) {
        let cached: BurnFactorSet? = SnapshotCache.load()?.burnFactors
        let shown: BurnFactorSet? = context.isPreview ? cached ?? .fixture : cached
        completion(BurnFactorEntry(date: Date(), burnFactors: shown))
    }

    internal func getTimeline(
        in _: Context,
        completion: @escaping (Timeline<BurnFactorEntry>) -> Void
    ) {
        let entry: BurnFactorEntry = .init(
            date: Date(),
            burnFactors: SnapshotCache.load()?.burnFactors
        )
        let refresh: Date = .init(timeIntervalSinceNow: Self.refreshInterval)
        completion(Timeline(entries: [entry], policy: .after(refresh)))
    }
}
