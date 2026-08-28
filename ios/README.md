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
- Installations upgraded from the initial prototype migrate the former App
  Group preference value once into the protected snapshot file, then remove the
  preference value only after the file write succeeds.
- Failure and stale states remain visible. The app never replaces missing quota
  windows with invented capacity.

## Targets

- `CodexStatus`: iOS dashboard and battery-safe background refresh.
- `CodexStatusWidget`: Home Screen, Lock Screen, and StandBy widgets.
- `CodexStatusWatch`: paired Watch dashboard with iPhone-mediated refresh.
- `CodexStatusWatchWidget`: accessory families for the watchOS Smart Stack.
- `CodexStatusTests`: native contract, nil-capacity, and cache-privacy tests.
- `CodexStatusUITests`: a sanitized iPhone live-status render gate.
- `CodexStatusWatchUITests`: launch proof plus a strict live-snapshot assertion
  for simulator and physical-Watch evidence.

## App icon

The app targets share the single-size `AppIcon` asset catalog entry. Its
source-of-truth is `Design/CodexStatusIcon.svg`; the committed 1024 px sRGB PNG
is full-bleed and opaque so iOS can apply its rounded-rectangle mask and
watchOS can apply its circular mask without a baked edge. Keep the capacity
ring and checkmark centered because watchOS crops the square master to a
circle. WidgetKit uses the icon of the containing iPhone or Watch app in system
galleries and complication pickers; the extensions must not declare a second
primary app icon.

Regenerate and validate the flattened asset deterministically from the `ios`
directory. The script uses Chrome's SVG renderer, then normalizes and checks the
PNG with ImageMagick:

```bash
./render_app_icon.sh
```

The Xcode project is generated from `project.yml`; do not commit the generated
`.xcodeproj` or DerivedData. Asset catalogs and privacy manifests are explicit
`sources` entries with `buildPhase: resources`; XcodeGen otherwise ignores an
unknown target-level `resources` key without creating a Copy Bundle Resources
phase.

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

The Watch UI-test target keeps launch proof separate from live-data proof. Run
`testDashboardLaunches` to validate the root UI, and count
`testLiveSnapshotRenders` only when the Watch received a real snapshot through
the signed app data path.

The `CodexStatusPhysicalLive` scheme is intentionally device-only. Its explicit
environment enables the guarded App Attest/cache integration tests and the
hero-only iPhone UI screenshot, while normal simulator test runs skip all live
network and App Group assertions.

Run the simulator app with `-CodexStatusFixture` only for sanitized UI evidence.
The normal app has no fixture fallback: it fails clearly when App Attest or the
live service is unavailable.

Debug Watch builds also accept `-CodexStatusDiagnosticSnapshotBase64` for
sanitized real-device diagnostics. The payload must decode as the native
snapshot contract and is written through the same protected App Group cache as
production data. The argument is absent from Release builds and diagnostic
evidence does not replace phone-to-Watch WatchConnectivity proof.

Release builds use automatic signing for Apple team `ZM6568G5FX`. Debug device
builds pin the four target-specific development profiles named in `project.yml`
so a trusted deployment Mac does not need a logged-in Xcode account. Those
profiles must contain App Attest in the development environment and the
`group.com.pitchai.codexstatus` App Group; the project also uses Background
Tasks, WatchConnectivity, and WidgetKit. Open the server enrollment gate only
while registering the intended physical installation, then close it
immediately.
