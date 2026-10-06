import Foundation

internal struct BurnFactorSet: Codable, Equatable, Sendable {
    internal enum CodingKeys: String, CodingKey {
        case generatedAt = "generated_at"
        case pools = "pools"
        case schemaVersion = "schema_version"
    }

    internal let schemaVersion: Int
    internal let generatedAt: String
    internal let pools: [BurnFactorPool]

    internal var generatedDate: Date? {
        ServerDateParser.parse(generatedAt)
    }

    internal func pool(_ key: String) -> BurnFactorPool? {
        pools.first { pool in
            pool.key == key
        }
    }
}
