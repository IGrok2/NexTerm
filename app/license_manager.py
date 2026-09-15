from __future__ import annotations

import hashlib
import hmac
import json
import os
import platform
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


DEFAULT_LICENSE_SERVER = "https://licenses.example.com"
LICENSE_SECRET = "NexTerm-local-license-signing-key"
OFFLINE_GRACE_DAYS = 14


@dataclass
class LicenseState:
    edition: str = "Standard"
    status: str = "active"
    key: str = ""
    owner: str = "Local user"
    expires_at: str = ""
    checked_at: str = ""
    offline_until: str = ""
    message: str = "Standard license"


def machine_id() -> str:
    raw = "|".join((platform.node(), platform.machine(), platform.platform(), socket.gethostname()))
    return hashlib.sha256(raw.encode("utf-8", errors="ignore")).hexdigest()[:32]


def normalize_key(value: str) -> str:
    return "".join(ch for ch in value.upper() if ch.isalnum())


def generate_activation_codes(count: int = 16) -> list[str]:
    return [uuid4().hex.upper() for _ in range(count)]


def validate_license(key: str, cache_path: str | Path, server_url: str = "") -> LicenseState:
    key = normalize_key(key)
    cache_path = Path(cache_path)
    if not key:
        return LicenseState()
    try:
        state = _fetch_license(key, server_url)
        _write_cache(cache_path, state)
        return state
    except Exception as exc:
        cached = _read_cache(cache_path, key)
        if cached and _within_grace(cached):
            cached.status = "offline"
            cached.message = f"Offline mode: server unavailable, cached Enterprise license is valid until {cached.offline_until}."
            return cached
        return LicenseState("Standard", "server_unavailable", key, message=f"License server unavailable: {exc}")


def _fetch_license(key: str, server_url: str = "") -> LicenseState:
    base_url = (server_url or os.getenv("NEXTERM_LICENSE_SERVER") or DEFAULT_LICENSE_SERVER).strip()
    url = f"{base_url.rstrip('/')}/licenses/{key}.json?machine={machine_id()}"
    request = urllib.request.Request(url, headers={"User-Agent": "NexTerm/1.0"})
    with urllib.request.urlopen(request, timeout=6) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not _verify_payload(payload):
        raise ValueError("bad license signature")
    if normalize_key(str(payload.get("key", ""))) != key:
        raise ValueError("license key mismatch")
    if str(payload.get("status", "active")).lower() not in {"active", "trial"}:
        raise ValueError("license is not active")
    expires = str(payload.get("expires_at", ""))
    if expires and _parse_time(expires) < datetime.now(timezone.utc):
        raise ValueError("license expired")
    now = datetime.now(timezone.utc)
    return LicenseState(
        edition=str(payload.get("edition", "Enterprise")),
        status=str(payload.get("status", "active")),
        key=key,
        owner=str(payload.get("owner", "Enterprise user")),
        expires_at=expires,
        checked_at=now.isoformat(),
        offline_until=(now + timedelta(days=OFFLINE_GRACE_DAYS)).isoformat(),
        message="Enterprise license activated",
    )


def _signable(payload: dict[str, Any]) -> bytes:
    clean = {k: v for k, v in payload.items() if k != "signature"}
    return json.dumps(clean, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _verify_payload(payload: dict[str, Any]) -> bool:
    signature = str(payload.get("signature", ""))
    expected = hmac.new(LICENSE_SECRET.encode("utf-8"), _signable(payload), hashlib.sha256).hexdigest()
    return bool(signature) and hmac.compare_digest(signature, expected)


def sign_license(payload: dict[str, Any]) -> dict[str, Any]:
    signed = dict(payload)
    signed["signature"] = hmac.new(LICENSE_SECRET.encode("utf-8"), _signable(signed), hashlib.sha256).hexdigest()
    return signed


def _write_cache(path: Path, state: LicenseState):
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = state.__dict__.copy()
    payload["machine"] = machine_id()
    payload["cache_signature"] = hmac.new(LICENSE_SECRET.encode("utf-8"), json.dumps(payload, sort_keys=True).encode("utf-8"), hashlib.sha256).hexdigest()
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_cache(path: Path, key: str) -> LicenseState | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        signature = payload.pop("cache_signature", "")
        expected = hmac.new(LICENSE_SECRET.encode("utf-8"), json.dumps(payload, sort_keys=True).encode("utf-8"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected) or payload.get("machine") != machine_id():
            return None
        if normalize_key(str(payload.get("key", ""))) != key:
            return None
        return LicenseState(**{k: v for k, v in payload.items() if k in LicenseState.__dataclass_fields__})
    except (OSError, ValueError, TypeError):
        return None


def _within_grace(state: LicenseState) -> bool:
    return bool(state.offline_until) and _parse_time(state.offline_until) >= datetime.now(timezone.utc)


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))
