import SwiftUI

@main
struct CodexStatusWatchApp: App {
    @StateObject private var store = WatchSnapshotStore()

    var body: some Scene {
        WindowGroup {
            WatchCapacityView()
                .environmentObject(store)
        }
    }
}
