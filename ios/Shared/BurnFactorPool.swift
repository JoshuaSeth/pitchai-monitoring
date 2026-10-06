import Foundation

internal struct BurnFactorPool: Codable, Equatable, Identifiable, Sendable {
    internal enum CodingKeys: String, CodingKey {
        case balanceUSD = "balance_usd"
        case key = "key"
        case label = "label"
        case results = "results"
        case unit = "unit"
    }

    internal static let longTermHorizon: String = "6d"
    internal static let shortTermHorizon: String = "24h"
    internal static let moneyUnit: String = "usd"

    internal let key: String
    internal let label: String
    internal let unit: String
    internal let balanceUSD: Double?
    internal let results: [BurnFactorResult]

    internal var id: String {
        key
    }

    internal var isMoney: Bool {
        unit == Self.moneyUnit
    }

    /// The 30-minute burn measured against the next 24 hours.
    internal var shortTerm: BurnFactorResult? {
        result(horizon: Self.shortTermHorizon)
    }

    /// The 24-hour burn measured against the next 6 days.
    internal var longTerm: BurnFactorResult? {
        result(horizon: Self.longTermHorizon)
    }

    internal func result(horizon: String) -> BurnFactorResult? {
        results.first { result in
            result.horizon == horizon
        }
    }
}
