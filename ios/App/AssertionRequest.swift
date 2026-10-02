import Foundation

internal struct AssertionRequest: Encodable {
    internal enum CodingKeys: String, CodingKey {
        case assertion = "assertion"
        case challengeID = "challenge_id"
        case keyID = "key_id"
    }

    internal let challengeID: String
    internal let keyID: String
    internal let assertion: String
}
