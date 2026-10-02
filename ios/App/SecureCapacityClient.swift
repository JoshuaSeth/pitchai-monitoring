import CryptoKit
@preconcurrency import DeviceCheck
import Foundation

internal actor SecureCapacityClient {
    private static let maximumResponseBytes: Int = 524_288
    private static let minimumSuccessStatus: Int = 200
    private static let maximumSuccessStatus: Int = 299
    private static let requestTimeoutSeconds: TimeInterval = 35
    private static let resourceTimeoutSeconds: TimeInterval = 45
    private static let successStatuses: ClosedRange<Int> =
        SecureCapacityClient.minimumSuccessStatus...SecureCapacityClient.maximumSuccessStatus
    private static let unverifiedMessage: String =
        "The installed app could not be verified by the capacity service."

    internal static let live: SecureCapacityClient = .init(
        baseURL: SecureCapacityClient.defaultBaseURL
    )

    private static var defaultBaseURL: URL {
        guard let url = URL(string: "https://codexusage.pitchai.net") else {
            preconditionFailure("The capacity service URL must stay a valid URL literal.")
        }
        return url
    }

    private let baseURL: URL
    private let session: URLSession
    internal let appAttest: DCAppAttestService
    private let keyDefaults: UserDefaults
    private let keyIdentifierDefaultsKey: String = "codex-status.app-attest-key-id.v1"

    internal init(baseURL: URL, keyDefaults: UserDefaults = .standard) {
        self.baseURL = baseURL
        self.keyDefaults = keyDefaults
        self.appAttest = DCAppAttestService.shared

        let configuration: URLSessionConfiguration = .ephemeral
        configuration.requestCachePolicy = .reloadIgnoringLocalAndRemoteCacheData
        configuration.httpCookieStorage = nil
        configuration.urlCredentialStorage = nil
        configuration.httpShouldSetCookies = false
        configuration.waitsForConnectivity = true
        configuration.timeoutIntervalForRequest = Self.requestTimeoutSeconds
        configuration.timeoutIntervalForResource = Self.resourceTimeoutSeconds
        self.session = URLSession(configuration: configuration)
    }

    private static func failureMessage(from data: Data) -> String {
        do {
            let envelope: APIErrorEnvelope = try JSONDecoder().decode(
                APIErrorEnvelope.self,
                from: data
            )
            return envelope.detail.message ?? Self.unverifiedMessage
        } catch {
            return Self.unverifiedMessage
        }
    }

    internal func fetchCapacity() async throws -> CodexSnapshot {
        try await performAssertionRequest(
            purpose: "capacity",
            path: "/api/v1/mobile/capacity",
            response: CodexSnapshot.self
        )
    }

    internal func requestManualRefresh() async throws -> RefreshResponse {
        try await performAssertionRequest(
            purpose: "refresh",
            path: "/api/v1/mobile/refresh",
            response: RefreshResponse.self
        )
    }

    private func performAssertionRequest<Response: Decodable>(
        purpose: String,
        path: String,
        response: Response.Type
    ) async throws -> Response {
        let keyID: String = try await registeredKeyID()
        let challenge: ChallengeResponse = try await requestChallenge(
            purpose: purpose,
            keyID: keyID
        )
        let clientData: Data = try Self.canonicalClientData(
            purpose: purpose,
            challengeID: challenge.challengeID,
            challenge: challenge.challenge,
            keyID: keyID
        )
        let assertion: Data = try await generateAssertion(
            keyID: keyID,
            clientDataHash: Data(SHA256.hash(data: clientData))
        )
        let body: AssertionRequest = .init(
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
        let existing: String? = keyDefaults.string(forKey: keyIdentifierDefaultsKey)
        if let existing, !existing.isEmpty {
            return existing
        }

        let keyID: String = try await generateKey()
        let challenge: ChallengeResponse = try await requestChallenge(
            purpose: "attest",
            keyID: keyID
        )
        guard let challengeData: Data = .init(base64Encoded: challenge.challenge) else {
            throw CapacityClientError.challengeInvalid
        }
        let attestation: Data = try await attestKey(
            keyID: keyID,
            clientDataHash: Data(SHA256.hash(data: challengeData))
        )
        let body: AttestationRequest = .init(
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

    private func requestChallenge(
        purpose: String,
        keyID: String
    ) async throws -> ChallengeResponse {
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
        var request: URLRequest = .init(url: baseURL.appending(path: path))
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        let encoder: JSONEncoder = .init()
        encoder.outputFormatting = [.sortedKeys, .withoutEscapingSlashes]
        request.httpBody = try encoder.encode(body)

        let (data, rawResponse): (Data, URLResponse) = try await session.data(for: request)
        guard let httpResponse = rawResponse as? HTTPURLResponse else {
            throw CapacityClientError.invalidServerResponse
        }
        guard data.count <= Self.maximumResponseBytes else {
            throw CapacityClientError.invalidServerResponse
        }
        guard Self.successStatuses.contains(httpResponse.statusCode) else {
            let rejection: ServerRejection = .init(
                status: httpResponse.statusCode,
                message: Self.failureMessage(from: data)
            )
            throw CapacityClientError.serverRejected(rejection)
        }
        do {
            return try JSONDecoder().decode(response, from: data)
        } catch {
            throw CapacityClientError.invalidServerResponse
        }
    }
}
