import Foundation

internal struct APIErrorEnvelope: Decodable {
    internal struct Detail: Decodable {
        internal let code: String?
        internal let message: String?
    }

    internal let detail: Detail
}
