import XCTest

@MainActor
internal final class CodexStatusWatchUITests: XCTestCase {
    override internal func setUpWithError() throws {
        continueAfterFailure = false
    }

    override internal func tearDownWithError() throws {
        continueAfterFailure = true
    }

    internal func testDashboardLaunches() {
        let app: XCUIApplication = .init()
        app.launch()

        let title: XCUIElement = app.navigationBars["Codex"]
        let titleText: XCUIElement = app.staticTexts["Codex"]
        guard title.waitForExistence(timeout: 45) || titleText.waitForExistence(timeout: 5) else {
            XCTFail("The Codex Status root view did not become visible.")
            return
        }

        attachScreenshot(named: "watch-dashboard-launch")
    }

    internal func testLiveSnapshotRenders() {
        let app: XCUIApplication = .init()
        app.launch()

        guard app.staticTexts["accounts ready"].waitForExistence(timeout: 45) else {
            XCTFail("The Watch did not render a live capacity snapshot.")
            return
        }
        guard exposesBrokerState(in: app) else {
            XCTFail("The live snapshot did not expose an explicit broker state.")
            return
        }

        attachScreenshot(named: "watch-dashboard-live")
    }

    private func exposesBrokerState(in app: XCUIApplication) -> Bool {
        let labels: [String] = ["Verified", "Attention", "No capacity", "Stale"]
        return labels.contains { label in
            app.staticTexts[label].exists
        }
    }

    private func attachScreenshot(named name: String) {
        let attachment: XCTAttachment = .init(screenshot: XCUIScreen.main.screenshot())
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }

    deinit {
        // XCTest owns the runner lifecycle; no additional resources are retained here.
    }
}
