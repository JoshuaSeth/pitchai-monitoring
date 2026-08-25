from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin

import httpx


@dataclass(frozen=True)
class ApiContractCheckResult:
    domain: str
    name: str
    service: str | None
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


_ENV_REF_RE = re.compile(r"\$\{([A-Z0-9_]{1,64})\}")
_SAFE_CLASS_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_SAFE_SERVICE_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
_SAFE_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")


def _substitute_env_refs(text: str) -> str:
    """Replace ${VAR} references without ever logging the substituted value."""
    s = str(text or "")
    if "${" not in s:
        return s
    missing: list[str] = []

    def _replace(match: re.Match[str]) -> str:
        key = match.group(1)
        value = os.getenv(key)
        if value is None:
            missing.append(key)
            return ""
        return value

    out = _ENV_REF_RE.sub(_replace, s)
    if missing:
        raise ValueError(f"missing_env_secrets: {sorted(set(missing))}")
    return out


def _headers_with_env(headers: dict[Any, Any]) -> dict[str, str]:
    return {str(key): _substitute_env_refs(str(value)) for key, value in headers.items()}


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
        service_candidate = str(raw.get("service") or "").strip()
        service = service_candidate if _SAFE_SERVICE_RE.fullmatch(service_candidate) else None
        method = str(raw.get("method") or "GET").strip().upper()
        path = str(raw.get("path") or "").strip()
        url = str(raw.get("url") or "").strip()
        if not url:
            if not path.startswith("/"):
                path = "/" + path if path else ""
            url = urljoin(base.rstrip("/") + "/", path)
        url = _substitute_env_refs(url)
        expected_statuses = [int(x) for x in _as_list(raw.get("expected_status_codes") or raw.get("expected_status") or [200])]
        if "expected_content_type_contains" in raw:
            expected_ct_raw = raw.get("expected_content_type_contains")
            expected_ct = None if expected_ct_raw is None else str(expected_ct_raw).strip() or None
        else:
            expected_ct = "application/json"
        json_required = [str(x) for x in _as_list(raw.get("json_paths_required")) if str(x or "").strip()]
        json_equal = raw.get("json_paths_equal") if isinstance(raw.get("json_paths_equal"), dict) else {}
        failure_class_path = str(raw.get("failure_class_json_path") or "").strip()
        application_commit_path = str(raw.get("application_commit_json_path") or "").strip()
        max_elapsed_ms = raw.get("max_elapsed_ms")
        try:
            max_elapsed_ms_f = float(max_elapsed_ms) if max_elapsed_ms is not None else None
        except Exception:
            max_elapsed_ms_f = None

        req_json = raw.get("body_json") if isinstance(raw.get("body_json"), (dict, list)) else None
        req_data = raw.get("body_text") if isinstance(raw.get("body_text"), str) else None
        if isinstance(req_data, str):
            req_data = _substitute_env_refs(req_data)
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
                headers=_headers_with_env(headers),
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
            if json_required or json_equal or failure_class_path or application_commit_path:
                try:
                    data = resp.json()
                except Exception as exc:
                    if ok and (json_required or json_equal):
                        ok = False
                        err = f"json_parse_error: {type(exc).__name__}: {exc}"

            if data is not None and failure_class_path:
                exists, failure_class = _get_path(data, failure_class_path)
                if exists and isinstance(failure_class, str) and _SAFE_CLASS_RE.fullmatch(failure_class):
                    details["failure_class"] = failure_class

            if data is not None and application_commit_path:
                exists, application_commit = _get_path(data, application_commit_path)
                if (
                    exists
                    and isinstance(application_commit, str)
                    and _SAFE_COMMIT_RE.fullmatch(application_commit)
                ):
                    details["application_commit"] = application_commit

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
                service=service,
                ok=ok,
                url=url,
                status_code=status_code,
                elapsed_ms=(round(float(elapsed_ms), 3) if elapsed_ms is not None else None),
                error=err,
                details=details,
            )
        )

    return results
