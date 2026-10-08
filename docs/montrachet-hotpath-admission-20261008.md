# Montrachet website hotpath admission

Prepared for the 8 October weekly inventory, PM
`b526cdf8-fb55-4e11-8457-4efedccdf6ad`. This source change adds one report
identity for the existing website runner, not a new worker or schedule.

## Existing execution and ownership

Website owner: `964ce401-6111-5f0c-9158-043a1ef3efe5`, under Montrachet manager
`d073eb2b-6f58-52ab-8b68-1d7d3165680f`. Website task:
`21eee407-7a70-54f2-be9b-4fdac58eaf44`.

The installed `montrachet-website-hotpath.timer` is active, with
`OnCalendar=*-*-* 05:15:00 UTC`, `RandomizedDelaySec=300` and `Persistent=true`.
The read-only 8 October observation returned last trigger 05:18:44 UTC, next
9 October 05:18:05 UTC, service result `success` and exit status 0. Its opaque
inventory schedule reference is `systemd:montrachet-website-hotpath.timer`.
Do not create a second daily engine reminder for this runner.

Retained result
`/mnt/pitchai-dev-data/artifacts/montrachet-website-hotpath/20261008T051844Z/result.json`
records nine passing steps from 05:18:44.875 to 05:18:52.137 UTC, including
deactivation. The retained browse screenshot was visually inspected and shows
the explicitly synthetic source and accepted-record count. Earlier failed
results remain historical. The current release link points to
`89f742f197aeff260dfac170ad76147fdbf10314`; that current observation is **not**
an attestation of the revision served during the earlier run.

## Identity and coverage

- Lane: `montrachet-website-hotpath`
- Project: `montrachet`
- Name: `Montrachet private data website`
- Target: `montrachet.pitchai.net application loopback; synthetic CSV import and agent read`
- Primary domain: `montrachet.pitchai.net`

The application runner already creates its own synthetic source, uploads one
CSV row, maps/previews/applies it, browses the accepted fact, grants and checks
the synthetic agent's source read, and deactivates the source. Its loopback
identity-header route does not test public SSO or real Google import. Those
must remain explicit coverage limits. The active real-Google implementation
has separate ownership and may not be interrupted or used as monitor data.

## Admission is not a passing report

Registration must initially show `never_reported`. No historical result may be
upgraded with an invented source/deployed revision, artifact receipt, duration
or occurrence. The existing runner needs exact revision capture, the existing
private SeaweedFS upload/readback contract and the canonical reporter. Its
owner must retain the sole timer, scoped synthetic data and cleanup. Public
SSO/Google coverage must not become green through registration or loopback
proof. The separate uptime PR240 does not provide this functional evidence.

The paired infrastructure identity map must use these exact fields. Verify
the owner tag and accepted live report independently before calling the weekly
inventory complete. Manager coordination was queued once as command
`3b3f3f59-5de2-4417-bfb9-54d970643081`; delivery remains unverified at source
preparation. This document does not claim deployment or completed reporting.
