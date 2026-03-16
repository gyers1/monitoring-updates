"""Runtime version helpers shared by UI rendering and API responses."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Optional

from .settings import get_settings


def parse_version_number(value: Optional[str]) -> Optional[int]:
    if not value:
        return None
    text = str(value).strip()
    match = re.fullmatch(r"v(\d{8,14})", text)
    if match:
        try:
            return int(match.group(1))
        except ValueError:
            return None
    match = re.fullmatch(r"v(\d{4})-(\d{2})-(\d{2})-(\d{2})[:-](\d{2})", text)
    if not match:
        return None
    try:
        return int("".join(match.groups()))
    except ValueError:
        return None


def pick_latest_version(primary: str, secondary: str) -> str:
    p_num = parse_version_number(primary)
    s_num = parse_version_number(secondary)
    if p_num is not None and s_num is not None:
        return primary if p_num >= s_num else secondary
    if p_num is not None:
        return primary
    if s_num is not None:
        return secondary
    return primary or secondary or "v-"


def read_env_version(base_dir: Path) -> str:
    env_path = base_dir / ".env"
    if not env_path.exists():
        return ""
    try:
        text = env_path.read_text(encoding="utf-8-sig")
    except Exception:
        return ""
    for line in text.splitlines():
        if line.startswith("APP_VERSION="):
            return line.split("=", 1)[1].strip()
    return ""


def candidate_version_roots(settings=None) -> list[Path]:
    settings = settings or get_settings()
    roots: list[Path] = []
    for candidate in (
        Path(settings.base_dir),
        Path(getattr(sys, "executable", "")).resolve().parent if getattr(sys, "executable", "") else None,
        Path.cwd(),
    ):
        if not candidate:
            continue
        path = Path(candidate)
        if path not in roots:
            roots.append(path)
    return roots


def read_version_json_flexible(version_file: Path) -> str:
    if not version_file.exists():
        return ""
    try:
        data = json.loads(version_file.read_text(encoding="utf-8"))
        value = (data.get("version") if isinstance(data, dict) else None) or ""
        return str(value).strip()
    except Exception:
        try:
            text = version_file.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return ""
        match = re.search(r"v(?:\d{8,14}|\d{4}-\d{2}-\d{2}-\d{2}[:-]\d{2})", text)
        return match.group(0) if match else ""


def resolve_runtime_version(settings=None) -> str:
    settings = settings or get_settings()
    settings_version = str(settings.app_version or "").strip()
    env_version = ""
    file_version = ""
    latest_numeric = ""

    for root in candidate_version_roots(settings):
        if not env_version:
            env_version = read_env_version(root)
        if not file_version:
            file_version = read_version_json_flexible(root / "version.json")
        if env_version and file_version:
            break

    for candidate in (env_version, file_version, settings_version):
        if parse_version_number(candidate) is not None:
            latest_numeric = pick_latest_version(latest_numeric, candidate)
    if latest_numeric:
        return latest_numeric

    for candidate in (env_version, file_version, settings_version):
        if candidate:
            return candidate
    return "v-"
