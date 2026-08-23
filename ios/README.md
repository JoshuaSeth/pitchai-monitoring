# Codex Status for iPhone and Apple Watch

Codex Status is Seth's personal, read-only view of the live PitchAI Codex auth
broker. It presents account readiness, five-hour and weekly remaining capacity,
reset timing, source freshness, and warnings on iPhone, Apple Watch, and
WidgetKit/Smart Stack surfaces.

## Security and data flow

- The iPhone authenticates each request with an Apple App Attest assertion over
  a server-issued, one-time challenge. No broker credential, API token, SSO
  cookie, email address, password, or device code is embedded in the project.
- The native API is a redacted projection and excludes account IDs, emails,
  provider token analytics, reset inventory, receipts, and all secrets.
- The Watch has no network client or service credential. It receives snapshots
  from the paired iPhone through WatchConnectivity.
- The iPhone and both widgets share only the redacted snapshot through
  `group.com.pitchai.codexstatus`. The app's standard defaults contain only the
  opaque App Attest key identifier; Apple retains the private key.
- Failure and stale states remain visible. The app never replaces missing quota
  windows with invented capacity.

## Targets

- `CodexStatus`: iOS dashboard and battery-safe background refresh.
- `CodexStatusWidget`: Home Screen, Lock Screen, and StandBy widgets.
- `CodexStatusWatch`: paired Watch dashboard with iPhone-mediated refresh.
- `CodexStatusWatchWidget`: accessory families for the watchOS Smart Stack.
- `CodexStatusTests`: native contract, nil-capacity, and cache-privacy tests.

The Xcode project is generated from `project.yml`; do not commit the generated
`.xcodeproj` or DerivedData.

## Build and test

On a Mac with Xcode 26 and XcodeGen:

```bash
xcodegen generate
xcodebuild \
  -project CodexStatus.xcodeproj \
  -scheme CodexStatus \
  -destination 'platform=iOS Simulator,name=iPhone 16 Pro' \
  CODE_SIGNING_ALLOWED=NO \
  test
```

Run the simulator app with `-CodexStatusFixture` only for sanitized UI evidence.
The normal app has no fixture fallback: it fails clearly when App Attest or the
live service is unavailable.

Physical builds use automatic signing for Apple team `ZM6568G5FX`. The required
capabilities are App Attest in the development environment, the
`group.com.pitchai.codexstatus` App Group, Background Tasks, WatchConnectivity,
and WidgetKit. Open the server enrollment gate only while registering the
intended physical installation, then close it immediately.
