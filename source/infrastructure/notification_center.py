"""Shared notification intent state for app focus and dashboard navigation."""

from __future__ import annotations

from threading import Lock
from typing import Callable

_intent_lock = Lock()
_pending_intent: dict | None = None
_focus_handler: Callable[[dict], None] | None = None


def build_dashboard_intent(
    *,
    date_key: str,
    show_unread: bool = True,
    category: str = "",
    message: str = "알림에서 이동했습니다.",
) -> dict:
    return {
        "date_key": date_key,
        "show_unread": bool(show_unread),
        "category": category or "",
        "message": message,
    }


def set_focus_handler(handler: Callable[[dict], None] | None) -> None:
    global _focus_handler
    with _intent_lock:
        _focus_handler = handler


def push_intent(intent: dict) -> None:
    global _pending_intent
    payload = dict(intent or {})
    handler = None
    with _intent_lock:
        _pending_intent = payload
        handler = _focus_handler
    if handler:
        try:
            handler(dict(payload))
        except Exception:
            pass


def peek_intent() -> dict | None:
    with _intent_lock:
        if _pending_intent is None:
            return None
        return dict(_pending_intent)


def pop_intent() -> dict | None:
    global _pending_intent
    with _intent_lock:
        if _pending_intent is None:
            return None
        payload = dict(_pending_intent)
        _pending_intent = None
        return payload
