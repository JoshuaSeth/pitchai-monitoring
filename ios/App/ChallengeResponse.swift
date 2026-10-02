import Foundation

internal struct ChallengeResponse: Decodable {
    internal enum CodingKeys: String, CodingKey {
        case challenge = "challenge"
        case challengeID = "challenge_id"
    }

    internal let challengeID: String
    internal let challenge: String
}
