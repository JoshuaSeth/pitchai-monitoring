from __future__ import annotations

import asyncio
import hashlib
import hmac
import ipaddress
import logging
import os
import secrets
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from e2e_registry import db as dbm
from e2e_registry import monitor_dashboard as md
from e2e_registry.alerts import (
    build_dispatch_prompt_for_failure,
    build_failure_telegram_message,
    build_recovery_telegram_message,
    maybe_dispatch_failure_investigation,
    maybe_send_failure_alert,
)
from e2e_registry.auth import RequestAuth, hash_token, require_admin, require_runner, require_tenant_auth
from e2e_registry.schema import (
    CreateApiKeyRequest,
    CreateTenantRequest,
    CreateTestRequest,
    DisableTestRequest,
    PatchTestRequest,
    RunnerClaimRequest,
    RunnerCompleteRequest,
)
from e2e_registry.settings import RegistrySettings
from e2e_registry.stepflow import StepFlowValidationError, parse_definition_bytes, validate_base_url, validate_definition


COOKIE_TOKEN_HASH = "e2e_token_hash"
COOKIE_MONITOR_DASH_TOKEN_HASH = "monitor_dash_token_hash"
LOGGER = logging.getLogger("e2e-registry")


_ALLOWED_TEST_KINDS = {"stepflow", "playwright_python", "puppeteer_js"}
_RESERVED_BASE_URL_HOSTS = {
    "example.com",
    "example.org",
    "example.net",
    "localhost",
    "127.0.0.1",
    "0.0.0.0",
    "::1",
}
_RESERVED_BASE_URL_SUFFIXES = (
    ".example.com",
    ".example.org",
    ".example.net",
    ".localhost",
    ".local",
    ".internal",
    ".invalid",
    ".test",
)


def _normalize_test_kind(kind: str) -> str:
    s = str(kind or "").strip().lower()
    # Backwards compatible aliases.
    aliases = {
        "stepflow": "stepflow",
        "yaml": "stepflow",
        "yml": "stepflow",
        "playwright-python": "playwright_python",
        "playwright_python": "playwright_python",
        "pw_python": "playwright_python",
        "puppeteer-js": "puppeteer_js",
        "puppeteer_js": "puppeteer_js",
        "pptr": "puppeteer_js",
    }
    out = aliases.get(s, s)
    return out if out in _ALLOWED_TEST_KINDS else ""


def _safe_filename(name: str, *, default: str) -> str:
    base = Path(str(name or "")).name
    cleaned = "".join(ch for ch in base if ch.isalnum() or ch in ("-", "_", ".", "+"))[:120].strip(".")
    return cleaned or default


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _parse_until(value: Any) -> float | None:
    # Lightweight parser compatible with service-monitoring's disabled_until rules.
    if value is None:
        return None
    if isinstance(value, (int, float)):
        ts = float(value)
        return ts if ts > 0 else None
    s = str(value or "").strip()
    if not s:
        return None
    try:
        ts = float(s)
        return ts if ts > 0 else None
    except Exception:
        pass
    # ISO-8601 parsing without extra deps: accept YYYY-MM-DD and YYYY-MM-DDTHH:MM:SSZ/offset
    try:
        from datetime import date, datetime, timezone

        s_iso = s[:-1] + "+00:00" if s.endswith("Z") else s
        try:
            dt = datetime.fromisoformat(s_iso)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.timestamp()
        except ValueError:
            d = date.fromisoformat(s)
            dt = datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
            return dt.timestamp()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"invalid_until: {exc}") from exc


def _url_host(base_url: str) -> str:
    try:
        host = (urlsplit(str(base_url or "").strip()).hostname or "").strip().lower()
    except Exception:
        host = ""
    return host.rstrip(".")


def _host_is_reserved_or_non_public(host: str) -> bool:
    h = str(host or "").strip().lower().rstrip(".")
    if not h:
        return True
    if h in _RESERVED_BASE_URL_HOSTS:
        return True
    if any(h.endswith(sfx) for sfx in _RESERVED_BASE_URL_SUFFIXES):
        return True

    try:
        ip = ipaddress.ip_address(h)
    except ValueError:
        ip = None

    if ip is not None:
        if ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified:
            return True
        return False

    # Strict mode should reject bare internal names (e.g. "my-service").
    if "." not in h:
        return True
    return False


def _load_monitored_allowlist_hosts(settings: RegistrySettings) -> set[str]:
    if not settings.base_url_allow_monitored_domains:
        return set()
    cfg = md._load_yaml(Path(str(settings.monitor_config_path or "").strip()))
    entries = md._normalize_domain_entries(cfg.get("domains"))
    hosts: set[str] = set()
    for entry in entries:
        d = str((entry or {}).get("domain") or "").strip().lower().rstrip(".")
        if d:
            hosts.add(d)
    return hosts


def create_app(settings: RegistrySettings | None = None) -> FastAPI:
    app = FastAPI(title="PitchAI E2E Registry", version="0.1.0")
    app.state.settings = settings or RegistrySettings()
    app.state.monitor_cache = {"loaded_at_ts": 0.0, "state_mtime": None, "config_mtime": None, "data": None}

    templates_dir = Path(__file__).parent / "templates"
    templates = Jinja2Templates(directory=str(templates_dir))
    app.state.templates = templates

    @app.on_event("startup")
    def _startup() -> None:
        dbm.ensure_schema(app.state.settings)
        # Ensure storage locations exist (single-host deployment).
        try:
            Path(app.state.settings.artifacts_dir).mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        try:
            Path(app.state.settings.tests_dir).mkdir(parents=True, exist_ok=True)
        except Exception:
            pass

        # Defensive cleanup: quarantine tests with disallowed hosts so they cannot keep firing.
        try:
            quarantined = _quarantine_disallowed_tests()
            if quarantined > 0:
                LOGGER.warning("Quarantined disallowed e2e tests count=%s", quarantined)
        except Exception:
            LOGGER.exception("Failed to quarantine disallowed e2e tests")

    def _strict_allowed_hosts() -> set[str]:
        settings2: RegistrySettings = app.state.settings
        allowed = {h.strip().lower().rstrip(".") for h in settings2.base_url_allowed_hosts if str(h).strip()}
        if not allowed:
            allowed = _load_monitored_allowlist_hosts(settings2)
        return allowed

    def _is_disallowed_host(host: str) -> bool:
        settings2: RegistrySettings = app.state.settings
        if not settings2.strict_base_url_policy:
            return False
        if _host_is_reserved_or_non_public(host):
            return True
        allowed = _strict_allowed_hosts()
        if allowed and host not in allowed:
            return True
        return False

    def _quarantine_disallowed_tests() -> int:
        settings2: RegistrySettings = app.state.settings
        if not settings2.strict_base_url_policy:
            return 0
        summary = dbm.status_summary(settings2)
        tests = summary.get("tests") if isinstance(summary, dict) else None
        if not isinstance(tests, list):
            return 0
        changed = 0
        for item in tests:
            if not isinstance(item, dict):
                continue
            host = _url_host(str(item.get("base_url") or ""))
            if not _is_disallowed_host(host):
                continue
            tenant_id = str(item.get("tenant_id") or "").strip()
            test_id = str(item.get("test_id") or "").strip()
            if not tenant_id or not test_id:
                continue
            ok = dbm.set_test_disabled(
                settings2,
                tenant_id=tenant_id,
                test_id=test_id,
                disabled=True,
                reason=f"auto-disabled disallowed base_url host: {host or 'unknown'}",
                until_ts=None,
            )
            if ok:
                changed += 1
        return changed

    def _validate_and_enforce_base_url(raw_base_url: str) -> str:
        base = validate_base_url(raw_base_url)
        settings2: RegistrySettings = app.state.settings
        if not settings2.strict_base_url_policy:
            return base

        host = _url_host(base)
        if _host_is_reserved_or_non_public(host):
            raise HTTPException(status_code=400, detail="base_url_not_allowed_host")

        allowed = _strict_allowed_hosts()
        if allowed and host not in allowed:
            raise HTTPException(status_code=400, detail="base_url_not_monitored_domain")
        return base

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {"ok": True, "ts": time.time()}

    @app.get("/")
    async def root(req: Request) -> RedirectResponse:
        # monitoring.pitchai.net is primarily a monitoring surface.
        return RedirectResponse(url="/dashboard", status_code=303)

    # -----------------
    # UI auth helpers
    # -----------------
    async def _ui_get_auth(req: Request) -> dbm.AuthedTenant | None:
        th = (req.cookies.get(COOKIE_TOKEN_HASH) or "").strip()
        if not th:
            return None
        return await asyncio.to_thread(dbm.get_api_key_by_hash, app.state.settings, token_hash=th)

    async def _ui_require_auth(req: Request) -> dbm.AuthedTenant:
        authed = await _ui_get_auth(req)
        if authed is None:
            raise HTTPException(status_code=401, detail="ui_not_authenticated")
        return authed

    def _redirect_to_login() -> RedirectResponse:
        return RedirectResponse(url="/ui/login", status_code=303)

    # -----------------
    # Monitoring dashboard auth (separate from tenant UI auth)
    # -----------------
    async def _dash_is_authed(req: Request) -> bool:
        settings2: RegistrySettings = app.state.settings
        if not settings2.dashboard_require_auth:
            return True

        expected: set[str] = set()
        if settings2.admin_token:
            expected.add(hash_token(settings2.admin_token))
        if settings2.monitor_token:
            expected.add(hash_token(settings2.monitor_token))

        th = (req.cookies.get(COOKIE_MONITOR_DASH_TOKEN_HASH) or "").strip()
        if th and th in expected:
            return True

        # Also allow bearer auth for programmatic access.
        token = (req.headers.get("authorization") or "").strip()
        if token.lower().startswith("bearer "):
            provided = token.split(None, 1)[1].strip()
            if settings2.admin_token and hmac.compare_digest(provided, settings2.admin_token.strip()):
                return True
            if settings2.monitor_token and hmac.compare_digest(provided, settings2.monitor_token.strip()):
                return True

        return False

    async def _dash_require_auth(req: Request) -> None:
        if not await _dash_is_authed(req):
            raise HTTPException(status_code=401, detail="dashboard_unauthorized")

    def _dash_redirect_to_login() -> RedirectResponse:
        return RedirectResponse(url="/dashboard/login", status_code=303)

    async def _get_monitor_data() -> md.MonitorData:
        settings2: RegistrySettings = app.state.settings
        cache = getattr(app.state, "monitor_cache", None)
        if not isinstance(cache, dict):
            cache = {"loaded_at_ts": 0.0, "state_mtime": None, "config_mtime": None, "data": None}
            app.state.monitor_cache = cache

        def _mtime(path: str) -> float | None:
            try:
                return float(os.stat(path).st_mtime)
            except Exception:
                return None

        now_ts = time.time()
        ttl_seconds = 5.0
        state_mtime = _mtime(settings2.monitor_state_path)
        config_mtime = _mtime(settings2.monitor_config_path)

        data = cache.get("data")
        try:
            loaded_at = float(cache.get("loaded_at_ts") or 0.0)
        except Exception:
            loaded_at = 0.0

        if (
            isinstance(data, md.MonitorData)
            and cache.get("state_mtime") == state_mtime
            and cache.get("config_mtime") == config_mtime
            and (now_ts - loaded_at) < ttl_seconds
        ):
            return data

        data2 = md.load_monitor_data(
            state_path=settings2.monitor_state_path,
            config_path=settings2.monitor_config_path,
        )
        cache["data"] = data2
        cache["loaded_at_ts"] = now_ts
        cache["state_mtime"] = state_mtime
        cache["config_mtime"] = config_mtime
        return data2

    # -----------------
    # UI routes
    # -----------------
    @app.get("/ui/login", response_class=HTMLResponse)
    async def ui_login(req: Request) -> HTMLResponse:
        return app.state.templates.TemplateResponse("login.html", {"request": req, "error": None})

    @app.post("/ui/login")
    async def ui_login_post(req: Request, api_key: str = Form("")):
        token = (api_key or "").strip()
        if not token:
            return app.state.templates.TemplateResponse(
                "login.html", {"request": req, "error": "Missing API key"}
            )
        th = hash_token(token)
        authed = await asyncio.to_thread(dbm.get_api_key_by_hash, app.state.settings, token_hash=th)
        if authed is None:
            return app.state.templates.TemplateResponse(
                "login.html", {"request": req, "error": "Invalid API key"}
            )
        resp = RedirectResponse(url="/ui/tests", status_code=303)
        resp.set_cookie(COOKIE_TOKEN_HASH, th, httponly=True, samesite="lax")
        return resp

    @app.get("/ui/logout")
    async def ui_logout() -> RedirectResponse:
        resp = RedirectResponse(url="/ui/login", status_code=303)
        resp.delete_cookie(COOKIE_TOKEN_HASH)
        return resp

    # -----------------
    # Monitoring dashboard routes
    # -----------------
    @app.get("/dashboard/login", response_class=HTMLResponse)
    async def dash_login(req: Request) -> HTMLResponse:
        if await _dash_is_authed(req):
            return RedirectResponse(url="/dashboard", status_code=303)
        return app.state.templates.TemplateResponse("dashboard_login.html", {"request": req, "error": None})

    @app.post("/dashboard/login")
    async def dash_login_post(req: Request, monitor_key: str = Form("")):
        token = (monitor_key or "").strip()
        if not token:
            return app.state.templates.TemplateResponse(
                "dashboard_login.html", {"request": req, "error": "Missing monitoring token"}
            )
        settings2: RegistrySettings = app.state.settings
        ok = False
        if settings2.admin_token and hmac.compare_digest(token, settings2.admin_token.strip()):
            ok = True
        if settings2.monitor_token and hmac.compare_digest(token, settings2.monitor_token.strip()):
            ok = True
        if not ok:
            return app.state.templates.TemplateResponse(
                "dashboard_login.html", {"request": req, "error": "Invalid monitoring token"}
            )
        resp = RedirectResponse(url="/dashboard", status_code=303)
        resp.set_cookie(
            COOKIE_MONITOR_DASH_TOKEN_HASH,
            hash_token(token),
            httponly=True,
            samesite="lax",
            secure=(req.url.scheme == "https"),
        )
        return resp

    @app.get("/dashboard/logout")
    async def dash_logout() -> RedirectResponse:
        resp = RedirectResponse(url="/dashboard/login", status_code=303)
        resp.delete_cookie(COOKIE_MONITOR_DASH_TOKEN_HASH)
        return resp

    @app.get("/dashboard", response_class=HTMLResponse)
    async def dashboard(req: Request) -> HTMLResponse:
        if not await _dash_is_authed(req):
            return _dash_redirect_to_login()
        return app.state.templates.TemplateResponse("dashboard.html", {"request": req, "title": "Monitoring"})

    @app.get("/ui/tests", response_class=HTMLResponse)
    async def ui_tests(req: Request) -> HTMLResponse:
        authed = await _ui_get_auth(req)
        if authed is None:
            return _redirect_to_login()
        tests = await asyncio.to_thread(dbm.list_tests, app.state.settings, tenant_id=authed.tenant_id)
        # Normalize sqlite rows (ints) into something templates can use.
        for t in tests:
            for k in ("effective_ok", "fail_streak", "success_streak"):
                try:
                    if t.get(k) is not None:
                        t[k] = int(t[k])
                except Exception:
                    pass
        return app.state.templates.TemplateResponse(
            "tests.html",
            {"request": req, "tenant_id": authed.tenant_id, "tests": tests},
        )

    @app.get("/ui/tests/{test_id}", response_class=HTMLResponse)
    async def ui_test_detail(req: Request, test_id: str, msg: str | None = None) -> HTMLResponse:
        authed = await _ui_get_auth(req)
        if authed is None:
            return _redirect_to_login()
        test = await asyncio.to_thread(dbm.get_test, app.state.settings, tenant_id=authed.tenant_id, test_id=test_id)
        if not test:
            raise HTTPException(status_code=404, detail="test_not_found")
        runs = await asyncio.to_thread(dbm.list_runs, app.state.settings, tenant_id=authed.tenant_id, test_id=test_id, limit=50)
        kind = str(test.get("test_kind") or "stepflow").strip().lower() or "stepflow"
        definition_json = test.get("definition_json") or ""
        source_text: str | None = None
        source_filename: str | None = None
        source_relpath = str(test.get("source_relpath") or "").strip()
        if kind != "stepflow" and source_relpath:
            try:
                base = Path(app.state.settings.tests_dir).resolve()
                fp = (base / source_relpath).resolve()
                if base in fp.parents and fp.exists() and fp.is_file():
                    source_filename = fp.name
                    source_text = fp.read_text(encoding="utf-8", errors="replace")
                    if len(source_text) > 80_000:
                        source_text = source_text[:80_000] + "\n...truncated..."
            except Exception:
                source_text = None
        return app.state.templates.TemplateResponse(
            "test_detail.html",
            {
                "request": req,
                "test": test,
                "runs": runs,
                "definition_json": definition_json,
                "source_text": source_text,
                "source_filename": source_filename,
                "msg": msg,
            },
        )

    @app.post("/ui/tests/{test_id}/run")
    async def ui_test_run_now(req: Request, test_id: str) -> RedirectResponse:
        authed = await _ui_require_auth(req)
        ok = await asyncio.to_thread(dbm.trigger_run_now, app.state.settings, tenant_id=authed.tenant_id, test_id=test_id)
        msg = "Run triggered" if ok else "Failed to trigger run"
        return RedirectResponse(url=f"/ui/tests/{test_id}?msg={msg}", status_code=303)

    @app.post("/ui/tests/{test_id}/disable")
    async def ui_test_disable(
        req: Request,
        test_id: str,
        reason: str = Form("temporary disable"),
        until: str = Form(""),
    ) -> RedirectResponse:
        authed = await _ui_require_auth(req)
        try:
            until_ts = _parse_until(until)
        except HTTPException:
            return RedirectResponse(url=f"/ui/tests/{test_id}?msg=Invalid+until+value", status_code=303)
        ok = await asyncio.to_thread(
            dbm.set_test_disabled,
            app.state.settings,
            tenant_id=authed.tenant_id,
            test_id=test_id,
            disabled=True,
            reason=reason,
            until_ts=until_ts,
        )
        msg = "Disabled" if ok else "Disable failed"
        return RedirectResponse(url=f"/ui/tests/{test_id}?msg={msg}", status_code=303)

    @app.post("/ui/tests/{test_id}/enable")
    async def ui_test_enable(req: Request, test_id: str) -> RedirectResponse:
        authed = await _ui_require_auth(req)
        ok = await asyncio.to_thread(
            dbm.set_test_disabled,
            app.state.settings,
            tenant_id=authed.tenant_id,
            test_id=test_id,
            disabled=False,
            reason=None,
            until_ts=None,
        )
        msg = "Enabled" if ok else "Enable failed"
        return RedirectResponse(url=f"/ui/tests/{test_id}?msg={msg}", status_code=303)

    @app.post("/ui/tests/{test_id}/source")
    async def ui_update_test_source(
        req: Request,
        test_id: str,
        file: UploadFile = File(...),
    ) -> RedirectResponse:
        """
        Replace the stored source for a code-based test via UI (multipart file upload).
        """
        authed = await _ui_require_auth(req)
        settings2: RegistrySettings = app.state.settings

        test = await asyncio.to_thread(dbm.get_test, settings2, tenant_id=authed.tenant_id, test_id=test_id)
        if not test:
            return RedirectResponse(url=f"/ui/tests/{test_id}?msg=Test+not+found", status_code=303)

        kind = str(test.get("test_kind") or "stepflow").strip().lower() or "stepflow"
        if kind == "stepflow":
            return RedirectResponse(url=f"/ui/tests/{test_id}?msg=StepFlow+tests+use+definition+updates", status_code=303)

        raw = await file.read()
        if int(settings2.max_upload_bytes) > 0 and len(raw) > int(settings2.max_upload_bytes):
            return RedirectResponse(url=f"/ui/tests/{test_id}?msg=File+too+large", status_code=303)

        default_fn = "test.py" if kind == "playwright_python" else "test.js"
        source_filename = _safe_filename(file.filename or "", default=default_fn)
        if kind == "playwright_python" and not source_filename.endswith(".py"):
            return RedirectResponse(url=f"/ui/tests/{test_id}?msg=Expected+.py+file", status_code=303)
        if kind == "puppeteer_js" and not (source_filename.endswith(".js") or source_filename.endswith(".mjs")):
            return RedirectResponse(url=f"/ui/tests/{test_id}?msg=Expected+.js+or+.mjs+file", status_code=303)

        base_dir = Path(settings2.tests_dir).resolve()
        rel = Path(authed.tenant_id) / str(test_id).strip() / source_filename
        fp = (base_dir / rel).resolve()
        if base_dir not in fp.parents:
            return RedirectResponse(url=f"/ui/tests/{test_id}?msg=Invalid+upload+path", status_code=303)
        try:
            fp.parent.mkdir(parents=True, exist_ok=True)
            fp.write_bytes(raw)
        except Exception as exc:
            return RedirectResponse(url=f"/ui/tests/{test_id}?msg=Write+failed:+{exc}", status_code=303)

        # Best-effort cleanup of the old file when it changes.
        old_rel = str(test.get("source_relpath") or "").strip()
        if old_rel and old_rel != str(rel):
            try:
                old_fp = (base_dir / old_rel).resolve()
                if base_dir in old_fp.parents and old_fp.exists() and old_fp.is_file():
                    old_fp.unlink(missing_ok=True)
            except Exception:
                pass

        ok = await asyncio.to_thread(
            dbm.update_test_source,
            settings2,
            tenant_id=authed.tenant_id,
            test_id=test_id,
            source_relpath=str(rel),
            source_filename=source_filename,
            source_sha256=_sha256_hex(raw),
            source_content_type=file.content_type,
        )
        msg = "Source updated" if ok else "Update failed"
        return RedirectResponse(url=f"/ui/tests/{test_id}?msg={msg}", status_code=303)

    @app.get("/ui/runs/{run_id}", response_class=HTMLResponse)
    async def ui_run_detail(req: Request, run_id: str) -> HTMLResponse:
        authed = await _ui_get_auth(req)
        if authed is None:
            return _redirect_to_login()
        run = await asyncio.to_thread(dbm.get_run, app.state.settings, tenant_id=authed.tenant_id, run_id=run_id)
        if not run:
            raise HTTPException(status_code=404, detail="run_not_found")
        artifacts = {}
        try:
            artifacts = (dbm._json_loads(run.get("artifacts_json")) or {}) if isinstance(run.get("artifacts_json"), (str, dict)) else {}
        except Exception:
            artifacts = {}
        return app.state.templates.TemplateResponse(
            "run_detail.html",
            {"request": req, "run": run, "artifacts": artifacts},
        )

    @app.get("/ui/upload", response_class=HTMLResponse)
    async def ui_upload(req: Request) -> HTMLResponse:
        authed = await _ui_get_auth(req)
        if authed is None:
            return _redirect_to_login()
        return app.state.templates.TemplateResponse("upload.html", {"request": req, "error": None, "msg": None})

    @app.post("/ui/upload", response_class=HTMLResponse)
    async def ui_upload_post(
        req: Request,
        name: str = Form(""),
        base_url: str = Form(""),
        kind: str = Form("stepflow"),
        interval_seconds: int = Form(300),
        file: UploadFile = File(...),
    ) -> HTMLResponse:
        authed = await _ui_get_auth(req)
        if authed is None:
            return _redirect_to_login()

        raw = await file.read()
        settings2: RegistrySettings = app.state.settings
        kind2 = _normalize_test_kind(kind)
        if not kind2:
            return app.state.templates.TemplateResponse(
                "upload.html", {"request": req, "error": "invalid_kind", "msg": None}
            )
        if int(settings2.max_upload_bytes) > 0 and len(raw) > int(settings2.max_upload_bytes):
            return app.state.templates.TemplateResponse(
                "upload.html", {"request": req, "error": "file_too_large", "msg": None}
            )
        try:
            base = _validate_and_enforce_base_url(base_url)
        except HTTPException as exc:
            return app.state.templates.TemplateResponse(
                "upload.html", {"request": req, "error": str(exc.detail), "msg": None}
            )

        defn = None
        tname = (name or "").strip()
        source_relpath = None
        source_filename = None
        source_sha = None
        content_type = file.content_type
        test_id_override: str | None = None

        if kind2 == "stepflow":
            try:
                defn_raw = parse_definition_bytes(raw, content_type=file.content_type)
                defn = validate_definition(defn_raw)
            except StepFlowValidationError as exc:
                return app.state.templates.TemplateResponse(
                    "upload.html", {"request": req, "error": str(exc), "msg": None}
                )
            tname = tname or str(defn.get("name") or "test")
        else:
            # Code-based tests: store the uploaded file on disk and run via sandbox runner.
            default_fn = "test.py" if kind2 == "playwright_python" else "test.js"
            source_filename = _safe_filename(file.filename or "", default=default_fn)
            if kind2 == "playwright_python" and not source_filename.endswith(".py"):
                return app.state.templates.TemplateResponse(
                    "upload.html", {"request": req, "error": "python_test_must_be_.py", "msg": None}
                )
            if kind2 == "puppeteer_js" and not (source_filename.endswith(".js") or source_filename.endswith(".mjs")):
                return app.state.templates.TemplateResponse(
                    "upload.html", {"request": req, "error": "puppeteer_test_must_be_.js", "msg": None}
                )
            tname = tname or source_filename

            test_id = str(uuid.uuid4())
            base_dir = Path(settings2.tests_dir).resolve()
            rel = Path(authed.tenant_id) / test_id / source_filename
            fp = (base_dir / rel).resolve()
            if base_dir not in fp.parents:
                return app.state.templates.TemplateResponse(
                    "upload.html", {"request": req, "error": "invalid_upload_path", "msg": None}
                )
            try:
                fp.parent.mkdir(parents=True, exist_ok=True)
                fp.write_bytes(raw)
            except Exception as exc:
                return app.state.templates.TemplateResponse(
                    "upload.html", {"request": req, "error": f"write_failed: {exc}", "msg": None}
                )
            source_relpath = str(rel)
            source_sha = _sha256_hex(raw)
            test_id_override = test_id

        try:
            created = await asyncio.to_thread(
                dbm.insert_test,
                app.state.settings,
                tenant_id=authed.tenant_id,
                name=tname,
                base_url=base,
                test_kind=kind2,
                definition=defn,
                source_relpath=source_relpath,
                source_filename=source_filename,
                source_sha256=source_sha,
                source_content_type=content_type,
                test_id=test_id_override,
                interval_seconds=int(interval_seconds),
                timeout_seconds=45,
                jitter_seconds=30,
                down_after_failures=2,
                up_after_successes=2,
                notify_on_recovery=False,
                dispatch_on_failure=False,
            )
        except Exception as exc:
            return app.state.templates.TemplateResponse(
                "upload.html", {"request": req, "error": f"db_error: {exc}", "msg": None}
            )

        msg = f"Created test {created.get('id')}"
        return app.state.templates.TemplateResponse(
            "upload.html", {"request": req, "error": None, "msg": msg}
        )

    # -----------------
    # API routes
    # -----------------
    @app.get("/api/v1/monitoring/summary")
    async def api_monitoring_summary(req: Request, range: str = "24h") -> dict[str, Any]:  # noqa: A002
        await _dash_require_auth(req)
        settings2: RegistrySettings = app.state.settings
        now_ts = time.time()
        since_ts, until_ts = md.resolve_range(now_ts=now_ts, range_label=range)

        data = await _get_monitor_data()
        e2e_status = await asyncio.to_thread(dbm.status_summary, settings2)
        e2e_dispatch = await asyncio.to_thread(dbm.list_dispatch_runs, settings2, limit=80)

        summary = md.build_dashboard_summary(
            data=data,
            now_ts=now_ts,
            e2e_status_summary=e2e_status,
            e2e_dispatch_runs=e2e_dispatch,
        )

        # Filter events/dispatch to the selected range for a smaller, more relevant payload.
        events = summary.get("events") if isinstance(summary.get("events"), list) else []
        events2: list[dict[str, Any]] = []
        for e in events:
            if not isinstance(e, dict):
                continue
            try:
                ts = float(e.get("ts") or 0.0)
            except Exception:
                continue
            if ts < float(since_ts) or ts > float(until_ts):
                continue
            events2.append(e)
        summary["events"] = events2

        dispatch = summary.get("dispatch") if isinstance(summary.get("dispatch"), dict) else {}
        recent = dispatch.get("recent") if isinstance(dispatch.get("recent"), list) else []
        recent2: list[dict[str, Any]] = []
        for r in recent:
            if not isinstance(r, dict):
                continue
            try:
                ts = float(r.get("ts") or 0.0)
            except Exception:
                ts = 0.0
            if ts and (ts < float(since_ts) or ts > float(until_ts)):
                continue
            recent2.append(r)
        dispatch["recent"] = recent2
        summary["dispatch"] = dispatch

        return summary

    @app.get("/api/v1/monitoring/domains/{domain}/series")
    async def api_domain_series(
        domain: str,
        req: Request,
        range: str = "24h",  # noqa: A002
        since_ts: float | None = None,
        until_ts: float | None = None,
    ) -> dict[str, Any]:
        await _dash_require_auth(req)
        settings2: RegistrySettings = app.state.settings
        now_ts = time.time()
        if since_ts is None or until_ts is None:
            s, u = md.resolve_range(now_ts=now_ts, range_label=range)
            since_ts = float(s) if since_ts is None else float(since_ts)
            until_ts = float(u) if until_ts is None else float(until_ts)
        if float(until_ts) < float(since_ts):
            raise HTTPException(status_code=400, detail="invalid_range")
        data = await _get_monitor_data()
        return md.domain_timeseries(
            data=data,
            domain=domain,
            since_ts=float(since_ts),
            until_ts=float(until_ts),
            max_points=int(settings2.dashboard_max_points),
        )

    @app.get("/api/v1/monitoring/signals/{signal}/series")
    async def api_signal_series(
        signal: str,
        req: Request,
        range: str = "24h",  # noqa: A002
        since_ts: float | None = None,
        until_ts: float | None = None,
    ) -> dict[str, Any]:
        await _dash_require_auth(req)
        settings2: RegistrySettings = app.state.settings
        now_ts = time.time()
        if since_ts is None or until_ts is None:
            s, u = md.resolve_range(now_ts=now_ts, range_label=range)
            since_ts = float(s) if since_ts is None else float(since_ts)
            until_ts = float(u) if until_ts is None else float(until_ts)
        if float(until_ts) < float(since_ts):
            raise HTTPException(status_code=400, detail="invalid_range")
        data = await _get_monitor_data()
        return md.signal_timeseries(
            data=data,
            signal=signal,
            since_ts=float(since_ts),
            until_ts=float(until_ts),
            max_points=int(settings2.dashboard_max_points),
        )

    @app.post("/api/v1/admin/tenants")
    async def api_create_tenant(_auth: None = Depends(require_admin), req: CreateTenantRequest | None = None) -> dict[str, Any]:
        if req is None:
            raise HTTPException(status_code=400, detail="missing_body")
        tenant = await asyncio.to_thread(dbm.create_tenant, app.state.settings, name=req.name)
        return {"ok": True, "tenant": tenant}

    @app.post("/api/v1/admin/api_keys")
    async def api_create_api_key(_auth: None = Depends(require_admin), req: CreateApiKeyRequest | None = None) -> dict[str, Any]:
        if req is None:
            raise HTTPException(status_code=400, detail="missing_body")
        token = secrets.token_urlsafe(32)
        th = hash_token(token)
        rec = await asyncio.to_thread(
            dbm.create_api_key,
            app.state.settings,
            tenant_id=req.tenant_id,
            name=req.name,
            token_hash=th,
        )
        return {"ok": True, "api_key": rec, "token": token}

    @app.post("/api/v1/tests")
    async def api_create_test(auth: RequestAuth = Depends(require_tenant_auth), req: CreateTestRequest | None = None) -> dict[str, Any]:
        if req is None:
            raise HTTPException(status_code=400, detail="missing_body")
        try:
            base = _validate_and_enforce_base_url(req.base_url)
            defn = validate_definition(req.definition)
        except StepFlowValidationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        created = await asyncio.to_thread(
            dbm.insert_test,
            app.state.settings,
            tenant_id=auth.tenant_id,
            name=req.name,
            base_url=base,
            test_kind="stepflow",
            definition=defn,
            interval_seconds=req.interval_seconds,
            timeout_seconds=req.timeout_seconds,
            jitter_seconds=req.jitter_seconds,
            down_after_failures=req.down_after_failures,
            up_after_successes=req.up_after_successes,
            notify_on_recovery=bool(req.notify_on_recovery),
            dispatch_on_failure=bool(req.dispatch_on_failure),
        )
        return {"ok": True, "test": created}

    @app.post("/api/v1/tests/upload")
    async def api_upload_test(
        req: Request,
        auth: RequestAuth = Depends(require_tenant_auth),
        name: str = Form(""),
        base_url: str = Form(""),
        kind: str = Form(""),
        interval_seconds: int = Form(300),
        timeout_seconds: int = Form(45),
        jitter_seconds: int = Form(30),
        down_after_failures: int = Form(2),
        up_after_successes: int = Form(2),
        notify_on_recovery: str = Form("0"),
        dispatch_on_failure: str = Form("0"),
        file: UploadFile = File(...),
    ) -> dict[str, Any]:
        """
        Upload a single-file E2E test:
        - kind=playwright_python: a `.py` file that defines `async def run(page, base_url, artifacts_dir)`
        - kind=puppeteer_js: a `.js`/`.mjs` file that exports `async function run({ page, baseUrl, artifactsDir })`

        This is the main "external devs submit files via API" workflow.
        """
        settings2: RegistrySettings = app.state.settings
        kind2 = _normalize_test_kind(kind)
        if not kind2:
            raise HTTPException(status_code=400, detail="invalid_kind")
        raw = await file.read()
        if int(settings2.max_upload_bytes) > 0 and len(raw) > int(settings2.max_upload_bytes):
            raise HTTPException(status_code=413, detail="file_too_large")

        base = _validate_and_enforce_base_url(base_url)
        notify = str(notify_on_recovery or "").strip().lower() in {"1", "true", "yes", "y", "on"}
        dispatch = str(dispatch_on_failure or "").strip().lower() in {"1", "true", "yes", "y", "on"}

        # StepFlow via upload is supported for convenience, but code-based kinds are the primary goal.
        defn = None
        source_relpath = None
        source_filename = None
        source_sha = None
        test_id_override: str | None = None

        if kind2 == "stepflow":
            try:
                defn_raw = parse_definition_bytes(raw, content_type=file.content_type)
                defn = validate_definition(defn_raw)
            except StepFlowValidationError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            tname = (name or "").strip() or str(defn.get("name") or "test")
        else:
            default_fn = "test.py" if kind2 == "playwright_python" else "test.js"
            source_filename = _safe_filename(file.filename or "", default=default_fn)
            if kind2 == "playwright_python" and not source_filename.endswith(".py"):
                raise HTTPException(status_code=400, detail="python_test_must_be_.py")
            if kind2 == "puppeteer_js" and not (source_filename.endswith(".js") or source_filename.endswith(".mjs")):
                raise HTTPException(status_code=400, detail="puppeteer_test_must_be_.js")

            tname = (name or "").strip() or source_filename
            test_id_override = str(uuid.uuid4())
            base_dir = Path(settings2.tests_dir).resolve()
            rel = Path(auth.tenant_id) / test_id_override / source_filename
            fp = (base_dir / rel).resolve()
            if base_dir not in fp.parents:
                raise HTTPException(status_code=400, detail="invalid_upload_path")
            fp.parent.mkdir(parents=True, exist_ok=True)
            fp.write_bytes(raw)

            source_relpath = str(rel)
            source_sha = _sha256_hex(raw)

        created = await asyncio.to_thread(
            dbm.insert_test,
            app.state.settings,
            tenant_id=auth.tenant_id,
            name=tname,
            base_url=base,
            test_id=test_id_override,
            test_kind=kind2,
            definition=defn,
            source_relpath=source_relpath,
            source_filename=source_filename,
            source_sha256=source_sha,
            source_content_type=file.content_type,
            interval_seconds=int(interval_seconds),
            timeout_seconds=int(timeout_seconds),
            jitter_seconds=int(jitter_seconds),
            down_after_failures=int(down_after_failures),
            up_after_successes=int(up_after_successes),
            notify_on_recovery=bool(notify),
            dispatch_on_failure=bool(dispatch),
        )
        return {"ok": True, "test": created}

    @app.get("/api/v1/tests")
    async def api_list_tests(auth: RequestAuth = Depends(require_tenant_auth)) -> dict[str, Any]:
        tests = await asyncio.to_thread(dbm.list_tests, app.state.settings, tenant_id=auth.tenant_id)
        return {"ok": True, "tests": tests}

    @app.get("/api/v1/tests/{test_id}")
    async def api_get_test(test_id: str, auth: RequestAuth = Depends(require_tenant_auth)) -> dict[str, Any]:
        test = await asyncio.to_thread(dbm.get_test, app.state.settings, tenant_id=auth.tenant_id, test_id=test_id)
        if not test:
            raise HTTPException(status_code=404, detail="not_found")
        return {"ok": True, "test": test}

    @app.get("/api/v1/tests/{test_id}/source")
    async def api_get_test_source(test_id: str, auth: RequestAuth = Depends(require_tenant_auth)) -> FileResponse:
        test = await asyncio.to_thread(dbm.get_test, app.state.settings, tenant_id=auth.tenant_id, test_id=test_id)
        if not test:
            raise HTTPException(status_code=404, detail="not_found")
        kind = str(test.get("test_kind") or "stepflow").strip().lower() or "stepflow"
        if kind == "stepflow":
            # Return definition JSON as a small downloadable artifact.
            txt = str(test.get("definition_json") or "").strip() or "{}"
            base = Path(app.state.settings.tests_dir).resolve()
            tmp = (base / auth.tenant_id / test_id / "definition.json").resolve()
            if base not in tmp.parents:
                raise HTTPException(status_code=400, detail="invalid_path")
            tmp.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(txt, encoding="utf-8", errors="replace")
            return FileResponse(str(tmp), media_type="application/json")

        rel = str(test.get("source_relpath") or "").strip()
        if not rel:
            raise HTTPException(status_code=404, detail="source_missing")
        base = Path(app.state.settings.tests_dir).resolve()
        fp = (base / rel).resolve()
        if base not in fp.parents:
            raise HTTPException(status_code=400, detail="invalid_path")
        if not fp.exists() or not fp.is_file():
            raise HTTPException(status_code=404, detail="source_not_found")
        return FileResponse(str(fp))

    @app.post("/api/v1/tests/{test_id}/source")
    async def api_update_test_source(
        test_id: str,
        auth: RequestAuth = Depends(require_tenant_auth),
        file: UploadFile = File(...),
    ) -> dict[str, Any]:
        """
        Replace the stored test source for a code-based test.
        """
        settings2: RegistrySettings = app.state.settings
        test = await asyncio.to_thread(dbm.get_test, settings2, tenant_id=auth.tenant_id, test_id=test_id)
        if not test:
            raise HTTPException(status_code=404, detail="not_found")
        kind = str(test.get("test_kind") or "stepflow").strip().lower() or "stepflow"
        if kind == "stepflow":
            raise HTTPException(status_code=400, detail="stepflow_source_updates_use_patch_definition")

        raw = await file.read()
        if int(settings2.max_upload_bytes) > 0 and len(raw) > int(settings2.max_upload_bytes):
            raise HTTPException(status_code=413, detail="file_too_large")

        default_fn = "test.py" if kind == "playwright_python" else "test.js"
        source_filename = _safe_filename(file.filename or "", default=default_fn)
        if kind == "playwright_python" and not source_filename.endswith(".py"):
            raise HTTPException(status_code=400, detail="python_test_must_be_.py")
        if kind == "puppeteer_js" and not (source_filename.endswith(".js") or source_filename.endswith(".mjs")):
            raise HTTPException(status_code=400, detail="puppeteer_test_must_be_.js")

        base_dir = Path(settings2.tests_dir).resolve()
        rel = Path(auth.tenant_id) / str(test_id).strip() / source_filename
        fp = (base_dir / rel).resolve()
        if base_dir not in fp.parents:
            raise HTTPException(status_code=400, detail="invalid_upload_path")
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_bytes(raw)

        # Best-effort cleanup of the old file when it changes.
        old_rel = str(test.get("source_relpath") or "").strip()
        if old_rel and old_rel != str(rel):
            try:
                old_fp = (base_dir / old_rel).resolve()
                if base_dir in old_fp.parents and old_fp.exists() and old_fp.is_file():
                    old_fp.unlink(missing_ok=True)
            except Exception:
                pass

        ok = await asyncio.to_thread(
            dbm.update_test_source,
            settings2,
            tenant_id=auth.tenant_id,
            test_id=test_id,
            source_relpath=str(rel),
            source_filename=source_filename,
            source_sha256=_sha256_hex(raw),
            source_content_type=file.content_type,
        )
        if not ok:
            raise HTTPException(status_code=404, detail="not_found")
        return {"ok": True}

    @app.patch("/api/v1/tests/{test_id}")
    async def api_patch_test(test_id: str, auth: RequestAuth = Depends(require_tenant_auth), req: PatchTestRequest | None = None) -> dict[str, Any]:
        if req is None:
            raise HTTPException(status_code=400, detail="missing_body")
        patch: dict[str, Any] = req.model_dump(exclude_unset=True)
        if "base_url" in patch and patch["base_url"] is not None:
            patch["base_url"] = _validate_and_enforce_base_url(patch["base_url"])
        if "definition" in patch and patch["definition"] is not None:
            patch["definition"] = validate_definition(patch["definition"])
        ok = await asyncio.to_thread(dbm.patch_test, app.state.settings, tenant_id=auth.tenant_id, test_id=test_id, patch=patch)
        if not ok:
            raise HTTPException(status_code=404, detail="not_found")
        test = await asyncio.to_thread(dbm.get_test, app.state.settings, tenant_id=auth.tenant_id, test_id=test_id)
        return {"ok": True, "test": test}

    @app.post("/api/v1/tests/{test_id}/disable")
    async def api_disable_test(test_id: str, auth: RequestAuth = Depends(require_tenant_auth), req: DisableTestRequest | None = None) -> dict[str, Any]:
        if req is None:
            raise HTTPException(status_code=400, detail="missing_body")
        until_ts = _parse_until(req.until)
        ok = await asyncio.to_thread(
            dbm.set_test_disabled,
            app.state.settings,
            tenant_id=auth.tenant_id,
            test_id=test_id,
            disabled=True,
            reason=req.reason,
            until_ts=until_ts,
        )
        if not ok:
            raise HTTPException(status_code=404, detail="not_found")
        return {"ok": True}

    @app.post("/api/v1/tests/{test_id}/enable")
    async def api_enable_test(test_id: str, auth: RequestAuth = Depends(require_tenant_auth)) -> dict[str, Any]:
        ok = await asyncio.to_thread(
            dbm.set_test_disabled,
            app.state.settings,
            tenant_id=auth.tenant_id,
            test_id=test_id,
            disabled=False,
            reason=None,
            until_ts=None,
        )
        if not ok:
            raise HTTPException(status_code=404, detail="not_found")
        return {"ok": True}

    @app.post("/api/v1/tests/{test_id}/run")
    async def api_run_now(test_id: str, auth: RequestAuth = Depends(require_tenant_auth)) -> dict[str, Any]:
        ok = await asyncio.to_thread(dbm.trigger_run_now, app.state.settings, tenant_id=auth.tenant_id, test_id=test_id)
        if not ok:
            raise HTTPException(status_code=404, detail="not_found")
        return {"ok": True}

    @app.get("/api/v1/tests/{test_id}/runs")
    async def api_list_runs(test_id: str, limit: int = 50, auth: RequestAuth = Depends(require_tenant_auth)) -> dict[str, Any]:
        runs = await asyncio.to_thread(dbm.list_runs, app.state.settings, tenant_id=auth.tenant_id, test_id=test_id, limit=limit)
        return {"ok": True, "runs": runs}

    @app.get("/api/v1/runs/{run_id}")
    async def api_get_run(run_id: str, auth: RequestAuth = Depends(require_tenant_auth)) -> dict[str, Any]:
        run = await asyncio.to_thread(dbm.get_run, app.state.settings, tenant_id=auth.tenant_id, run_id=run_id)
        if not run:
            raise HTTPException(status_code=404, detail="not_found")
        return {"ok": True, "run": run}

    @app.get("/api/v1/runs/{run_id}/artifacts/{name}")
    async def api_get_artifact(run_id: str, name: str, auth: RequestAuth = Depends(require_tenant_auth)) -> FileResponse:
        run = await asyncio.to_thread(dbm.get_run, app.state.settings, tenant_id=auth.tenant_id, run_id=run_id)
        if not run:
            raise HTTPException(status_code=404, detail="run_not_found")
        # Artifacts are stored on disk under {artifacts_dir}/{tenant}/{test}/{run}/...
        tenant_id = auth.tenant_id
        test_id = str(run.get("test_id") or "").strip()
        if not test_id:
            raise HTTPException(status_code=404, detail="test_not_found")
        base = Path(app.state.settings.artifacts_dir).resolve()
        file_path = (base / tenant_id / test_id / run_id / name).resolve()
        if base not in file_path.parents:
            raise HTTPException(status_code=400, detail="invalid_artifact_path")
        if not file_path.exists() or not file_path.is_file():
            raise HTTPException(status_code=404, detail="artifact_not_found")
        return FileResponse(str(file_path))

    @app.get("/api/v1/status/summary")
    async def api_status_summary(req: Request) -> dict[str, Any]:
        """
        Returns either:
        - global summary (admin token), or
        - global summary (monitor token), or
        - tenant-only summary (valid tenant token)
        """
        token = (req.headers.get("authorization") or "").strip()
        settings2: RegistrySettings = app.state.settings

        # Admin/monitor path
        if token.lower().startswith("bearer "):
            provided = token.split(None, 1)[1].strip()
            if settings2.admin_token and hmac.compare_digest(provided, settings2.admin_token.strip()):
                return await asyncio.to_thread(dbm.status_summary, settings2)
            if settings2.monitor_token and hmac.compare_digest(provided, settings2.monitor_token.strip()):
                return await asyncio.to_thread(dbm.status_summary, settings2)

        # Tenant path
        try:
            auth = require_tenant_auth(req, settings2)
        except HTTPException as exc:
            raise HTTPException(status_code=401, detail="unauthorized") from exc
        summary = await asyncio.to_thread(dbm.status_summary, settings2)
        tests = summary.get("tests") if isinstance(summary.get("tests"), list) else []
        tests2 = [t for t in tests if str(t.get("tenant_id") or "") == auth.tenant_id]
        failing: list[dict[str, Any]] = []
        for t in tests2:
            v = t.get("effective_ok")
            try:
                v_i = 1 if v is None else int(v)
            except Exception:
                v_i = 1
            if v_i == 0:
                failing.append(t)
        return {"ok": True, "total_tests": len(tests2), "failing_tests": len(failing), "tests": tests2}

    # -----------------
    # Runner API
    # -----------------
    @app.post("/api/v1/runner/claim")
    async def runner_claim(_auth: None = Depends(require_runner), req: RunnerClaimRequest | None = None) -> dict[str, Any]:
        max_runs = int(req.max_runs) if req is not None else 1
        claimed = await asyncio.to_thread(dbm.claim_due_runs, app.state.settings, max_runs=max_runs)
        jobs = [
            {
                "run_id": c.run_id,
                "test_id": c.test_id,
                "tenant_id": c.tenant_id,
                "test_name": c.test_name,
                "base_url": c.base_url,
                "timeout_seconds": c.timeout_seconds,
                "test_kind": c.test_kind,
                "definition": c.definition,
                "source_relpath": c.source_relpath,
                "source_filename": c.source_filename,
                "source_sha256": c.source_sha256,
            }
            for c in claimed
        ]
        return {"ok": True, "jobs": jobs}

    @app.post("/api/v1/runner/runs/{run_id}/complete")
    async def runner_complete(
        run_id: str,
        _auth: None = Depends(require_runner),
        req: RunnerCompleteRequest | None = None,
    ) -> dict[str, Any]:
        if req is None:
            raise HTTPException(status_code=400, detail="missing_body")
        status = str(req.status or "").strip().lower()
        if status not in {"pass", "fail", "infra_degraded"}:
            raise HTTPException(status_code=400, detail="invalid_status")

        completion = dbm.RunCompletion(
            status=status,
            elapsed_ms=req.elapsed_ms,
            error_kind=req.error_kind,
            error_message=req.error_message,
            final_url=req.final_url,
            title=req.title,
            artifacts=req.artifacts or {},
            started_at_ts=req.started_at_ts,
            finished_at_ts=req.finished_at_ts,
        )
        outcome = await asyncio.to_thread(dbm.complete_run, app.state.settings, run_id=run_id, completion=completion)

        # Send alerts out-of-band (after DB commit).
        async with httpx.AsyncClient(headers={"User-Agent": "PitchAI E2E Registry"}) as http_client:
            if outcome.alerted_down and outcome.updated and outcome.tenant_id and outcome.test_id and outcome.test_name:
                cfg = await asyncio.to_thread(
                    dbm.get_test_config_internal, app.state.settings, test_id=outcome.test_id
                )
                down_after = int(cfg.get("down_after_failures") or 2) if isinstance(cfg, dict) else 2
                test_kind = str(cfg.get("test_kind") or "stepflow") if isinstance(cfg, dict) else "stepflow"
                msg = build_failure_telegram_message(
                    settings=app.state.settings,
                    tenant_id=outcome.tenant_id,
                    test_id=outcome.test_id,
                    test_name=outcome.test_name,
                    test_kind=test_kind,
                    run_id=run_id,
                    fail_streak=int(outcome.fail_streak or 0),
                    down_after_failures=down_after,
                    error_kind=req.error_kind,
                    error_message=req.error_message,
                    final_url=req.final_url,
                    artifacts=req.artifacts,
                )
                await maybe_send_failure_alert(http_client=http_client, settings=app.state.settings, msg=msg)

                # Optional dispatcher escalation.
                if isinstance(cfg, dict) and bool(int(cfg.get("dispatch_on_failure") or 0)):
                    prompt = build_dispatch_prompt_for_failure(
                        test_id=outcome.test_id,
                        test_name=outcome.test_name,
                        test_kind=test_kind,
                        base_url=str(cfg.get("base_url") or ""),
                        run_id=run_id,
                        error_kind=req.error_kind,
                        error_message=req.error_message,
                        artifacts=req.artifacts,
                    )
                    await maybe_dispatch_failure_investigation(
                        http_client=http_client,
                        settings=app.state.settings,
                        prompt=prompt,
                        context={
                            "tenant_id": outcome.tenant_id,
                            "test_id": outcome.test_id,
                            "test_name": outcome.test_name,
                            "test_kind": test_kind,
                            "base_url": str(cfg.get("base_url") or "") if isinstance(cfg, dict) else "",
                            "run_id": run_id,
                        },
                    )

            if outcome.recovered_up and outcome.updated and outcome.test_id and outcome.test_name:
                cfg = await asyncio.to_thread(
                    dbm.get_test_config_internal, app.state.settings, test_id=outcome.test_id
                )
                if isinstance(cfg, dict) and bool(int(cfg.get("notify_on_recovery") or 0)):
                    msg = build_recovery_telegram_message(
                        settings=app.state.settings,
                        test_id=outcome.test_id,
                        test_name=outcome.test_name,
                        run_id=run_id,
                    )
                    await maybe_send_failure_alert(http_client=http_client, settings=app.state.settings, msg=msg)

        return {"ok": True, "outcome": outcome.__dict__}

    return app


app = create_app()
