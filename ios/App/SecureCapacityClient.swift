import CryptoKit
@preconcurrency import DeviceCheck
import Foundation

enum CapacityClientError: LocalizedError {
    case appAttestUnavailable
    case invalidServerResponse
    case serverRejected(status: Int, message: String)
    case challengeInvalid

    var errorDescription: String? {
        switch self {
        case .appAttestUnavailable:
            "App Attest is unavailable on this device. Live broker data remains locked."
        case .invalidServerResponse:
            "The capacity service returned an invalid response."
        case let .serverRejected(status, message):
            "\(message) (HTTP \(status))"
        case .challengeInvalid:
            "The one-time server challenge was invalid."
        }
    }
}

actor SecureCapacityClient {
    static let live = SecureCapacityClient(
        baseURL: URL(string: "https://codexusage.pitchai.net")!
    )

    private let baseURL: URL
    private let session: URLSession
    private let appAttest = DCAppAttestService.shared
    private let keyDefaults: UserDefaults
    private let keyIdentifierDefaultsKey = "codex-status.app-attest-key-id.v1"

    init(baseURL: URL, keyDefaults: UserDefaults = .standard) {
        self.baseURL = baseURL
        self.keyDefaults = keyDefaults

        let configuration = URLSessionConfiguration.ephemeral
        configuration.requestCachePolicy = .reloadIgnoringLocalAndRemoteCacheData
        configuration.httpCookieStorage = nil
        configuration.urlCredentialStorage = nil
        configuration.httpShouldSetCookies = false
        configuration.waitsForConnectivity = true
        configuration.timeoutIntervalForRequest = 35
        configuration.timeoutIntervalForResource = 45
        self.session = URLSession(configuration: configuration)
    }

    func fetchCapacity() async throws -> CodexSnapshot {
        try await performAssertionRequest(
            purpose: "capacity",
            path: "/api/v1/mobile/capacity",
            response: CodexSnapshot.self
        )
    }

    func requestManualRefresh() async throws -> RefreshResponse {
        try await performAssertionRequest(
            purpose: "refresh",
            path: "/api/v1/mobile/refresh",
            response: RefreshResponse.self
        )
    }

    static func canonicalClientData(
        purpose: String,
        challengeID: String,
        challenge: String,
        keyID: String
    ) throws -> Data {
        let value = [
            "pitchai-codex-status-v1",
            purpose,
            challengeID,
            challenge,
            keyID
        ].joined(separator: "\n")
        guard let data = value.data(using: .ascii) else {
            throw CapacityClientError.challengeInvalid
        }
        return data
    }

    private func performAssertionRequest<Response: Decodable>(
        purpose: String,
        path: String,
        response: Response.Type
    ) async throws -> Response {
        let keyID = try await registeredKeyID()
        let challenge = try await requestChallenge(purpose: purpose, keyID: keyID)
        let clientData = try Self.canonicalClientData(
            purpose: purpose,
            challengeID: challenge.challengeID,
            challenge: challenge.challenge,
            keyID: keyID
        )
        let assertion = try await generateAssertion(
            keyID: keyID,
            clientDataHash: Data(SHA256.hash(data: clientData))
        )
        let body = AssertionRequest(
            challengeID: challenge.challengeID,
            keyID: keyID,
            assertion: assertion.base64EncodedString()
        )
        return try await post(path: path, body: body, response: response)
    }

    private func registeredKeyID() async throws -> String {
        guard appAttest.isSupported else {
            throw CapacityClientError.appAttestUnavailable
        }
        if let existing = keyDefaults.string(forKey: keyIdentifierDefaultsKey),
           !existing.isEmpty {
            return existing
        }

        let keyID = try await generateKey()
        let challenge = try await requestChallenge(purpose: "attest", keyID: keyID)
        guard let challengeData = Data(base64Encoded: challenge.challenge) else {
            throw CapacityClientError.challengeInvalid
        }
        let attestation = try await attestKey(
            keyID: keyID,
            clientDataHash: Data(SHA256.hash(data: challengeData))
        )
        let body = AttestationRequest(
            challengeID: challenge.challengeID,
            keyID: keyID,
            attestation: attestation.base64EncodedString()
        )
        let response: AttestationResponse = try await post(
            path: "/api/v1/mobile/attest",
            body: body,
            response: AttestationResponse.self
        )
        guard response.registered else {
            throw CapacityClientError.invalidServerResponse
        }
        keyDefaults.set(keyID, forKey: keyIdentifierDefaultsKey)
        return keyID
    }

    private func requestChallenge(purpose: String, keyID: String) async throws -> ChallengeResponse {
        try await post(
            path: "/api/v1/mobile/challenge",
            body: ChallengeRequest(purpose: purpose, keyID: keyID),
            response: ChallengeResponse.self
        )
    }

    private func post<Body: Encodable, Response: Decodable>(
        path: String,
        body: Body,
        response: Response.Type
    ) async throws -> Response {
        let url = baseURL.appending(path: path)
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys, .withoutEscapingSlashes]
        request.httpBody = try encoder.encode(body)

        let (data, rawResponse) = try await session.data(for: request)
        guard let httpResponse = rawResponse as? HTTPURLResponse else {
            throw CapacityClientError.invalidServerResponse
        }
        guard data.count <= 512 * 1024 else {
            throw CapacityClientError.invalidServerResponse
        }
        guard (200 ... 299).contains(httpResponse.statusCode) else {
            let envelope = try? JSONDecoder().decode(APIErrorEnvelope.self, from: data)
            throw CapacityClientError.serverRejected(
                status: httpResponse.statusCode,
                message: envelope?.detail.message ?? "The installed app could not be verified by the capacity service."
            )
        }
        do {
            return try JSONDecoder().decode(response, from: data)
        } catch {
            throw CapacityClientError.invalidServerResponse
        }
    }

    private func generateKey() async throws -> String {
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

    private func attestKey(keyID: String, clientDataHash: Data) async throws -> Data {
        try await withCheckedThrowingContinuation { continuation in
            appAttest.attestKey(keyID, clientDataHash: clientDataHash) { attestation, error in
                if let attestation {
                    continuation.resume(returning: attestation)
                } else {
                    continuation.resume(throwing: error ?? CapacityClientError.invalidServerResponse)
                }
            }
        }
    }

    private func generateAssertion(keyID: String, clientDataHash: Data) async throws -> Data {
        try await withCheckedThrowingContinuation { continuation in
            appAttest.generateAssertion(keyID, clientDataHash: clientDataHash) { assertion, error in
                if let assertion {
                    continuation.resume(returning: assertion)
                } else {
                    continuation.resume(throwing: error ?? CapacityClientError.invalidServerResponse)
                }
            }
        }
    }
}

private struct ChallengeRequest: Encodable {
    let purpose: String
    let keyID: String

    enum CodingKeys: String, CodingKey {
        case purpose
        case keyID = "key_id"
    }
}

private struct ChallengeResponse: Decodable {
    let challengeID: String
    let challenge: String

    enum CodingKeys: String, CodingKey {
        case challengeID = "challenge_id"
        case challenge
    }
}

private struct AttestationRequest: Encodable {
    let challengeID: String
    let keyID: String
    let attestation: String

    enum CodingKeys: String, CodingKey {
        case challengeID = "challenge_id"
        case keyID = "key_id"
        case attestation
    }
}

private struct AttestationResponse: Decodable {
    let registered: Bool
}

private struct AssertionRequest: Encodable {
    let challengeID: String
    let keyID: String
    let assertion: String

    enum CodingKeys: String, CodingKey {
        case challengeID = "challenge_id"
        case keyID = "key_id"
        case assertion
    }
}

private struct APIErrorEnvelope: Decodable {
    let detail: APIErrorDetail
}

private struct APIErrorDetail: Decodable {
    let code: String?
    let message: String?
}
