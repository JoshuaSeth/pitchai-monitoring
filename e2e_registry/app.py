from __future__ import annotations

import asyncio
import hashlib
import logging
import time
import uuid
from pathlib import Path
from typing import Any

import httpx
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from e2e_registry import db as dbm
from e2e_registry.app_access import RegistryAccess
from e2e_registry.app_admin_routes import router as admin_router
from e2e_registry.app_read_routes import router as read_router
from e2e_registry.app_test_creation import router as test_creation_router
from e2e_registry.app_test_routes import lookup_router as test_lookup_router
from e2e_registry.app_test_routes import router as test_mutation_router
from e2e_registry.app_access import TENANT_COOKIE_NAME as COOKIE_TOKEN_HASH
from e2e_registry.app_context import RegistryContext
from e2e_registry.app_host_policy import RegistryHostPolicy
from e2e_registry.app_host_policy import host_is_reserved_or_non_public as _host_is_reserved_or_non_public
from e2e_registry.app_host_policy import load_monitored_allowlist_hosts as _load_monitored_allowlist_hosts
from e2e_registry.app_host_policy import url_host as _url_host
from e2e_registry.app_inputs import normalize_pitchai_email as _normalize_pitchai_email
from e2e_registry.app_inputs import normalize_test_kind as _normalize_test_kind
from e2e_registry.app_inputs import safe_filename as _safe_filename
from e2e_registry.app_monitoring_routes import install_monitoring_routes
from e2e_registry.disablement import parse_disabled_until
from e2e_registry.alerts import (
    build_dispatch_prompt_for_failure,
    build_failure_telegram_message,
    build_recovery_telegram_message,
    maybe_dispatch_failure_investigation,
    maybe_send_failure_alert,
)
from e2e_registry.auth import RequestAuth, hash_token, require_runner, require_tenant_auth
from e2e_registry.schema import (
    RunnerClaimRequest,
    RunnerCompleteRequest,
)
from e2e_registry.settings import RegistrySettings
from e2e_registry.stepflow import StepFlowValidationError, parse_definition_bytes, validate_definition


__all__ = ["_host_is_reserved_or_non_public", "_load_monitored_allowlist_hosts", "_normalize_pitchai_email",
           "_normalize_test_kind", "_safe_filename", "_url_host", "app", "create_app"]
LOGGER = logging.getLogger("e2e-registry")
def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def create_app(settings: RegistrySettings | None = None) -> FastAPI:
    app = FastAPI(title="PitchAI E2E Registry", version="0.1.0")
    app.state.settings = settings or RegistrySettings()
    app.state.monitor_cache = {"loaded_at_ts": 0.0, "state_mtime": None, "config_mtime": None, "data": None}

    templates_dir = Path(__file__).parent / "templates"
    templates = Jinja2Templates(directory=str(templates_dir))
    app.state.templates = templates
    dashboard_assets_dir = Path(__file__).parent / "static"
    app.mount(
        "/dashboard/assets",
        StaticFiles(directory=str(dashboard_assets_dir)),
        name="dashboard-assets",
    )

    context = RegistryContext(app)
    access = RegistryAccess(context)
    host_policy = RegistryHostPolicy(context)

    @app.on_event("startup")
    def _startup() -> None:
        dbm.ensure_schema(context.settings)
        # Ensure storage locations exist (single-host deployment).
        try:
            Path(context.settings.artifacts_dir).mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        try:
            Path(context.settings.tests_dir).mkdir(parents=True, exist_ok=True)
        except Exception:
            pass

        # Defensive cleanup: quarantine tests with disallowed hosts so they cannot keep firing.
        try:
            quarantined = host_policy.quarantine_disallowed_tests()
            if quarantined > 0:
                LOGGER.warning("Quarantined disallowed e2e tests count=%s", quarantined)
        except Exception:
            LOGGER.exception("Failed to quarantine disallowed e2e tests")


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


    def _redirect_to_login() -> RedirectResponse:
        return RedirectResponse(url="/ui/login", status_code=303)

    # -----------------
    # Monitoring operator auth (separate from tenant UI authorization)
    # -----------------


    # -----------------
    # UI routes
    # -----------------
    @app.get("/ui/login", response_class=HTMLResponse)
    async def ui_login(req: Request) -> HTMLResponse:
        return context.templates.TemplateResponse("login.html", {"request": req, "error": None})

    @app.post("/ui/login")
    async def ui_login_post(req: Request, api_key: str = Form("")):
        token = (api_key or "").strip()
        if not token:
            return context.templates.TemplateResponse(
                "login.html", {"request": req, "error": "Missing API key"}
            )
        th = hash_token(token)
        authed = await asyncio.to_thread(dbm.get_api_key_by_hash, context.settings, token_hash=th)
        if authed is None:
            return context.templates.TemplateResponse(
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
    @app.get("/dashboard", response_class=HTMLResponse)
    async def dashboard(req: Request) -> HTMLResponse:
        actor = access.dashboard_identity(req)
        return context.templates.TemplateResponse(
            "dashboard.html",
            {"request": req, "title": "Monitoring", "operator_identity": actor},
        )

    @app.get("/ui/tests", response_class=HTMLResponse)
    async def ui_tests(req: Request) -> HTMLResponse:
        authed = await access.ui_get_auth(req)
        if authed is None:
            return _redirect_to_login()
        tests = await asyncio.to_thread(dbm.list_tests, context.settings, tenant_id=authed.tenant_id)
        # Normalize sqlite rows (ints) into something templates can use.
        for t in tests:
            for k in ("effective_ok", "fail_streak", "success_streak"):
                try:
                    if t.get(k) is not None:
                        t[k] = int(t[k])
                except Exception:
                    pass
        return context.templates.TemplateResponse(
            "tests.html",
            {"request": req, "tenant_id": authed.tenant_id, "tests": tests},
        )

    @app.get("/ui/tests/{test_id}", response_class=HTMLResponse)
    async def ui_test_detail(req: Request, test_id: str, msg: str | None = None) -> HTMLResponse:
        authed = await access.ui_get_auth(req)
        if authed is None:
            return _redirect_to_login()
        test = await asyncio.to_thread(dbm.get_test, context.settings, tenant_id=authed.tenant_id, test_id=test_id)
        if not test:
            raise HTTPException(status_code=404, detail="test_not_found")
        runs = await asyncio.to_thread(dbm.list_runs, context.settings, tenant_id=authed.tenant_id, test_id=test_id, limit=50)
        kind = str(test.get("test_kind") or "stepflow").strip().lower() or "stepflow"
        definition_json = test.get("definition_json") or ""
        source_text: str | None = None
        source_filename: str | None = None
        source_relpath = str(test.get("source_relpath") or "").strip()
        if kind != "stepflow" and source_relpath:
            try:
                base = Path(context.settings.tests_dir).resolve()
                fp = (base / source_relpath).resolve()
                if base in fp.parents and fp.exists() and fp.is_file():
                    source_filename = fp.name
                    source_text = fp.read_text(encoding="utf-8", errors="replace")
                    if len(source_text) > 80_000:
                        source_text = source_text[:80_000] + "\n...truncated..."
            except Exception:
                source_text = None
        return context.templates.TemplateResponse(
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
        authed = await access.ui_require_auth(req)
        ok = await asyncio.to_thread(dbm.trigger_run_now, context.settings, tenant_id=authed.tenant_id, test_id=test_id)
        msg = "Run triggered" if ok else "Failed to trigger run"
        return RedirectResponse(url=f"/ui/tests/{test_id}?msg={msg}", status_code=303)

    @app.post("/ui/tests/{test_id}/disable")
    async def ui_test_disable(
        req: Request,
        test_id: str,
        reason: str = Form("temporary disable"),
        until: str = Form(""),
    ) -> RedirectResponse:
        authed = await access.ui_require_auth(req)
        try:
            until_ts = parse_disabled_until(until)
        except ValueError:
            return RedirectResponse(url=f"/ui/tests/{test_id}?msg=Invalid+until+value", status_code=303)
        ok = await asyncio.to_thread(
            dbm.set_test_disabled,
            context.settings,
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
        authed = await access.ui_require_auth(req)
        ok = await asyncio.to_thread(
            dbm.set_test_disabled,
            context.settings,
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
        authed = await access.ui_require_auth(req)
        settings2: RegistrySettings = context.settings

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
        authed = await access.ui_get_auth(req)
        if authed is None:
            return _redirect_to_login()
        run = await asyncio.to_thread(dbm.get_run, context.settings, tenant_id=authed.tenant_id, run_id=run_id)
        if not run:
            raise HTTPException(status_code=404, detail="run_not_found")
        artifacts = {}
        try:
            artifacts = (dbm._json_loads(run.get("artifacts_json")) or {}) if isinstance(run.get("artifacts_json"), (str, dict)) else {}
        except Exception:
            artifacts = {}
        return context.templates.TemplateResponse(
            "run_detail.html",
            {"request": req, "run": run, "artifacts": artifacts},
        )

    @app.get("/ui/upload", response_class=HTMLResponse)
    async def ui_upload(req: Request) -> HTMLResponse:
        authed = await access.ui_get_auth(req)
        if authed is None:
            return _redirect_to_login()
        return context.templates.TemplateResponse("upload.html", {"request": req, "error": None, "msg": None})

    @app.post("/ui/upload", response_class=HTMLResponse)
    async def ui_upload_post(
        req: Request,
        name: str = Form(""),
        base_url: str = Form(""),
        kind: str = Form("stepflow"),
        interval_seconds: int = Form(300),
        file: UploadFile = File(...),
    ) -> HTMLResponse:
        authed = await access.ui_get_auth(req)
        if authed is None:
            return _redirect_to_login()

        raw = await file.read()
        settings2: RegistrySettings = context.settings
        kind2 = _normalize_test_kind(kind)
        if not kind2:
            return context.templates.TemplateResponse(
                "upload.html", {"request": req, "error": "invalid_kind", "msg": None}
            )
        if int(settings2.max_upload_bytes) > 0 and len(raw) > int(settings2.max_upload_bytes):
            return context.templates.TemplateResponse(
                "upload.html", {"request": req, "error": "file_too_large", "msg": None}
            )
        try:
            base = host_policy.validate_base_url(base_url)
        except HTTPException as exc:
            return context.templates.TemplateResponse(
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
                return context.templates.TemplateResponse(
                    "upload.html", {"request": req, "error": str(exc), "msg": None}
                )
            tname = tname or str(defn.get("name") or "test")
        else:
            # Code-based tests: store the uploaded file on disk and run via sandbox runner.
            default_fn = "test.py" if kind2 == "playwright_python" else "test.js"
            source_filename = _safe_filename(file.filename or "", default=default_fn)
            if kind2 == "playwright_python" and not source_filename.endswith(".py"):
                return context.templates.TemplateResponse(
                    "upload.html", {"request": req, "error": "python_test_must_be_.py", "msg": None}
                )
            if kind2 == "puppeteer_js" and not (source_filename.endswith(".js") or source_filename.endswith(".mjs")):
                return context.templates.TemplateResponse(
                    "upload.html", {"request": req, "error": "puppeteer_test_must_be_.js", "msg": None}
                )
            tname = tname or source_filename

            test_id = str(uuid.uuid4())
            base_dir = Path(settings2.tests_dir).resolve()
            rel = Path(authed.tenant_id) / test_id / source_filename
            fp = (base_dir / rel).resolve()
            if base_dir not in fp.parents:
                return context.templates.TemplateResponse(
                    "upload.html", {"request": req, "error": "invalid_upload_path", "msg": None}
                )
            try:
                fp.parent.mkdir(parents=True, exist_ok=True)
                fp.write_bytes(raw)
            except Exception as exc:
                return context.templates.TemplateResponse(
                    "upload.html", {"request": req, "error": f"write_failed: {exc}", "msg": None}
                )
            source_relpath = str(rel)
            source_sha = _sha256_hex(raw)
            test_id_override = test_id

        try:
            created = await asyncio.to_thread(
                dbm.insert_test,
                context.settings,
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
            return context.templates.TemplateResponse(
                "upload.html", {"request": req, "error": f"db_error: {exc}", "msg": None}
            )

        msg = f"Created test {created.get('id')}"
        return context.templates.TemplateResponse(
            "upload.html", {"request": req, "error": None, "msg": msg}
        )

    # -----------------
    # API routes
    # -----------------
    install_monitoring_routes(context, access)


    app.include_router(admin_router)

    app.include_router(test_creation_router)

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
        settings2: RegistrySettings = context.settings
        kind2 = _normalize_test_kind(kind)
        if not kind2:
            raise HTTPException(status_code=400, detail="invalid_kind")
        raw = await file.read()
        if int(settings2.max_upload_bytes) > 0 and len(raw) > int(settings2.max_upload_bytes):
            raise HTTPException(status_code=413, detail="file_too_large")

        base = host_policy.validate_base_url(base_url)
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
            context.settings,
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

    app.include_router(test_lookup_router)

    @app.get("/api/v1/tests/{test_id}/source")
    async def api_get_test_source(test_id: str, auth: RequestAuth = Depends(require_tenant_auth)) -> FileResponse:
        test = await asyncio.to_thread(dbm.get_test, context.settings, tenant_id=auth.tenant_id, test_id=test_id)
        if not test:
            raise HTTPException(status_code=404, detail="not_found")
        kind = str(test.get("test_kind") or "stepflow").strip().lower() or "stepflow"
        if kind == "stepflow":
            # Return definition JSON as a small downloadable artifact.
            txt = str(test.get("definition_json") or "").strip() or "{}"
            base = Path(context.settings.tests_dir).resolve()
            tmp = (base / auth.tenant_id / test_id / "definition.json").resolve()
            if base not in tmp.parents:
                raise HTTPException(status_code=400, detail="invalid_path")
            tmp.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(txt, encoding="utf-8", errors="replace")
            return FileResponse(str(tmp), media_type="application/json")

        rel = str(test.get("source_relpath") or "").strip()
        if not rel:
            raise HTTPException(status_code=404, detail="source_missing")
        base = Path(context.settings.tests_dir).resolve()
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
        settings2: RegistrySettings = context.settings
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

    app.include_router(test_mutation_router)

    app.include_router(read_router)

    # -----------------
    # Runner API
    # -----------------
    @app.post("/api/v1/runner/claim")
    async def runner_claim(_auth: None = Depends(require_runner), req: RunnerClaimRequest | None = None) -> dict[str, Any]:
        max_runs = int(req.max_runs) if req is not None else 1
        claimed = await asyncio.to_thread(dbm.claim_due_runs, context.settings, max_runs=max_runs)
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
        outcome = await asyncio.to_thread(dbm.complete_run, context.settings, run_id=run_id, completion=completion)

        # Send alerts out-of-band (after DB commit).
        async with httpx.AsyncClient(headers={"User-Agent": "PitchAI E2E Registry"}) as http_client:
            if outcome.alerted_down and outcome.updated and outcome.tenant_id and outcome.test_id and outcome.test_name:
                cfg = await asyncio.to_thread(
                    dbm.get_test_config_internal, context.settings, test_id=outcome.test_id
                )
                down_after = int(cfg.get("down_after_failures") or 2) if isinstance(cfg, dict) else 2
                test_kind = str(cfg.get("test_kind") or "stepflow") if isinstance(cfg, dict) else "stepflow"
                msg = build_failure_telegram_message(
                    settings=context.settings,
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
                await maybe_send_failure_alert(http_client=http_client, settings=context.settings, msg=msg)

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
                        settings=context.settings,
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
                    dbm.get_test_config_internal, context.settings, test_id=outcome.test_id
                )
                if isinstance(cfg, dict) and bool(int(cfg.get("notify_on_recovery") or 0)):
                    msg = build_recovery_telegram_message(
                        settings=context.settings,
                        test_id=outcome.test_id,
                        test_name=outcome.test_name,
                        run_id=run_id,
                    )
                    await maybe_send_failure_alert(http_client=http_client, settings=context.settings, msg=msg)

        return {"ok": True, "outcome": outcome.__dict__}

    return app


app = create_app()
