"""
Authentication helper for Google Apps Script based access control.
"""

from __future__ import annotations

import hashlib
import json
import platform
import socket
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx

from config import get_settings


AUTH_CACHE_FILE = "auth_cache.json"


@dataclass
class AuthState:
    session_ok: bool = False
    checked_at: datetime | None = None


_state = AuthState()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _to_iso(dt: datetime | None) -> str | None:
    if not dt:
        return None
    return dt.astimezone(timezone.utc).isoformat()


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _cache_path() -> Path:
    settings = get_settings()
    return Path(settings.base_dir) / AUTH_CACHE_FILE


def get_device_info() -> tuple[str, str]:
    device_name = platform.node() or socket.gethostname() or "unknown"
    raw = f"{device_name}-{uuid.getnode()}"
    device_id = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return device_id, device_name


def load_cache() -> dict[str, Any]:
    path = _cache_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_cache(data: dict[str, Any]) -> None:
    path = _cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def cache_is_valid(cache: dict[str, Any], days: int) -> bool:
    if not cache:
        return False
    status = str(cache.get("status") or "active").lower()
    if status != "active":
        return False
    last = _parse_iso(cache.get("last_verified_at"))
    if not last:
        return False
    return _utcnow() - last <= timedelta(days=days)


def cache_expires_at(cache: dict[str, Any], days: int) -> str | None:
    last = _parse_iso(cache.get("last_verified_at"))
    if not last:
        return None
    return _to_iso(last + timedelta(days=days))


def set_session_ok(ok: bool) -> None:
    _state.session_ok = ok
    _state.checked_at = _utcnow()


def is_session_ok() -> bool:
    return _state.session_ok


def get_auth_snapshot() -> dict[str, Any]:
    settings = get_settings()
    cache = load_cache()
    device_id, device_name = get_device_info()
    days = int(settings.auth_cache_days or 7)
    return {
        "session_ok": _state.session_ok,
        "cache_valid": cache_is_valid(cache, days),
        "cached_name": cache.get("name"),
        "status": cache.get("status"),
        "last_verified_at": cache.get("last_verified_at"),
        "expires_at": cache_expires_at(cache, days),
        "device_id": device_id,
        "device_name": device_name,
    }


async def verify_auth(name: str | None) -> dict[str, Any]:
    settings = get_settings()
    cache = load_cache()
    days = int(settings.auth_cache_days or 7)
    device_id, device_name = get_device_info()

    name = (name or cache.get("name") or "").strip()
    if not name:
        set_session_ok(False)
        return {
            "ok": False,
            "reason": "name_required",
            "device_id": device_id,
            "device_name": device_name,
            "cached_name": cache.get("name"),
        }

    if not settings.auth_script_url or not settings.auth_token:
        set_session_ok(False)
        return {
            "ok": False,
            "reason": "not_configured",
            "device_id": device_id,
            "device_name": device_name,
        }

    payload = {
        "name": name,
        "device_id": device_id,
        "device_name": device_name,
        "token": settings.auth_token,
    }

    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            response = await client.post(settings.auth_script_url, json=payload)

        if response.status_code != 200:
            set_session_ok(False)
            return {
                "ok": False,
                "reason": f"auth_http_{response.status_code}",
                "status_code": response.status_code,
                "name": name,
                "device_id": device_id,
                "device_name": device_name,
            }

        data = {}
        try:
            data = response.json()
        except ValueError:
            data = {}

        ok = bool(data.get("ok"))
        status = str(data.get("status") or ("active" if ok else "unknown")).lower()
        reason = data.get("reason")

        if ok and status == "active":
            now = _utcnow()
            save_cache(
                {
                    "name": name,
                    "device_id": device_id,
                    "device_name": device_name,
                    "status": "active",
                    "last_verified_at": _to_iso(now),
                }
            )
            set_session_ok(True)
            return {
                "ok": True,
                "status": "active",
                "offline": False,
                "cached": False,
                "name": name,
                "device_id": device_id,
                "device_name": device_name,
                "last_verified_at": _to_iso(now),
                "expires_at": _to_iso(now + timedelta(days=days)),
            }

        if status in {"pending", "requested", "new"} or (ok and status not in {"active", "blocked"}):
            now = _utcnow()
            save_cache(
                {
                    "name": name,
                    "device_id": device_id,
                    "device_name": device_name,
                    "status": "pending",
                    "last_verified_at": _to_iso(now),
                }
            )
            set_session_ok(False)
            return {
                "ok": False,
                "status": "pending",
                "reason": "pending_approval",
                "name": name,
                "device_id": device_id,
                "device_name": device_name,
                "last_verified_at": _to_iso(now),
            }

        if status == "blocked":
            now = _utcnow()
            save_cache(
                {
                    "name": name,
                    "device_id": device_id,
                    "device_name": device_name,
                    "status": "blocked",
                    "last_verified_at": _to_iso(now),
                }
            )
            set_session_ok(False)
            return {
                "ok": False,
                "status": "blocked",
                "reason": "blocked",
                "name": name,
                "device_id": device_id,
                "device_name": device_name,
                "last_verified_at": _to_iso(now),
            }

        set_session_ok(False)
        return {
            "ok": False,
            "status": status,
            "reason": reason or "denied",
            "name": name,
            "device_id": device_id,
            "device_name": device_name,
        }
    except httpx.RequestError:
        if cache_is_valid(cache, days):
            set_session_ok(True)
            return {
                "ok": True,
                "status": "active",
                "offline": True,
                "cached": True,
                "name": cache.get("name") or name,
                "device_id": device_id,
                "device_name": device_name,
                "last_verified_at": cache.get("last_verified_at"),
                "expires_at": cache_expires_at(cache, days),
            }

        set_session_ok(False)
        return {
            "ok": False,
            "reason": "offline_cache_expired",
            "device_id": device_id,
            "device_name": device_name,
            "cached_name": cache.get("name"),
        }
