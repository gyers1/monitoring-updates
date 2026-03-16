"""
Persistent UI preference storage.

Stores category order and site priority in a local JSON file so the layout
survives app restart, update, and webview storage resets.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

DEFAULT_UI_PREFS: dict = {
    "category_order": [],
    "site_priority": {},
}


def _prefs_path(base_dir: str | Path) -> Path:
    return Path(base_dir) / "ui_prefs.json"


def _normalize_category_order(value) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        if not isinstance(item, str):
            continue
        name = item.strip()
        if not name:
            continue
        if name not in result:
            result.append(name)
    return result


def _normalize_site_priority(value) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, int] = {}
    for key, val in value.items():
        key_text = str(key).strip()
        if not key_text:
            continue
        try:
            priority = int(val)
        except (TypeError, ValueError):
            continue
        if priority <= 0:
            continue
        result[key_text] = priority
    return result


def _normalize_prefs(value: dict) -> dict:
    if not isinstance(value, dict):
        return DEFAULT_UI_PREFS.copy()
    return {
        "category_order": _normalize_category_order(value.get("category_order")),
        "site_priority": _normalize_site_priority(value.get("site_priority")),
    }


def load_ui_prefs(base_dir: str | Path) -> dict:
    path = _prefs_path(base_dir)
    if not path.exists():
        return DEFAULT_UI_PREFS.copy()
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return DEFAULT_UI_PREFS.copy()
    return _normalize_prefs(raw)


def save_ui_prefs(
    base_dir: str | Path,
    *,
    category_order: Optional[list[str]] = None,
    site_priority: Optional[dict] = None,
) -> dict:
    current = load_ui_prefs(base_dir)
    if category_order is not None:
        current["category_order"] = _normalize_category_order(category_order)
    if site_priority is not None:
        current["site_priority"] = _normalize_site_priority(site_priority)

    path = _prefs_path(base_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".tmp")
    tmp_path.write_text(
        json.dumps(current, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    tmp_path.replace(path)
    return current
