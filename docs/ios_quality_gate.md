# PitchAI iOS Quality Gate

Codex Status uses the reusable PitchAI gate. Run it on macOS with Xcode 26,
XcodeGen, swift-format, SwiftLint, Gitleaks, and Semgrep installed.

The wrapper copies `ios/` into `.build/xcodegen/ios`, generates the existing
project there, and removes that copy on exit. Product sources, signing settings,
provisioning profiles, and the checked-in XcodeGen specification stay unchanged.

The `CodexStatus` scheme uses unsigned simulator builds, analyze, and unit tests,
including the iPhone, Watch, and widget build dependencies. Physical/live schemes
are excluded; their existing opt-in tests must not be enabled for this gate.
Missing tools and failed compilation or tests fail nonzero.

The rollout targets `staging`; production deployment requires a push to `main`.
Its commit and squash title retain `[ios-quality-no-artifacts]`. The Python
workflow also recognizes the exact rollout PR branch to prevent report artifact
publication while preserving every validation job.

Run:

```sh
make check
```

Useful commands:

```sh
make check-list
make check-one GATE=swiftlint
make check-probe
make format
```

The gate fails on formatting drift, SwiftLint violations, PitchAI forbidden
runtime patterns, secret-like strings, Semgrep findings, dependency issues,
compiler warnings/errors, strict concurrency failures, SwiftPM build/test
failures, analyzer findings, and test/simulator failures according to
`scripts/ios_check.env`.

Release safety: this gate is not release automation. It uses simulator/test
builds and a local DerivedData path. It must not archive, export, upload to
TestFlight, or modify signing/provisioning settings.
