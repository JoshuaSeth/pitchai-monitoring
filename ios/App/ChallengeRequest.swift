import Foundation

internal struct ChallengeRequest: Encodable {
    internal enum CodingKeys: String, CodingKey {
        case keyID = "key_id"
        case purpose = "purpose"
    }

    internal let purpose: String
    internal let keyID: String
}
