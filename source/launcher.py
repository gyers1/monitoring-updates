"""
Minimal launcher that logs startup errors to a file.
This helps diagnose cases where the GUI does not show.
"""

from __future__ import annotations

import os
import sys
import time
import traceback
from pathlib import Path


def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


LOG_PATH = _base_dir() / "startup.log"


def _log(line: str) -> None:
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except Exception:
        pass


def _log_header() -> None:
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    _log("=" * 60)
    _log(f"[STARTUP] {ts}")
    _log(f"frozen={getattr(sys, 'frozen', False)}")
    _log(f"exe={sys.executable}")
    _log(f"base_dir={_base_dir()}")
    _log(f"sys.path={sys.path}")


def _ensure_edgechromium() -> bool:
    os.environ.setdefault("PYWEBVIEW_GUI", "edgechromium")
    try:
        import webview.platforms.edgechromium  # noqa: F401
        _log("edgechromium backend available")
        return True
    except Exception as exc:
        _log(f"[ERROR] edgechromium backend unavailable: {exc}")
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(  # type: ignore[attr-defined]
                0,
                "WebView2 runtime is missing or unavailable.\nInstall Edge WebView2 Runtime and retry.",
                "Monitoring Dashboard",
                0x10,
            )
        except Exception:
            pass
        return False


def _preflight_imports() -> None:
    required = [
        "main",
        "webview_app",
        "config",
        "application",
        "domain",
        "infrastructure",
        "uvicorn",
        "fastapi",
        "sqlalchemy",
        "webview",
        "webview.platforms.edgechromium",
        "pystray",
        "email.mime.text",
        "email.mime.multipart",
    ]
    for name in required:
        try:
            module = __import__(name)
            if name == "config" and not hasattr(module, "get_settings"):
                _log("[WARN] config loaded but missing get_settings")
        except Exception as exc:
            _log(f"[WARN] import failed: {name} -> {exc}")


def main() -> None:
    _log_header()
    if not _ensure_edgechromium():
        return
    try:
        _preflight_imports()
        _log("import webview_app...")
        import webview_app

        _log("starting app...")
        webview_app.main()
        _log("[EXIT] normal")
    except Exception:
        _log("[ERROR] unhandled exception")
        _log(traceback.format_exc())
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(  # type: ignore[attr-defined]
                0,
                "MonitoringDashboard failed to start.\nCheck startup.log",
                "Monitoring Dashboard",
                0x10,
            )
        except Exception:
            pass


if __name__ == "__main__":
    main()
