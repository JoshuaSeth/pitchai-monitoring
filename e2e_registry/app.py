from __future__ import annotations

import asyncio
import hmac
import os
import secrets
import time
from pathlib import Path
from typing import Any

import httpx
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from e2e_registry import db as dbm
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


def create_app(settings: RegistrySettings | None = None) -> FastAPI:
    app = FastAPI(title="PitchAI E2E Registry", version="0.1.0")
    app.state.settings = settings or RegistrySettings()

    templates_dir = Path(__file__).parent / "templates"
    templates = Jinja2Templates(directory=str(templates_dir))
    app.state.templates = templates

    @app.on_event("startup")
    def _startup() -> None:
        dbm.ensure_schema(app.state.settings)

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {"ok": True, "ts": time.time()}

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
        definition_json = test.get("definition_json") or ""
        return app.state.templates.TemplateResponse(
            "test_detail.html",
            {"request": req, "test": test, "runs": runs, "definition_json": definition_json, "msg": msg},
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
        interval_seconds: int = Form(300),
        file: UploadFile = File(...),
    ) -> HTMLResponse:
        authed = await _ui_get_auth(req)
        if authed is None:
            return _redirect_to_login()

        raw = await file.read()
        try:
            defn_raw = parse_definition_bytes(raw, content_type=file.content_type)
            defn = validate_definition(defn_raw)
            base = validate_base_url(base_url)
        except StepFlowValidationError as exc:
            return app.state.templates.TemplateResponse(
                "upload.html", {"request": req, "error": str(exc), "msg": None}
            )
        except HTTPException as exc:
            return app.state.templates.TemplateResponse(
                "upload.html", {"request": req, "error": str(exc.detail), "msg": None}
            )

        tname = (name or "").strip() or str(defn.get("name") or "test")
        try:
            created = await asyncio.to_thread(
                dbm.insert_test,
                app.state.settings,
                tenant_id=authed.tenant_id,
                name=tname,
                base_url=base,
                definition=defn,
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
            base = validate_base_url(req.base_url)
            defn = validate_definition(req.definition)
        except StepFlowValidationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        created = await asyncio.to_thread(
            dbm.insert_test,
            app.state.settings,
            tenant_id=auth.tenant_id,
            name=req.name,
            base_url=base,
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

    @app.patch("/api/v1/tests/{test_id}")
    async def api_patch_test(test_id: str, auth: RequestAuth = Depends(require_tenant_auth), req: PatchTestRequest | None = None) -> dict[str, Any]:
        if req is None:
            raise HTTPException(status_code=400, detail="missing_body")
        patch: dict[str, Any] = req.model_dump(exclude_unset=True)
        if "base_url" in patch and patch["base_url"] is not None:
            patch["base_url"] = validate_base_url(patch["base_url"])
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
                "definition": c.definition,
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
                msg = build_failure_telegram_message(
                    settings=app.state.settings,
                    tenant_id=outcome.tenant_id,
                    test_id=outcome.test_id,
                    test_name=outcome.test_name,
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
