import json
from dataclasses import replace
from types import SimpleNamespace

from fastapi.testclient import TestClient

from auth_usage_dashboard.app import create_app
from auth_usage_dashboard.claude_accounts import auth_status, collect, read_snapshot
from auth_usage_dashboard.settings import DashboardSettings


def make_owner(tmp_path, now):
    state = tmp_path / "owners/person"
    state.mkdir(parents=True)
    (state / "home").mkdir()
    (state / "secondary").mkdir()
    owner = {"provider": "claude_code", "tenant_id": "tenant", "user_id": "person"}
    (state / "owner.json").write_text(json.dumps(owner))
    (state / "accounts.json").write_text(json.dumps({**owner, "accounts": [
        {"id": "primary", "home": "home"}, {"id": "secondary", "home": "secondary"}]}))
    (state / "health.json").write_text(json.dumps({"writtenAt": now, "accounts": [
        {"id": "primary", "usageLimit": {"limitType": "seven_day", "utilization": 0.76,
                                         "observedAt": now - 1000, "limitedUntil": now + 3600}},
        {"id": "secondary", "usageLimit": {}}]}))
    return state


def test_export_separates_availability_from_stale_or_unknown_usage(tmp_path, monkeypatch):
    now = 1790586000
    state = make_owner(tmp_path, now)
    (state / "home/auth.json").write_text('{"access_token":"never-export-this"}')
    monkeypatch.setattr("auth_usage_dashboard.claude_accounts.auth_status", lambda cli, home: {
        "signed_in": True, "email": "first@pitchai.net" if home.name == "home" else "second@pitchai.net", "plan": "max"})
    raw = collect(tmp_path / "owners", tmp_path / "claude", now=now)
    path = tmp_path / "status.json"
    path.write_text(json.dumps(raw))
    snapshot = read_snapshot(path, now=now)
    assert len(snapshot["accounts"]) == 2
    first, second = snapshot["accounts"]
    assert first["status"] == "cooldown" and first["used_percent"] == 76
    assert first["usage_stale"] is True and first["window"] == "seven_day"
    assert second["status"] == "ready" and second["used_percent"] is None
    assert second["usage_stale"] is True and second["rotation_enabled"] is True
    assert "never-export-this" not in json.dumps(raw)
    assert not raw["errors"]
    stale = read_snapshot(path, now=now + 200)
    assert stale["stale"] and all(a["status"] == "unavailable" for a in stale["accounts"])


def test_export_rejects_foreign_principal_and_path_escape(tmp_path):
    state = make_owner(tmp_path, 1790586000)
    path = state / "accounts.json"
    config = json.loads(path.read_text())
    config["user_id"] = "other"
    path.write_text(json.dumps(config))
    assert collect(tmp_path / "owners", tmp_path / "missing")["accounts"] == []
    config["user_id"] = "person"
    config["accounts"][0]["home"] = "/root"
    path.write_text(json.dumps(config))
    assert collect(tmp_path / "owners", tmp_path / "missing")["accounts"] == []


def test_auth_status_uses_official_cli_and_scrubs_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "must-not-leak")
    def run(args, **kwargs):
        assert args[-2:] == ["auth", "status"]
        assert "ANTHROPIC_API_KEY" not in kwargs["env"]
        assert kwargs["env"]["HOME"] == str(tmp_path)
        return SimpleNamespace(stdout=json.dumps({"loggedIn": True, "authMethod": "claude.ai",
            "apiProvider": "firstParty", "subscriptionType": "max", "email": "person@pitchai.net",
            "accessToken": "must-not-leak"}))
    monkeypatch.setattr("auth_usage_dashboard.claude_accounts.subprocess.run", run)
    result = auth_status(tmp_path / "claude", tmp_path)
    assert result == {"signed_in": True, "email": "person@pitchai.net", "plan": "max"}


class EmptySource:
    def read_accounts(self): return []
    def close(self): pass


def test_claude_api_requires_identity_and_allowlists_response(tmp_path):
    path = tmp_path / "claude.json"
    path.write_text(json.dumps({"schema_version": 1, "generated_at": 1790586000,
        "access_token": "must-not-leak", "accounts": [{"email": "person@pitchai.net", "plan": "max",
        "status": "ready", "used_percent": None, "refresh_token": "must-not-leak"}]}))
    settings = DashboardSettings(broker_data_dir=tmp_path, broker_url="http://127.0.0.1:1", broker_admin_token="",
        safe_probe_enabled=False, probe_on_startup=False, claude_accounts_file=path, history_file=None)
    with TestClient(create_app(settings, source=EmptySource())) as client:
        assert client.get("/api/v1/claude-accounts").status_code == 401
        assert client.get("/api/v1/claude-accounts", headers={"X-PitchAI-Email": "person@example.com"}).status_code == 401
        response = client.get("/api/v1/claude-accounts", headers={"X-PitchAI-Email": "person@pitchai.net"})
        assert response.status_code == 200 and len(response.json()["accounts"]) == 1
        assert "must-not-leak" not in response.text and "refresh_token" not in response.text
        assert response.headers["cache-control"] == "private, no-store"
    with TestClient(create_app(replace(settings, claude_accounts_file=tmp_path / "absent"), source=EmptySource())) as client:
        snapshot = client.get("/api/v1/claude-accounts", headers={"X-PitchAI-Email": "person@pitchai.net"}).json()
        assert snapshot["stale"] and snapshot["accounts"] == []
