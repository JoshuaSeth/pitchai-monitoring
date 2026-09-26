# Domain coverage sweep — 26 September 2026

Discovery window: 17 September 20:45:04 UTC through 26 September 20:45:04 UTC. Verified live on 26 September. The recurring schedule is unchanged.

Added `screens.135-181-182-48.sslip.io` as **dashboard-only monitoring, with Telegram alerts disabled**. Its read-only `/health` JSON check is healthy. The Screens release notes describe test enrollment only, with production activation pending; monitoring does not open support sessions, enroll devices or request screen/control access.

The live index contains **85 unique targets: 71 normal and 14 quiet**, plus 42 classified retirements. Every runtime policy matches config. All 14 quiet targets produced INFO-level results, no warning/error lines and no actionable incidents. All 84 prior production domain contracts and all 42 retirements are unchanged. No DNS records were changed.

## Discovery

Scanned 1,748 authorized central agent projections: 327 recent/running agents and 1,421 older live lanes, including idle, waiting and blocked lanes. Recent detailed histories succeeded for 291 agents after seven smaller-read recoveries. The older live projections yielded no additional candidates.

Authorized saved-history search covered 66,286 messages in nine daily batches across three cells. Also scanned all 86 PM projects, 554 updated tasks across 31 projects, 48 CLI catalog projects, 133 Git repository stores across three hosts, 14 recent DNS-engineering artifacts, current ingress, and a fresh Namecheap snapshot containing 78 records and 74 web hostnames. All 74 are already monitored or explicitly retired.

Each of the 3,876 candidate strings has a disposition and source in the [machine-readable evidence](monitoring-domain-coverage-2026-09-26.json). There were 460 newly found strings versus the previous sweep: Screens and 459 ignored candidates. The latter are historical aliases, third-party/research references, fixtures, extracted code fragments and temporary tunnels—not 459 missing production domains.

The unresolved DePlanbook aliases (`app`, `play` and `www`), historical Azure DFT origins, the old CIS domain and the `potai.pitchai.net` typo are currently NXDOMAIN. Legacy `stable.skybuyfly.com` fails certificate hostname validation. Their canonical deployed services are already normally monitored; the evidence records the reasons for ignoring these aliases.

Thirty-six recent detailed histories remained unavailable despite retries; their authorized projections were scanned. FSN rejected tenant-unattributed saved history. No raw shared index or identity workaround was used. These are discovery limits, not successful history reads.

## Integration and deployment

- [Staging PR #168](https://github.com/JoshuaSeth/pitchai-monitoring/pull/168) and [main PR #169](https://github.com/JoshuaSeth/pitchai-monitoring/pull/169) are merged. Both passed the repository-required Enforcement integrity and Quality ratchet checks. The inherited optional Full zero-debt gate remains red.
- Main revision `7542cdf2b6cda3a02d02b94198e7c856b91bc54a` runs in all six monitoring containers. Main's newer hot-path inventory and deployment guards were preserved. The deployed nginx map matches that source and passes syntax validation.
- Focused tests passed: 22 on staging and 26 on main. Both branch-specific local quality ratchets and hosted full-image tests passed. The fresh Screens result is HTTP 200 with the required JSON contract. Its headed-browser dashboard row reads HEALTHY / DASHBOARD ONLY; the screenshot was inspected.
- [Deployment run 36272142926](https://github.com/JoshuaSeth/pitchai-monitoring/actions/runs/36272142926) is **red**, although the rollout completed: the scheduler observer's existing authenticated feed poll timed out. Its last successful poll remains 21 September, before this release. No cursor, incident state or gate was rewritten or weakened.
- After that failure, the original database-snapshot and exact-release dashboard verification steps passed independently: 85 domains, 16 groups, 43 database dependencies, six dashboard tabs, mobile layout and no browser errors. The domain incident producer is healthy with no pending events. This proves the scoped domain rollout, not overall scheduler health.

## Remaining risks and delivery

Five existing failures retain normal alerts: `dispatch.pitchai.net`, `whatsapp.pitchai.net`, `jeff-codex-voice.pitchai.net`, `jeff-dispatch.pitchai.net` and `jeff-work-inbox.pitchai.net`. Screens, AetherReel and Wrist Vault remain pre-launch/quiet. Existing nginx duplicate-server-name/protocol warnings and the scheduler timeout remain visible. One retired RSR state row is preserved but excluded from active checks.

One requester-private Telegram completion report was delivered to Seth/ORI and verified with no broad copies. The JSON evidence retains only sanitized routing and receipt facts, not the private message body or raw Telegram identifiers.
