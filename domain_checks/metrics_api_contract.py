from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin

import httpx


@dataclass(frozen=True)
class ApiContractCheckResult:
    domain: str
    name: str
    ok: bool
    url: str
    status_code: int | None
    elapsed_ms: float | None
    error: str | None
    details: dict[str, Any]


def _get_path(obj: Any, path: str) -> tuple[bool, Any]:
    """
    Dot-path traversal:
      - "a.b.c"
      - list indices supported as numeric segments: "items.0.id"
    """
    cur = obj
    for seg in (path or "").split("."):
        s = seg.strip()
        if not s:
            return False, None
        if isinstance(cur, list):
            try:
                idx = int(s)
            except Exception:
                return False, None
            if not (0 <= idx < len(cur)):
                return False, None
            cur = cur[idx]
            continue
        if isinstance(cur, dict):
            if s not in cur:
                return False, None
            cur = cur[s]
            continue
        return False, None
    return True, cur


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


async def run_api_contract_checks(
    *,
    http_client: httpx.AsyncClient,
    domain: str,
    base_url: str,
    checks: list[dict[str, Any]],
    timeout_seconds: float = 10.0,
) -> list[ApiContractCheckResult]:
    results: list[ApiContractCheckResult] = []
    cleaned_domain = str(domain or "").strip().lower()
    base = str(base_url or "").strip()

    for raw in checks:
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name") or raw.get("path") or raw.get("url") or "api_check").strip()[:80]
        method = str(raw.get("method") or "GET").strip().upper()
        path = str(raw.get("path") or "").strip()
        url = str(raw.get("url") or "").strip()
        if not url:
            if not path.startswith("/"):
                path = "/" + path if path else ""
            url = urljoin(base.rstrip("/") + "/", path.lstrip("/"))
        expected_statuses = [int(x) for x in _as_list(raw.get("expected_status_codes") or raw.get("expected_status") or [200])]
        expected_ct = str(raw.get("expected_content_type_contains") or "application/json").strip() or None
        json_required = [str(x) for x in _as_list(raw.get("json_paths_required")) if str(x or "").strip()]
        json_equal = raw.get("json_paths_equal") if isinstance(raw.get("json_paths_equal"), dict) else {}
        max_elapsed_ms = raw.get("max_elapsed_ms")
        try:
            max_elapsed_ms_f = float(max_elapsed_ms) if max_elapsed_ms is not None else None
        except Exception:
            max_elapsed_ms_f = None

        req_json = raw.get("body_json") if isinstance(raw.get("body_json"), (dict, list)) else None
        req_data = raw.get("body_text") if isinstance(raw.get("body_text"), str) else None
        headers = raw.get("headers") if isinstance(raw.get("headers"), dict) else {}

        started = time.perf_counter()
        status_code = None
        elapsed_ms = None
        err = None
        details: dict[str, Any] = {}
        ok = True

        try:
            resp = await http_client.request(
                method,
                url,
                json=req_json,
                content=req_data.encode("utf-8") if isinstance(req_data, str) else None,
                headers={str(k): str(v) for k, v in headers.items()},
                timeout=float(timeout_seconds),
                follow_redirects=True,
            )
            status_code = int(resp.status_code)
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            details["content_type"] = resp.headers.get("content-type")
            details["final_url"] = str(resp.url)

            if status_code not in expected_statuses:
                ok = False
                err = f"unexpected_status: {status_code} not in {expected_statuses}"

            if ok and expected_ct:
                ct = (resp.headers.get("content-type") or "").lower()
                if expected_ct.lower() not in ct:
                    ok = False
                    err = f"unexpected_content_type: {ct!r} missing {expected_ct!r}"

            data = None
            if ok and (json_required or json_equal):
                try:
                    data = resp.json()
                except Exception as exc:
                    ok = False
                    err = f"json_parse_error: {type(exc).__name__}: {exc}"

            if ok and json_required:
                missing: list[str] = []
                for p in json_required[:50]:
                    exists, _val = _get_path(data, p)
                    if not exists:
                        missing.append(p)
                if missing:
                    ok = False
                    err = "missing_json_paths"
                    details["missing_json_paths"] = missing[:25]

            if ok and json_equal:
                mismatches: list[str] = []
                for p, expected_val in list(json_equal.items())[:50]:
                    exists, got_val = _get_path(data, str(p))
                    if not exists:
                        mismatches.append(f"{p}: missing")
                        continue
                    if got_val != expected_val:
                        mismatches.append(f"{p}: got={got_val!r} expected={expected_val!r}")
                if mismatches:
                    ok = False
                    err = "json_value_mismatch"
                    details["json_mismatches"] = mismatches[:25]

            if ok and max_elapsed_ms_f is not None and elapsed_ms is not None and float(elapsed_ms) > max_elapsed_ms_f:
                ok = False
                err = f"slow_api: elapsed_ms={elapsed_ms:.1f} > {max_elapsed_ms_f:.1f}"
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            ok = False
            err = f"{type(exc).__name__}: {exc}"

        results.append(
            ApiContractCheckResult(
                domain=cleaned_domain,
                name=name,
                ok=ok,
                url=url,
                status_code=status_code,
                elapsed_ms=(round(float(elapsed_ms), 3) if elapsed_ms is not None else None),
                error=err,
                details=details,
            )
        )

    return results

