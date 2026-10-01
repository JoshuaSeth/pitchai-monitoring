# pitchai-dev logind session headroom

`pitchai-dev` refuses new logind sessions once `Login.SessionsMax` (default
8192) is reached. On 2026-09-21 the host was at 8192/8192: 8186 sessions were
stuck in logind's `closing` state with their scope unit already gone
(`Unit session-<id>.scope could not be found`) and their leader process dead,
so `loginctl terminate-session` was a no-op and the phantoms could never be
garbage collected. Every subsequent SSH login logged
`pam_systemd(sshd:session): Failed to create session: Maximum number of
sessions (8192) reached, refusing further sessions` (59,790 times on 2026-09-21
alone) and lost its managed session.

Two pieces close that failure mode:

1. **`pitchai-dev-session-reaper` (+ timer, every 10 minutes).** Below
   `MIN_SESSIONS` (1024) it exits silently. Above it, when at least
   `STALE_RATIO_PERCENT` (90%) of sessions are dead `closing` entries, it
   drops those `/run/systemd/sessions/<id>` state files and restarts
   `systemd-logind`, which rebuilds its table from what is actually live.
   Restarting logind does not signal running processes while
   `KillUserProcesses=no` (the host default); live sessions are re-adopted
   from their own state files. If the table is large but not stale-dominated
   the guard only logs a line and leaves logind alone.
2. **`10-pitchai-session-headroom.conf`.** Raises `SessionsMax` to 65536 so a
   future backlog cannot refuse new logins before the reaper gets to it.

## Install (on pitchai-dev)

```sh
install -m 0755 pitchai-dev-session-reaper /usr/local/sbin/pitchai-dev-session-reaper
install -m 0644 pitchai-dev-session-reaper.service /etc/systemd/system/
install -m 0644 pitchai-dev-session-reaper.timer /etc/systemd/system/
install -d -m 0755 /etc/systemd/logind.conf.d
install -m 0644 10-pitchai-session-headroom.conf /etc/systemd/logind.conf.d/
systemctl daemon-reload
systemctl enable --now pitchai-dev-session-reaper.timer
```

`SessionsMax` is read by logind at start/reload time; apply it with
`systemctl restart systemd-logind` (safe for running work, see above).

## Verify

```sh
loginctl list-sessions --no-legend | wc -l
systemctl list-timers pitchai-dev-session-reaper.timer
journalctl -u pitchai-dev-session-reaper --since "24 hours ago"
grep -c 'Maximum number of sessions' /var/log/auth.log
```

`DRY_RUN=1 /usr/local/sbin/pitchai-dev-session-reaper` reports what it would do
without touching anything; `MIN_SESSIONS` and `STALE_RATIO_PERCENT` are
overridable for a bounded manual run.

## Revert

```sh
systemctl disable --now pitchai-dev-session-reaper.timer
rm -f /etc/systemd/system/pitchai-dev-session-reaper.{service,timer}
rm -f /etc/systemd/logind.conf.d/10-pitchai-session-headroom.conf
systemctl daemon-reload
rm -f /usr/local/sbin/pitchai-dev-session-reaper
```
