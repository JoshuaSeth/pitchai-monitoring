from __future__ import annotations

from bisect import bisect_left
from typing import Any, Iterable


# Sample encoding for on-disk state.json (compact, stable schema):
# [ts, ok, http_elapsed_ms, browser_elapsed_ms, status_code]
#
# - ts: float unix timestamp (seconds)
# - ok: bool
# - http_elapsed_ms/browser_elapsed_ms: float | None
# - status_code: int | None
Sample = list[Any]


def coerce_history(raw: Any) -> dict[str, list[Sample]]:
    """
    Best-effort decode for history loaded from state.json.
    Ignores invalid entries to be robust to partial writes or older formats.
    """
    if not isinstance(raw, dict):
        return {}

    out: dict[str, list[Sample]] = {}
    for domain, items in raw.items():
        if not isinstance(domain, str) or not domain:
            continue
        if not isinstance(items, list):
            continue

        samples: list[Sample] = []
        for item in items:
            if not isinstance(item, list) or len(item) < 2:
                continue
            try:
                ts = float(item[0])
            except Exception:
                continue
            ok = bool(item[1])

            http_ms = None
            if len(item) >= 3 and item[2] is not None:
                try:
                    http_ms = float(item[2])
                except Exception:
                    http_ms = None

            browser_ms = None
            if len(item) >= 4 and item[3] is not None:
                try:
                    browser_ms = float(item[3])
                except Exception:
                    browser_ms = None

            status_code = None
            if len(item) >= 5 and item[4] is not None:
                try:
                    status_code = int(item[4])
                except Exception:
                    status_code = None

            samples.append([ts, ok, http_ms, browser_ms, status_code])

        samples.sort(key=lambda s: float(s[0] or 0.0))
        if samples:
            out[domain] = samples

    return out


def append_sample(
    history: dict[str, list[Sample]],
    *,
    domain: str,
    ts: float,
    ok: bool,
    http_elapsed_ms: float | None,
    browser_elapsed_ms: float | None,
    status_code: int | None,
) -> None:
    if not domain:
        return

    sample: Sample = [
        float(ts),
        bool(ok),
        float(http_elapsed_ms) if http_elapsed_ms is not None else None,
        float(browser_elapsed_ms) if browser_elapsed_ms is not None else None,
        int(status_code) if status_code is not None else None,
    ]

    items = history.get(domain)
    if items is None:
        history[domain] = [sample]
        return

    # Normal case: we append in time-order (cycle order). If a clock jump or out-of-order
    # append happens, fall back to sorted insert.
    if not items or float(items[-1][0] or 0.0) <= float(sample[0] or 0.0):
        items.append(sample)
        return

    idx = bisect_left([float(s[0] or 0.0) for s in items], float(sample[0] or 0.0))
    items.insert(idx, sample)


def prune_history(history: dict[str, list[Sample]], *, before_ts: float) -> None:
    cutoff = float(before_ts)
    for domain in list(history.keys()):
        items = history.get(domain) or []
        if not items:
            del history[domain]
            continue

        # Find first sample with ts >= cutoff.
        ts_list = [float(s[0] or 0.0) for s in items]
        idx = bisect_left(ts_list, cutoff)
        if idx <= 0:
            continue
        if idx >= len(items):
            del history[domain]
            continue
        history[domain] = items[idx:]


def window_samples(items: list[Sample], *, since_ts: float) -> list[Sample]:
    if not items:
        return []
    cutoff = float(since_ts)
    ts_list = [float(s[0] or 0.0) for s in items]
    idx = bisect_left(ts_list, cutoff)
    return items[idx:]


def compute_availability(items: list[Sample]) -> tuple[int, int, float | None]:
    """
    Returns (total, ok_count, ok_percent_or_None_if_total_0)
    """
    total = len(items)
    if total <= 0:
        return 0, 0, None
    ok_count = sum(1 for s in items if bool(s[1]))
    ok_pct = (ok_count / float(total)) * 100.0
    return total, ok_count, ok_pct


def compute_error_rate_percent(items: list[Sample]) -> float | None:
    total = len(items)
    if total <= 0:
        return None
    ok_count = sum(1 for s in items if bool(s[1]))
    err_count = total - ok_count
    return (err_count / float(total)) * 100.0


def _percentile(sorted_values: list[float], p: float) -> float | None:
    if not sorted_values:
        return None
    p = float(p)
    if p <= 0:
        return float(sorted_values[0])
    if p >= 100:
        return float(sorted_values[-1])
    # Nearest-rank method.
    k = int(round((p / 100.0) * (len(sorted_values) - 1)))
    k = max(0, min(k, len(sorted_values) - 1))
    return float(sorted_values[k])


def extract_latency_ms(items: Iterable[Sample], *, field: str) -> list[float]:
    idx = 2 if field == "http_elapsed_ms" else 3
    out: list[float] = []
    for s in items:
        if not isinstance(s, list) or len(s) <= idx:
            continue
        v = s[idx]
        if v is None:
            continue
        try:
            out.append(float(v))
        except Exception:
            continue
    return out


def latency_percentile_ms(items: list[Sample], *, field: str, percentile: float) -> float | None:
    values = extract_latency_ms(items, field=field)
    values.sort()
    return _percentile(values, percentile)


def compute_burn_rate(items: list[Sample], *, slo_target_percent: float) -> float | None:
    """
    burn_rate = error_rate / error_budget
    where:
      error_rate = (1 - availability)
      error_budget = (1 - SLO)
    """
    total, ok_count, _ok_pct = compute_availability(items)
    if total <= 0:
        return None

    target = float(slo_target_percent)
    if not (0.0 < target < 100.0):
        return None
    budget = 1.0 - (target / 100.0)
    if budget <= 0.0:
        return None

    err_rate = (total - ok_count) / float(total)
    return err_rate / budget

