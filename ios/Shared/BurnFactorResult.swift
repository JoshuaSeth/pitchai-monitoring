import Foundation

internal struct BurnFactorResult: Codable, Equatable, Sendable {
    internal enum CodingKeys: String, CodingKey {
        case available = "available"
        case blockedUntil = "blocked_until"
        case burnPerHour = "burn_per_hour"
        case demand = "demand"
        case factor = "factor"
        case horizon = "horizon"
        case lowerBound = "lower_bound"
        case margin = "margin"
        case rolling = "rolling"
        case runwayHours = "runway_hours"
        case status = "status"
    }

    internal let rolling: String?
    internal let horizon: String?
    internal let factor: Double?
    internal let status: String
    internal let lowerBound: Bool
    internal let runwayHours: Double?
    internal let burnPerHour: Double?
    internal let demand: Double?
    internal let available: Double?
    internal let margin: Double?
    internal let blockedUntil: String?
}
