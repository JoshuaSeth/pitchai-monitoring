from __future__ import annotations

import base64
import hashlib
import json
import struct
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import cbor2
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID, ObjectIdentifier
from fastapi.testclient import TestClient

from auth_usage_dashboard.app import create_app
from auth_usage_dashboard.mobile_auth import (
    AppAttestRegistry,
    Challenge,
    ChallengeStore,
    MobileAuthError,
    canonical_client_data,
    verify_assertion as verify_app_attest_assertion,
)
from auth_usage_dashboard.settings import DashboardSettings


UTC = timezone.utc
APP_ID_PREFIX = "ZM6568G5FX"
BUNDLE_ID = "com.pitchai.codexstatus"
APP_ID = f"{APP_ID_PREFIX}.{BUNDLE_ID}"
NONCE_OID = ObjectIdentifier("1.2.840.113635.100.8.2")


class FakeSource:
    def __init__(self) -> None:
        self.closed = False

    def read_accounts(self) -> list[dict[str, Any]]:
        now = datetime.now(UTC)
        return [
            {
                "metadata": {
                    "account_id": "must-never-escape",
                    "label": "seth-primary",
                    "enabled": True,
                    "prefer_for_all_clients": True,
                },
                "auth_json": {"refresh_token": "must-never-escape"},
                "state": {
                    "availability": "available",
                    "last_probe_at": now.isoformat(),
                    "usage": {
                        "email": "private-account@example.com",
                        "plan_type": "pro",
                        "rate_limit": {
                            "primary_window": {
                                "used_percent": 20,
                                "reset_at": (now + timedelta(hours=2)).isoformat(),
                                "limit_window_seconds": 18_000,
                            },
                            "secondary_window": {
                                "used_percent": 40,
                                "reset_at": (now + timedelta(days=3)).isoformat(),
                                "limit_window_seconds": 604_800,
                            },
                        },
                    },
                },
            }
        ]

    def probe_accounts(self, accounts: list[dict[str, Any]]) -> dict[str, str]:
        return {}

    def probe_analytics(self, accounts: list[dict[str, Any]]) -> dict[str, str]:
        return {}

    def close(self) -> None:
        self.closed = True


def _settings(tmp_path: Path, root_path: Path) -> DashboardSettings:
    return DashboardSettings(
        broker_data_dir=tmp_path,
        broker_url="http://127.0.0.1:38188",
        broker_admin_token="test-only",
        safe_probe_enabled=False,
        probe_on_startup=False,
        snapshot_refresh_seconds=300,
        manual_probe_min_interval_seconds=30,
        require_proxy_auth=True,
        history_file=None,
        mobile_enabled=True,
        mobile_app_id_prefix=APP_ID_PREFIX,
        mobile_bundle_id=BUNDLE_ID,
        mobile_app_attest_environment="development",
        mobile_app_attest_registry_file=tmp_path / "registry.json",
        mobile_app_attest_root_certificate=root_path,
        mobile_app_attest_enrollment_enabled=True,
        mobile_app_attest_max_keys=1,
        mobile_challenge_ttl_seconds=120,
        mobile_challenge_max_pending=8,
    )


class AttestationFixture:
    def __init__(self, tmp_path: Path) -> None:
        now = datetime.now(UTC)
        self.root_key = ec.generate_private_key(ec.SECP384R1())
        self.root_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Test App Attest Root")])
        self.root = self._certificate(
            subject=self.root_name,
            issuer=self.root_name,
            public_key=self.root_key.public_key(),
            issuer_key=self.root_key,
            is_ca=True,
            now=now,
        )
        self.intermediate_key = ec.generate_private_key(ec.SECP384R1())
        self.intermediate_name = x509.Name(
            [x509.NameAttribute(NameOID.COMMON_NAME, "Test App Attest Intermediate")]
        )
        self.intermediate = self._certificate(
            subject=self.intermediate_name,
            issuer=self.root_name,
            public_key=self.intermediate_key.public_key(),
            issuer_key=self.root_key,
            is_ca=True,
            now=now,
        )
        self.attested_key = ec.generate_private_key(ec.SECP256R1())
        point = self.attested_key.public_key().public_bytes(
            serialization.Encoding.X962,
            serialization.PublicFormat.UncompressedPoint,
        )
        self.key_id = base64.b64encode(hashlib.sha256(point).digest()).decode("ascii")
        self.root_path = tmp_path / "test-root.crt"
        self.root_path.write_bytes(self.root.public_bytes(serialization.Encoding.PEM))

    def attestation(self, challenge: bytes, *, app_id: str = APP_ID) -> str:
        credential = base64.b64decode(self.key_id)
        numbers = self.attested_key.public_key().public_numbers()
        cose = cbor2.dumps(
            {
                1: 2,
                3: -7,
                -1: 1,
                -2: numbers.x.to_bytes(32, "big"),
                -3: numbers.y.to_bytes(32, "big"),
            }
        )
        auth_data = (
            hashlib.sha256(app_id.encode("utf-8")).digest()
            + b"\x40"
            + struct.pack(">I", 0)
            + b"appattestdevelop"
            + struct.pack(">H", len(credential))
            + credential
            + cose
        )
        nonce = hashlib.sha256(auth_data + hashlib.sha256(challenge).digest()).digest()
        extension = b"\x30\x24\xa1\x22\x04\x20" + nonce
        now = datetime.now(UTC)
        leaf_name = x509.Name(
            [x509.NameAttribute(NameOID.COMMON_NAME, "Test App Attest Credential")]
        )
        leaf = (
            x509.CertificateBuilder()
            .subject_name(leaf_name)
            .issuer_name(self.intermediate_name)
            .public_key(self.attested_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=5))
            .not_valid_after(now + timedelta(days=2))
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.UnrecognizedExtension(NONCE_OID, extension), critical=False)
            .sign(self.intermediate_key, hashes.SHA256())
        )
        return base64.b64encode(
            cbor2.dumps(
                {
                    "fmt": "apple-appattest",
                    "attStmt": {
                        "x5c": [
                            leaf.public_bytes(serialization.Encoding.DER),
                            self.intermediate.public_bytes(serialization.Encoding.DER),
                        ],
                        "receipt": b"test-receipt",
                    },
                    "authData": auth_data,
                }
            )
        ).decode("ascii")

    def assertion(self, client_data: bytes, *, counter: int, flags: int = 0) -> str:
        auth_data = (
            hashlib.sha256(APP_ID.encode("utf-8")).digest()
            + bytes([flags])
            + struct.pack(">I", counter)
        )
        nonce = hashlib.sha256(auth_data + hashlib.sha256(client_data).digest()).digest()
        signature = self.attested_key.sign(nonce, ec.ECDSA(hashes.SHA256()))
        return base64.b64encode(
            cbor2.dumps(
                {"signature": signature, "authenticatorData": auth_data}
            )
        ).decode("ascii")

    @staticmethod
    def _certificate(
        *,
        subject: x509.Name,
        issuer: x509.Name,
        public_key: ec.EllipticCurvePublicKey,
        issuer_key: ec.EllipticCurvePrivateKey,
        is_ca: bool,
        now: datetime,
    ) -> x509.Certificate:
        return (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(issuer)
            .public_key(public_key)
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(days=1))
            .not_valid_after(now + timedelta(days=30))
            .add_extension(
                x509.BasicConstraints(ca=is_ca, path_length=None), critical=True
            )
            .sign(issuer_key, hashes.SHA256())
        )


def test_app_attest_registry_enforces_counter_and_persists_privately(
    tmp_path: Path,
) -> None:
    fixture = AttestationFixture(tmp_path)
    path = tmp_path / "registry.json"
    registry = AppAttestRegistry(
        path=path,
        root_certificate_path=fixture.root_path,
        app_id=APP_ID,
        environment="development",
        max_keys=1,
        enrollment_enabled=True,
    )
    challenge = b"a" * 32
    registry.register(
        key_id=fixture.key_id,
        attestation_object=fixture.attestation(challenge),
        challenge=challenge,
    )

    request_data = b"canonical request"
    assertion = fixture.assertion(request_data, counter=1, flags=0x40)
    assert (
        registry.verify_assertion(
            key_id=fixture.key_id,
            assertion_object=assertion,
            client_data=request_data,
        )
        == 1
    )
    with pytest.raises(MobileAuthError, match="already used"):
        registry.verify_assertion(
            key_id=fixture.key_id,
            assertion_object=assertion,
            client_data=request_data,
        )

    assert path.stat().st_mode & 0o777 == 0o600
    persisted = path.read_text(encoding="utf-8")
    assert "private-account" not in persisted
    assert "test-only" not in persisted


@pytest.mark.parametrize("flags", [0x00, 0x40])
def test_app_attest_assertion_accepts_supported_apple_flag_values(
    tmp_path: Path,
    flags: int,
) -> None:
    fixture = AttestationFixture(tmp_path)
    client_data = b"canonical request"

    assert (
        verify_app_attest_assertion(
            assertion_object=fixture.assertion(
                client_data,
                counter=1,
                flags=flags,
            ),
            client_data=client_data,
            app_id=APP_ID,
            public_key=fixture.attested_key.public_key(),
            previous_counter=0,
        )
        == 1
    )


@pytest.mark.parametrize(
    "flags",
    [0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x41, 0x44, 0x80, 0xFF],
)
def test_app_attest_assertion_rejects_all_other_authenticator_flags(
    tmp_path: Path,
    flags: int,
) -> None:
    fixture = AttestationFixture(tmp_path)
    client_data = b"canonical request"

    with pytest.raises(MobileAuthError, match="flags are invalid"):
        verify_app_attest_assertion(
            assertion_object=fixture.assertion(
                client_data,
                counter=1,
                flags=flags,
            ),
            client_data=client_data,
            app_id=APP_ID,
            public_key=fixture.attested_key.public_key(),
            previous_counter=0,
        )


def test_attestation_is_bound_to_challenge_and_app(tmp_path: Path) -> None:
    fixture = AttestationFixture(tmp_path)
    registry = AppAttestRegistry(
        path=tmp_path / "registry.json",
        root_certificate_path=fixture.root_path,
        app_id=APP_ID,
        environment="development",
        max_keys=1,
        enrollment_enabled=True,
    )
    with pytest.raises(MobileAuthError, match="nonce does not match"):
        registry.register(
            key_id=fixture.key_id,
            attestation_object=fixture.attestation(b"a" * 32),
            challenge=b"b" * 32,
        )


def test_challenges_are_single_use_and_request_data_is_canonical() -> None:
    store = ChallengeStore(ttl_seconds=120, max_pending=8)
    key_id = base64.b64encode(b"k" * 32).decode("ascii")
    challenge = store.issue(purpose="capacity", key_id=key_id)
    consumed = store.consume(
        identifier=challenge.identifier, purpose="capacity", key_id=key_id
    )
    assert canonical_client_data(consumed).decode("ascii") == (
        "pitchai-codex-status-v1\n"
        f"capacity\n{challenge.identifier}\n{challenge.encoded_value}\n{key_id}"
    )
    with pytest.raises(MobileAuthError, match="missing or expired"):
        store.consume(
            identifier=challenge.identifier, purpose="capacity", key_id=key_id
        )


def test_mobile_routes_enroll_assert_and_return_only_native_contract(
    tmp_path: Path,
) -> None:
    fixture = AttestationFixture(tmp_path)
    source = FakeSource()
    app = create_app(_settings(tmp_path, fixture.root_path), source=source)

    with TestClient(app) as client:
        challenge_response = client.post(
            "/api/v1/mobile/challenge",
            json={"purpose": "attest", "key_id": fixture.key_id},
        )
        assert challenge_response.status_code == 200
        challenge_payload = challenge_response.json()
        challenge = base64.b64decode(challenge_payload["challenge"])
        attested = client.post(
            "/api/v1/mobile/attest",
            json={
                "challenge_id": challenge_payload["challenge_id"],
                "key_id": fixture.key_id,
                "attestation": fixture.attestation(challenge),
            },
        )
        assert attested.status_code == 200
        assert attested.json()["registered"] is True

        capacity_challenge_response = client.post(
            "/api/v1/mobile/challenge",
            json={"purpose": "capacity", "key_id": fixture.key_id},
        )
        capacity_challenge_payload = capacity_challenge_response.json()
        capacity_challenge = Challenge(
            identifier=capacity_challenge_payload["challenge_id"],
            value=base64.b64decode(capacity_challenge_payload["challenge"]),
            purpose="capacity",
            key_id=fixture.key_id,
            created_monotonic=0,
        )
        response = client.post(
            "/api/v1/mobile/capacity",
            json={
                "challenge_id": capacity_challenge.identifier,
                "key_id": fixture.key_id,
                "assertion": fixture.assertion(
                    canonical_client_data(capacity_challenge), counter=1
                ),
            },
        )

    assert source.closed is True
    assert response.status_code == 200
    payload = response.json()
    assert payload["schema_version"] == 1
    assert payload["summary"]["usable_now"] == 1
    assert payload["summary"]["window_aggregates"]["five_hour"][
        "remaining_points"
    ] == 80.0
    assert payload["accounts"][0]["label"] == "seth-primary"
    assert payload["accounts"][0]["five_hour"]["remaining_percent"] == 80.0
    assert payload["refresh_policy"]["recommended_background_interval_seconds"] == 900
    encoded = json.dumps(payload)
    for forbidden in (
        "private-account@example.com",
        "must-never-escape",
        "auth_json",
        "access_token",
        "refresh_token",
        "admin_token",
        "receipt",
        "public_key",
    ):
        assert forbidden not in encoded


def test_mobile_routes_are_absent_when_disabled(tmp_path: Path) -> None:
    settings = DashboardSettings(
        broker_data_dir=tmp_path,
        broker_url="http://127.0.0.1:38188",
        broker_admin_token="test-only",
        safe_probe_enabled=False,
        history_file=None,
        mobile_enabled=False,
    )
    with TestClient(create_app(settings, source=FakeSource())) as client:
        response = client.post(
            "/api/v1/mobile/challenge",
            json={
                "purpose": "capacity",
                "key_id": base64.b64encode(b"k" * 32).decode("ascii"),
            },
        )
    assert response.status_code == 404


def test_mobile_nginx_edge_clears_browser_and_proxy_credentials() -> None:
    config = Path("ops/codexusage.pitchai.net.nginx.conf").read_text(
        encoding="utf-8"
    )
    mobile = config.split("location ^~ /api/v1/mobile/ {", 1)[1].split(
        "\n    }", 1
    )[0]
    assert 'proxy_set_header Authorization "";' in mobile
    assert 'proxy_set_header Cookie "";' in mobile
    assert 'proxy_set_header X-PitchAI-Email "";' in mobile
    assert "pitchai-sso-protected-location" not in mobile
    assert "limit_req zone=codex_usage_mobile" in mobile
