import BackgroundTasks
import Foundation
import SwiftUI
import WidgetKit

@MainActor
final class SnapshotStore: ObservableObject {
    static let shared = SnapshotStore()

    enum LoadState: Equatable {
        case idle
        case loading
        case loaded
        case failed(String)
    }

    @Published private(set) var snapshot: CodexSnapshot?
    @Published private(set) var state: LoadState = .idle
    @Published private(set) var refreshNotice: String?
    @Published private(set) var lastAttemptAt: Date?

    private let client: SecureCapacityClient
    private let fixtureMode: Bool
    private var foregroundRefreshTask: Task<Void, Never>?

    init(
        client: SecureCapacityClient = .live,
        fixtureMode: Bool = ProcessInfo.processInfo.arguments.contains("-CodexStatusFixture")
    ) {
        self.client = client
        self.fixtureMode = fixtureMode
        self.snapshot = fixtureMode ? .fixture : SnapshotCache.load()
        self.state = self.snapshot == nil ? .idle : .loaded
    }

    func start() {
        guard foregroundRefreshTask == nil else { return }
        if fixtureMode {
            snapshot = .fixture
            state = .loaded
            return
        }
        foregroundRefreshTask = Task { [weak self] in
            guard let self else { return }
            await refresh(manual: false)
            while !Task.isCancelled {
                let seconds = snapshot?.refreshPolicy.recommendedBackgroundIntervalSeconds ?? 900
                try? await Task.sleep(for: .seconds(max(900, seconds)))
                guard !Task.isCancelled else { return }
                await refresh(manual: false)
            }
        }
    }

    func stopForegroundRefresh() {
        foregroundRefreshTask?.cancel()
        foregroundRefreshTask = nil
    }

    func refresh(manual: Bool) async {
        if fixtureMode {
            snapshot = .fixture
            state = .loaded
            refreshNotice = "Preview data refreshed"
            return
        }
        if state == .loading { return }
        state = .loading
        lastAttemptAt = Date()
        do {
            let updated: CodexSnapshot
            if manual {
                let response = try await client.requestManualRefresh()
                updated = response.snapshot
                if response.probeStarted {
                    refreshNotice = "Provider state refreshed"
                } else if response.reason == "probe_throttled",
                          let retry = response.retryAfterSeconds {
                    refreshNotice = "Already fresh · retry in \(retry)s"
                } else {
                    refreshNotice = "Latest broker state loaded"
                }
            } else {
                updated = try await client.fetchCapacity()
                refreshNotice = nil
            }
            try SnapshotCache.save(updated)
            snapshot = updated
            state = .loaded
            WatchSnapshotBridge.shared.publish(updated)
            WidgetCenter.shared.reloadAllTimelines()
        } catch {
            state = .failed(Self.safeMessage(for: error))
        }
    }

    func performBackgroundRefresh(task: BGAppRefreshTask) {
        scheduleBackgroundRefresh()
        let work = Task { @MainActor [weak self] in
            guard let self else {
                task.setTaskCompleted(success: false)
                return
            }
            await refresh(manual: false)
            let success: Bool
            if case .loaded = state {
                success = true
            } else {
                success = false
            }
            task.setTaskCompleted(success: success)
        }
        task.expirationHandler = {
            work.cancel()
        }
    }

    func scheduleBackgroundRefresh() {
        guard !fixtureMode else { return }
        BGTaskScheduler.shared.cancel(taskRequestWithIdentifier: BackgroundRefresh.identifier)
        let request = BGAppRefreshTaskRequest(identifier: BackgroundRefresh.identifier)
        let seconds = snapshot?.refreshPolicy.recommendedBackgroundIntervalSeconds ?? 900
        request.earliestBeginDate = Date(timeIntervalSinceNow: TimeInterval(max(900, seconds)))
        do {
            try BGTaskScheduler.shared.submit(request)
        } catch {
            refreshNotice = "Background refresh scheduling is unavailable"
        }
    }

    private static func safeMessage(for error: Error) -> String {
        if let localized = error as? LocalizedError,
           let description = localized.errorDescription,
           !description.isEmpty {
            return description
        }
        return "Live capacity could not be refreshed. Cached values remain visible."
    }
}

enum BackgroundRefresh {
    static let identifier = "com.pitchai.codexstatus.refresh"

    static func register() {
        BGTaskScheduler.shared.register(forTaskWithIdentifier: identifier, using: nil) { task in
            guard let refreshTask = task as? BGAppRefreshTask else {
                task.setTaskCompleted(success: false)
                return
            }
            Task { @MainActor in
                SnapshotStore.shared.performBackgroundRefresh(task: refreshTask)
            }
        }
    }
}
