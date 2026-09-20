# Daily monitoring review: 2026-09-20 (second fire, run 80)

## Decision

**No new findings.** This fire
(`reminder-20260630T073139899030-3b53242d@2026-09-20T030000z`, run 80) landed 30
minutes after the 2026-09-19 review was completed by the same agent, so it
re-validated live state and recorded the delta instead of duplicating the full
report. The rolling 24-hour picture is unchanged from
`monitoring/reporting/2026-09-19-daily-review.md` (merged in PR #143); live
checks below were taken 2026-09-20T03:27-03:34Z.

Live re-checks: state schema v6 refreshed 2026-09-20T03:26:56Z with a zero
state-write failure streak; seven of eight core domains at 612/612 = 100% and
`cms.deplanbook.com` still at 62.092% from the 2026-09-19 05:09-14:50Z incident
window (green since); `browser` 0/612, `dns` 0/91 and `proxy` 0/612 bad
samples; `container_health` green with fail streak 0; `host_health` still
`ok=0` on swap 99.973% (2.7 MB free of 32 GB) plus the one standing violation;
`meta` 126.9 s cycle against the 60 s interval; `tls` 3 failures;
`performance` 45 slow domains, `red` 56 violations, `slo` 6.

Dashboard: `ok=true`, 82 domains, 42741/50184 = 85.169% aggregate;
`montrachet-demo.pitchai.net` left the down list when both flapping demo routes
recovered at 03:13:41Z (verified 200 on `/` and `/readyz`). External E2E:
`ok=true`, 36 tests, `failing_tests=2` (both disabled historical rows), no
enabled test with a non-pass `last_status`. Containers: none unhealthy or
restarting; `service-monitoring`, `e2e-registry` and `e2e-runner` up 33 hours.
`nginx -t` passes, 14 failed units unchanged, `registry.pitchai.net:5000` TLS
valid to 2026-10-21 with a working manifest, ACME webroot probes for
`staging.formatief-toetsen.pitchai.net` return 404 on HTTP and HTTPS, `n8n`
still has no enabled reference, and `monitoring.pitchai.net/health` returns ok.
Nginx error log over 24 h: 1399 `connect() failed` (slow scanner traffic on the
same two dead dashboard-only upstreams) and 12 `upstream prematurely closed`,
with no `no live upstreams` and no oversized-header errors.

## Dedicated host: aipc-fsn1-01 (5.9.42.254)

Reachable read-only. Uptime 14 days 16 h, load 12.2/18.6/18.3 on 8 CPUs,
`/dev/md2` 38% (270 GB free, inodes 14%), `/srv/pitchai-data` 31% (890 GB
free), swap 1/15 GiB, journal 1002.5 MB (8 MB above the reading 20 minutes
earlier — steady logging, still inside the journald cap). Docker: the same
three running fixture/proof containers plus one exited build container, and no
`aipc-*` or `ai_price_crawler-*` containers and no `actions.runner.*` unit, so
the container and isolated-runner inventory gap stays open for server-ops
(recorded on topology task `e13a891e-7aed-4225-a370-92da1d4ebdd3`). The same
seven one-shot proof/audit units remain failed; none serve traffic.

## Disk observation (pitchai-main)

`/dev/md2` free space moved 459 GB (03:09Z) → 447 GB (03:28Z) → 458 GB (03:31Z)
→ 458 GB (03:33Z). Container JSON logs are not the cause: all container logs
total 11 GB and grew only 164 KB in 45 s, and the two largest (1.5 GB each)
belong to the long-paused `autopar-batch-stage4-jaw-backfill-02/04` containers.
A bounded scan found no large file remaining on the root filesystem and no
deleted-but-open large file, so this looks like a periodic write-then-remove
burst such as a backup or rollup job. The filesystem is at 73% with 458 GB
free, so it is not near full; the next review should confirm the cycle and its
peak before it is treated as settled.

## SkyBuyFly certificate

Unchanged from the morning review: both front doors serve the lineage expiring
2026-10-19T03:35:18Z. The HEL1 certbot timer fires at 2026-09-20T04:09Z and
will fail again until the missing ACME account is repaired (last failure
2026-09-19T17:42Z). Nothing was changed from this lane.

## Actions

None. No fix was applied and no message was sent from this fire: the escalation
obligation for this morning was already met at 03:20Z with a verified
requester-private receipt, and this pass produced no new broken pattern.
