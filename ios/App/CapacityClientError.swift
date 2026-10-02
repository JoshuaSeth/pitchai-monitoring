import Foundation

internal struct ServerRejection: Equatable, Sendable {
    internal let status: Int
    internal let message: String
}

internal enum CapacityClientError: LocalizedError {
    case appAttestUnavailable
    case challengeInvalid
    case invalidServerResponse
    case serverRejected(ServerRejection)

    internal var errorDescription: String? {
        switch self {
        case .appAttestUnavailable:
            return "App Attest is unavailable on this device. Live broker data remains locked."

        case .challengeInvalid:
            return "The one-time server challenge was invalid."

        case .invalidServerResponse:
            return "The capacity service returned an invalid response."

        case .serverRejected(let rejection):
            return "\(rejection.message) (HTTP \(rejection.status))"
        }
    }
}
