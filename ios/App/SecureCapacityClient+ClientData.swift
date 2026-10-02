import Foundation

extension SecureCapacityClient {
    internal static func canonicalClientData(
        purpose: String,
        challengeID: String,
        challenge: String,
        keyID: String
    ) throws -> Data {
        let parts: [String] = ["pitchai-codex-status-v1", purpose, challengeID, challenge, keyID]
        let value: String = parts.joined(separator: "\n")
        guard let data: Data = value.data(using: .ascii) else {
            throw CapacityClientError.challengeInvalid
        }
        return data
    }
}
