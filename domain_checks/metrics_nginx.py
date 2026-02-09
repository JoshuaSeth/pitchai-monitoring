from __future__ import annotations

import gzip
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_ACCESS_RE = re.compile(
    r'^\S+\s+\S+\s+\S+\s+\[(?P<ts>[^\]]+)\]\s+"(?P<req>[^"]*)"\s+(?P<status>\d{3})\s+(?P<size>\S+)\s+"(?P<ref>[^"]*)"\s+"(?P<ua>[^"]*)"'
)

_ERROR_TS_RE = re.compile(r"^(?P<ts>\d{4}/\d{2}/\d{2}\s+\d{2}:\d{2}:\d{2})\s+\[(?P<level>\w+)\]\s+")


def _tail_bytes(path: Path, *, max_bytes: int) -> str:
    """
    Best-effort tail read.
    - Supports .gz (reads entire compressed file, so use small max_bytes for .gz configs).
    """
    p = Path(path)
    if not p.exists():
        return ""
    if p.suffix == ".gz":
        try:
            with gzip.open(p, "rt", encoding="utf-8", errors="replace") as f:
                data = f.read()
            return data[-max(1, int(max_bytes)) :]
        except Exception:
            return ""

    try:
        with open(p, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            n = max(1, min(int(max_bytes), int(size)))
            f.seek(size - n, os.SEEK_SET)
            raw = f.read(n)
        return raw.decode("utf-8", errors="replace")
    except Exception:
        return ""


@dataclass(frozen=True)
class NginxAccessWindowStats:
    total: int
    status_5xx: int
    status_502_504: int
    status_4xx: int
    sample_lines: list[str]


def compute_access_window_stats(
    *,
    access_log_path: str,
    now: datetime,
    window_seconds: int,
    max_bytes: int = 1_000_000,
    sample_limit: int = 8,
) -> NginxAccessWindowStats | None:
    txt = _tail_bytes(Path(access_log_path), max_bytes=int(max_bytes))
    if not txt.strip():
        return None

    cutoff = now.astimezone(timezone.utc).timestamp() - max(1, int(window_seconds))
    total = 0
    status_5xx = 0
    status_502_504 = 0
    status_4xx = 0
    samples: list[str] = []

    for line in reversed(txt.splitlines()):
        m = _ACCESS_RE.match(line.strip())
        if not m:
            continue
        ts_s = m.group("ts")
        try:
            dt = datetime.strptime(ts_s, "%d/%b/%Y:%H:%M:%S %z")
        except Exception:
            continue
        ts = dt.astimezone(timezone.utc).timestamp()
        if ts < cutoff:
            break

        try:
            status = int(m.group("status"))
        except Exception:
            status = 0

        total += 1
        if 500 <= status < 600:
            status_5xx += 1
        if status in {502, 504}:
            status_502_504 += 1
        if 400 <= status < 500:
            status_4xx += 1
        if (status in {502, 503, 504}) and len(samples) < int(sample_limit):
            samples.append(line.strip()[:800])

    samples.reverse()
    return NginxAccessWindowStats(
        total=total,
        status_5xx=status_5xx,
        status_502_504=status_502_504,
        status_4xx=status_4xx,
        sample_lines=samples,
    )


@dataclass(frozen=True)
class NginxUpstreamErrorEvent:
    ts: str
    level: str
    server: str | None
    upstream: str | None
    message: str


def _extract_kv(line: str, key: str) -> str | None:
    marker = f"{key}: "
    if marker not in line:
        return None
    rest = line.split(marker, 1)[1]
    if "," in rest:
        rest = rest.split(",", 1)[0]
    return rest.strip().strip('"') or None


def parse_recent_upstream_errors(
    *,
    error_log_path: str,
    now: datetime,
    window_seconds: int,
    local_tz,
    max_bytes: int = 1_000_000,
    max_events: int = 200,
) -> list[NginxUpstreamErrorEvent]:
    txt = _tail_bytes(Path(error_log_path), max_bytes=int(max_bytes))
    if not txt.strip():
        return []

    # error.log timestamps do not include TZ; interpret using configured tz (host local).
    cutoff = now.astimezone(local_tz).timestamp() - max(1, int(window_seconds))
    events: list[NginxUpstreamErrorEvent] = []

    for line in reversed(txt.splitlines()):
        s = line.strip()
        if not s:
            continue
        m = _ERROR_TS_RE.match(s)
        if not m:
            continue
        ts_s = m.group("ts")
        level = m.group("level")
        try:
            dt = datetime.strptime(ts_s, "%Y/%m/%d %H:%M:%S").replace(tzinfo=local_tz)
        except Exception:
            continue
        ts = dt.timestamp()
        if ts < cutoff:
            break

        # Focus on upstream failures (timeouts/connect errors/502/504 surfaces).
        low = s.lower()
        if "upstream" not in low and "connect()" not in low:
            continue
        if not any(x in low for x in ("timed out", "failed", "refused", "no live upstreams", "upstream prematurely closed")):
            # Keep some upstream warnings, but avoid noise like buffering warnings.
            if "upstream response is buffered" in low:
                continue

        server = _extract_kv(s, "server")
        upstream = _extract_kv(s, "upstream")
        msg = s
        events.append(
            NginxUpstreamErrorEvent(
                ts=ts_s,
                level=level,
                server=server,
                upstream=upstream,
                message=msg[:1000],
            )
        )
        if len(events) >= int(max_events):
            break

    events.reverse()
    return events


def summarize_upstream_errors(events: list[NginxUpstreamErrorEvent]) -> dict[str, Any]:
    by_server: dict[str, int] = {}
    samples: dict[str, list[str]] = {}
    for e in events:
        server = e.server or "(unknown)"
        by_server[server] = int(by_server.get(server, 0)) + 1
        if server not in samples:
            samples[server] = []
        if len(samples[server]) < 3:
            samples[server].append(e.message)
    return {"counts_by_server": by_server, "samples_by_server": samples}

