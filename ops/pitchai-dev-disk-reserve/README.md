# Montrachet demo disk-reserve safety valve (pitchai-dev)

The public demo `montrachet-demo.pitchai.net` runs on `pitchai-dev`, where the
demo Postgres PANICs the moment the root filesystem cannot satisfy a write
(`could not write to file "pg_logical/replorigin_checkpoint.tmp": No space left
on device`). That has taken the production surface down five times since
2026-09-18 while the host carries far more live lane work than its 905G root can
hold (see PM `DISK-PITCHAI-DEV-20260919` and incident task entries recorded by
the monitoring incident lane).

The pitchai-server-space registry intentionally keeps existing agent work
untouched and only reclaims caches, so between its passes the host can still
cross zero. This guard closes that gap for the monitored production surface:

1. **Arm with headroom.** While root has more than `FREE_REARM_BYTES` (4 GiB)
   available, hold a `RESERVE_TARGET_BYTES` (2 GiB) `fallocate`d reserve file.
2. **Release on critical.** When root drops below `FREE_CRITICAL_BYTES`
   (512 MiB) available, delete the reserve immediately. A few hundred MiB is
   all the demo Postgres needs to finish its end-of-recovery checkpoint, so the
   surface stays up.
3. **Crisis reclaim.** If the filesystem is still below `CRISIS_FLOOR_BYTES`
   (256 MiB) after release, reclaim regenerable space only: journald vacuum to
   200 MiB, `docker image prune` and `docker builder prune` for objects older
   than 24h, and the rotated `syslog`/`auth.log`/`kern.log`/`apport.log`
   archives (the active files stay readable and logrotate keeps producing new
   generations). These are the same bounded reclaims the incident lane has
   applied by hand; nothing outside regenerable caches and rotated log
   generations is ever removed.
4. **Emergency rotation.** If the filesystem is *still* below
   `FREE_EMERGENCY_BYTES` (100 MiB) — a few seconds of write headroom away from
   the Postgres PANIC — force `logrotate -f /etc/logrotate.d/rsyslog` so the
   active logs are rotated through the sanctioned rsyslog reopen hook, then
   drop the generations it just produced. This is the only rung that touches
   active log files, and it only fires when the alternative is the production
   surface going down.

The guard never touches other lanes' work, never stops containers, and never
changes the server-space registry policy. It writes one journal line per
action; a no-op run stays silent.

## Install (on pitchai-dev)

```sh
install -m 0755 pitchai-montrachet-demo-disk-reserve /usr/local/sbin/pitchai-montrachet-demo-disk-reserve
install -m 0644 pitchai-montrachet-demo-disk-reserve.service /etc/systemd/system/
install -m 0644 pitchai-montrachet-demo-disk-reserve.timer /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now pitchai-montrachet-demo-disk-reserve.timer
```

State lives in `/var/lib/pitchai-montrachet-demo-disk-reserve/` (reserve file
plus a README marker). Thresholds can be overridden with the environment
variables `RESERVE_TARGET_BYTES`, `FREE_CRITICAL_BYTES`, `FREE_REARM_BYTES`,
`CRISIS_FLOOR_BYTES`, `FREE_EMERGENCY_BYTES`, and `DRY_RUN=1` for a no-touch
dry run.

The guard is paired with `pitchai-journald-cap.conf` (install as
`/etc/systemd/journald.conf.d/10-pitchai-cap.conf`). Without it journald
inherits its default ceiling of 10% of the filesystem (~90 GiB on this host) and
regrows into whatever the host frees; with `SystemMaxUse=1G` and
`SystemKeepFree=2G` the journal stays bounded and journald itself starts
trimming whenever the root filesystem runs tight, which is exactly when the
demo needs headroom.

## Verify

```sh
systemctl list-timers pitchai-montrachet-demo-disk-reserve.timer
journalctl -u pitchai-montrachet-demo-disk-reserve --since "24 hours ago"
df -B1 --output=avail / | tail -1
```

Dry runs:

```sh
DRY_RUN=1 FREE_CRITICAL_BYTES=1125899906842624 /usr/local/sbin/pitchai-montrachet-demo-disk-reserve   # simulates release
DRY_RUN=1 FREE_REARM_BYTES=1048576 /usr/local/sbin/pitchai-montrachet-demo-disk-reserve                # simulates arm
```

## Revert

```sh
systemctl disable --now pitchai-montrachet-demo-disk-reserve.timer
rm -f /etc/systemd/system/pitchai-montrachet-demo-disk-reserve.{service,timer}
systemctl daemon-reload
rm -f /usr/local/sbin/pitchai-montrachet-demo-disk-reserve
rm -rf /var/lib/pitchai-montrachet-demo-disk-reserve
```

This is a stop-gap protection for a production surface on an over-committed
host; the durable fix remains owner-level capacity/retention work on
`pitchai-dev` (PM `DISK-PITCHAI-DEV-20260919`).
