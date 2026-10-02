import DeviceCheck
import Foundation

extension SecureCapacityClient {
    internal func generateKey() async throws -> String {
        try await withCheckedThrowingContinuation { continuation in
            appAttest.generateKey { keyID, error in
                if let keyID {
                    continuation.resume(returning: keyID)
                } else {
                    continuation.resume(throwing: error ?? CapacityClientError.appAttestUnavailable)
                }
            }
        }
    }

    internal func attestKey(keyID: String, clientDataHash: Data) async throws -> Data {
        try await withCheckedThrowingContinuation { continuation in
            appAttest.attestKey(keyID, clientDataHash: clientDataHash) { attestation, error in
                if let attestation {
                    continuation.resume(returning: attestation)
                } else {
                    continuation.resume(
                        throwing: error ?? CapacityClientError.invalidServerResponse
                    )
                }
            }
        }
    }

    internal func generateAssertion(keyID: String, clientDataHash: Data) async throws -> Data {
        try await withCheckedThrowingContinuation { continuation in
            appAttest.generateAssertion(keyID, clientDataHash: clientDataHash) { assertion, error in
                if let assertion {
                    continuation.resume(returning: assertion)
                } else {
                    continuation.resume(
                        throwing: error ?? CapacityClientError.invalidServerResponse
                    )
                }
            }
        }
    }
}
