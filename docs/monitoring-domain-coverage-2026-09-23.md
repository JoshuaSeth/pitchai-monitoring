# Domain coverage sweep — 23 September 2026

Verified live on 24 September. Discovery window: 14 September 20:45:43 UTC through 23 September 20:45:43 UTC. The recurring schedule is unchanged.

Two missing targets were added:

| Domain | Policy | Live result |
| --- | --- | --- |
| `waddinxveen.demos.pitchai.net` | Normal alerts; active client-facing demo | Healthy |
| `aetherreel.37.27.67.52.nip.io` | Dashboard-only; pre-launch platform | Healthy |

The live index contains **84 unique targets: 71 normal and 13 quiet**, plus 42 classified retirements. Every live policy matches config. All 13 quiet targets produced only INFO-level results, no warning/error lines and no actionable incidents. The previous 82 target contracts are unchanged. No DNS records were changed.

RSR (`studentenreisproduct.demos.pitchai.net`) was already retired in main. Its retirement was reconciled into staging so a future integration cannot restore it accidentally. Its one historical state row remains preserved but is excluded from active checks.

## Discovery

Scanned 367 permitted recent-agent projections, 314 detailed histories, all 85 PM projects and 498 recently updated tasks, 133 Git repository stores across three hosts, 26 DNS-engineering artifacts, a fresh 78-record Namecheap snapshot, and current ingress. Each of the 3,416 candidate strings has a disposition and source in the [machine-readable evidence](monitoring-domain-coverage-2026-09-23.json).

There are 1,134 newly ignored candidates, mainly municipality/agriculture research sources, third-party services, fixtures, temporary preview tunnels and extracted code fragments. `stable.pitchai.net`, `skybuyfly.net` and `montrachet.pitchai.net` are documented mistaken aliases; their canonical deployed hosts are monitored.

Deeper history reads failed for 53 agents despite stable-ID retries. Their authorized latest-state projections were scanned. Federated saved history was denied as tenant-unattributed; no raw-index or identity workaround was used. These limits are recorded explicitly rather than counted as successful history reads.

## Integration and deployment

- [Staging PR #160](https://github.com/JoshuaSeth/pitchai-monitoring/pull/160) and [main PR #161](https://github.com/JoshuaSeth/pitchai-monitoring/pull/161) are merged. Both passed the repository-required Enforcement integrity and Quality ratchet checks.
- Main revision `f524b3ef5c26da77aa3dbd64728e5c03400e8b61` is running in all six monitoring containers. The nginx map matches that revision and passes syntax validation.
- Focused tests passed: 27 on staging and 31 on main. Hosted full-image tests passed. Both new public pages and deployed dashboard rows passed headed-browser checks; screenshots were inspected.
- [Deployment run 35966515961](https://github.com/JoshuaSeth/pitchai-monitoring/actions/runs/35966515961) is **red**, despite completing the rollout: the scheduler observer's existing 10-second authenticated feed poll timed out. The preceding release failed at the same step; its last successful poll was 21 September, before this change. A read-only 45-second probe succeeded. No incident cursor, state or gate was rewritten or weakened.
- After that failure, the original database-snapshot and exact-release dashboard verification steps passed independently: 84 domains, 16 groups, 43 database dependencies, six dashboard tabs, mobile layout and no browser errors. This proves the scoped domain rollout, not overall scheduler health.

## Remaining risks and delivery

Five existing failures retain normal alerts: `dispatch.pitchai.net`, `whatsapp.pitchai.net`, `jeff-codex-voice.pitchai.net`, `jeff-dispatch.pitchai.net` and `jeff-work-inbox.pitchai.net`. AetherReel and Wrist Vault remain pre-launch/quiet. Existing nginx duplicate-server-name/protocol warnings and the scheduler observer timeout remain visible; this sweep does not claim universal service health.

One requester-private Telegram completion report was delivered to Seth/ORI and verified with no broad copies. The JSON evidence retains only the sanitized routing receipt, not the private message body or raw Telegram identifiers.
