import Foundation

internal struct AttestationRequest: Encodable {
    internal enum CodingKeys: String, CodingKey {
        case attestation = "attestation"
        case challengeID = "challenge_id"
        case keyID = "key_id"
    }

    internal let challengeID: String
    internal let keyID: String
    internal let attestation: String
}
