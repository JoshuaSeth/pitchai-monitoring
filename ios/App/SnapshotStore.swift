import BackgroundTasks
import Foundation
import SwiftUI
import WidgetKit

@MainActor
internal final class SnapshotStore: ObservableObject {
    internal enum LoadState: Equatable {
        case failed(String)
        case idle
        case loaded
        case loading
    }

    internal static let shared: SnapshotStore = .init()

    private static let minimumBackgroundIntervalSeconds: Int = 900
    private static let cacheFailureMessage: String =
        "Live capacity could not be refreshed. Cached values remain visible."

    @Published internal private(set) var snapshot: CodexSnapshot?
    @Published internal private(set) var state: LoadState = .idle
    @Published internal private(set) var refreshNotice: String?
    @Published internal private(set) var lastAttemptAt: Date?

    private let client: SecureCapacityClient
    private let fixtureMode: Bool
    private var foregroundRefreshTask: Task<Void, Never>?

    private var backgroundInterval: TimeInterval {
        let seconds: Int =
            snapshot?.refreshPolicy.recommendedBackgroundIntervalSeconds
            ?? Self.minimumBackgroundIntervalSeconds
        return TimeInterval(max(Self.minimumBackgroundIntervalSeconds, seconds))
    }

    internal init(
        client: SecureCapacityClient = .live,
        fixtureMode: Bool = ProcessInfo.processInfo.arguments.contains("-CodexStatusFixture")
    ) {
        self.client = client
        self.fixtureMode = fixtureMode
        self.snapshot = fixtureMode ? .fixture : SnapshotCache.load()
        self.state = self.snapshot == nil ? .idle : .loaded
    }

    private static func safeMessage(for error: Error) -> String {
        let description: String? = (error as? LocalizedError)?.errorDescription
        guard let description, !description.isEmpty else {
            return cacheFailureMessage
        }
        return description
    }

    internal func start() {
        guard foregroundRefreshTask == nil else {
            return
        }
        if fixtureMode {
            snapshot = .fixture
            state = .loaded
            return
        }
        if let snapshot {
            WatchSnapshotBridge.shared.publish(snapshot)
        }
        foregroundRefreshTask = Task { [weak self] in
            guard let self else {
                return
            }
            await refresh(manual: false)
            while !Task.isCancelled {
                await sleepBetweenRefreshes()
                guard !Task.isCancelled else {
                    return
                }
                await refresh(manual: false)
            }
        }
    }

    internal func stopForegroundRefresh() {
        foregroundRefreshTask?.cancel()
        foregroundRefreshTask = nil
    }

    internal func refresh(manual: Bool) async {
        if fixtureMode {
            snapshot = .fixture
            state = .loaded
            refreshNotice = "Preview data refreshed"
            return
        }
        if state == .loading {
            return
        }
        state = .loading
        lastAttemptAt = Date()
        do {
            let updated: CodexSnapshot = try await loadSnapshot(manual: manual)
            try SnapshotCache.save(updated)
            snapshot = updated
            state = .loaded
            WatchSnapshotBridge.shared.publish(updated)
            WidgetCenter.shared.reloadAllTimelines()
        } catch {
            state = .failed(Self.safeMessage(for: error))
        }
    }

    internal func performBackgroundRefresh(task: BGAppRefreshTask) {
        scheduleBackgroundRefresh()
        let work: Task<Void, Never> = .init { @MainActor [weak self] in
            guard let self else {
                task.setTaskCompleted(success: false)
                return
            }
            await refresh(manual: false)
            var success: Bool = false
            if case .loaded = state {
                success = true
            }
            task.setTaskCompleted(success: success)
        }
        task.expirationHandler = {
            work.cancel()
        }
    }

    internal func scheduleBackgroundRefresh() {
        guard !fixtureMode else {
            return
        }
        BGTaskScheduler.shared.cancel(taskRequestWithIdentifier: BackgroundRefresh.identifier)
        let request: BGAppRefreshTaskRequest = .init(identifier: BackgroundRefresh.identifier)
        request.earliestBeginDate = Date(timeIntervalSinceNow: backgroundInterval)
        do {
            try BGTaskScheduler.shared.submit(request)
        } catch {
            refreshNotice = "Background refresh scheduling is unavailable"
        }
    }

    private func loadSnapshot(manual: Bool) async throws -> CodexSnapshot {
        guard manual else {
            refreshNotice = nil
            return try await client.fetchCapacity()
        }
        let response: RefreshResponse = try await client.requestManualRefresh()
        if response.probeStarted {
            refreshNotice = "Provider state refreshed"
        } else if response.reason == "probe_throttled", let retry = response.retryAfterSeconds {
            refreshNotice = "Already fresh · retry in \(retry)s"
        } else {
            refreshNotice = "Latest broker state loaded"
        }
        return response.snapshot
    }

    private func sleepBetweenRefreshes() async {
        do {
            try await Task.sleep(for: .seconds(backgroundInterval))
        } catch {
            // Cancellation ends the foreground refresh loop.
        }
    }

    deinit {
        // The foreground refresh task is cancelled through `stopForegroundRefresh()`.
    }
}
