import Foundation
import WatchConnectivity

extension WatchSnapshotStore {
    nonisolated internal func session(
        _ session: WCSession,
        activationDidCompleteWith _: WCSessionActivationState,
        error: Error?
    ) {
        guard error == nil else {
            Task { @MainActor [weak self] in
                self?.reportConnectionFailure()
            }
            return
        }
        let payload: Data? = Self.snapshotPayload(in: session.receivedApplicationContext)
        Task { @MainActor [weak self] in
            self?.apply(snapshotData: payload)
            self?.requestLatestSnapshot()
        }
    }

    nonisolated internal func sessionReachabilityDidChange(_ session: WCSession) {
        guard session.isReachable else {
            return
        }
        Task { @MainActor [weak self] in
            self?.requestLatestSnapshot()
        }
    }

    nonisolated internal func session(
        _: WCSession,
        didReceiveApplicationContext applicationContext: [String: Any]
    ) {
        let payload: Data? = Self.snapshotPayload(in: applicationContext)
        Task { @MainActor [weak self] in
            self?.apply(snapshotData: payload)
        }
    }

    nonisolated internal func session(
        _: WCSession,
        didReceiveUserInfo userInfo: [String: Any] = [:]
    ) {
        let payload: Data? = Self.snapshotPayload(in: userInfo)
        Task { @MainActor [weak self] in
            self?.apply(snapshotData: payload)
        }
    }
}
