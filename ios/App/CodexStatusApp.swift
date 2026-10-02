import SwiftUI

@main
internal struct CodexStatusApp: App {
    @Environment(\.scenePhase)
    private var scenePhase: ScenePhase

    @StateObject private var store: SnapshotStore = .shared

    internal var body: some Scene {
        WindowGroup {
            CapacityDashboardView()
                .environmentObject(store)
                .task {
                    store.start()
                }
        }
        .onChange(of: scenePhase) { _, phase in
            switch phase {
            case .active:
                store.start()

            case .background:
                store.stopForegroundRefresh()
                store.scheduleBackgroundRefresh()

            case .inactive:
                break

            @unknown default:
                break
            }
        }
    }

    internal init() {
        BackgroundRefresh.register()
        // Resolving the shared bridge activates the WatchConnectivity session at launch.
        _ = WatchSnapshotBridge.shared
    }
}
