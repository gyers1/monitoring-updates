"""
Webview launcher for the monitoring server.
Runs the dashboard inside an app window and opens articles in a separate webview.
"""

from __future__ import annotations

import ctypes
import json
import logging
import os
import socket
import sys
import threading
import time
import webbrowser
from logging.handlers import RotatingFileHandler
from pathlib import Path

import pystray
import uvicorn
import webview
from PIL import Image, ImageDraw, ImageFont

from config import get_settings
from infrastructure.notification_center import set_focus_handler
import main as main_module


def _resolve_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


BASE_DIR = _resolve_base_dir()


def _get_screen_size() -> tuple[int, int]:
    try:
        user32 = ctypes.windll.user32  # type: ignore[attr-defined]
        return user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
    except Exception:
        return 1400, 900


def _create_icon(size: int = 64) -> Image.Image:
    image = Image.new("RGB", (size, size), (16, 120, 80))
    draw = ImageDraw.Draw(image)
    draw.rectangle((4, 4, size - 4, size - 4), outline=(255, 255, 255), width=3)
    try:
        font = ImageFont.load_default()
        text = "M"
        text_w, text_h = draw.textsize(text, font=font)
        draw.text(((size - text_w) / 2, (size - text_h) / 2), text, fill=(255, 255, 255), font=font)
    except Exception:
        pass
    return image


class WebviewApi:
    __slots__ = ("_app",)

    def __init__(self, app: "WebviewApp") -> None:
        self._app = app

    def open_preview(self, url: str, title: str | None = None) -> None:
        self._app.open_preview(url, title or "Preview")

    def close_preview(self) -> None:
        self._app.close_preview()

    def open_selector_helper(self, url: str) -> None:
        self._app.open_selector_helper(url)

    def close_selector_helper(self) -> None:
        self._app.close_selector_helper()

    def selector_helper_picked(self, payload: dict) -> None:
        self._app.selector_helper_picked(payload)

    def apply_selector_helper(self, payload: dict) -> None:
        self._app.apply_selector_helper(payload)

    def save_sites_export(self, payload: dict) -> dict:
        return self._app.save_sites_export(payload)

    def pick_sites_import(self) -> dict:
        return self._app.pick_sites_import()

    def open_external(self, url: str) -> None:
        self._app.open_external(url)


class WebviewApp:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.server: uvicorn.Server | None = None
        self.server_thread: threading.Thread | None = None
        self.url = f"http://{self.settings.host}:{self.settings.port}/"
        self.main_window: webview.Window | None = None
        self.preview_window: webview.Window | None = None
        self.helper_window: webview.Window | None = None
        self._helper_payload: dict | None = None
        self.tray_icon: pystray.Icon | None = None
        self.tray_thread: threading.Thread | None = None
        self.allow_exit = False
        self.api: WebviewApi | None = None
        self.log_path = BASE_DIR / "tray.log"
        self._configure_logging()

    def _configure_logging(self) -> None:
        max_bytes = max(1, int(self.settings.log_file_max_mb or 5)) * 1024 * 1024
        backup_count = max(1, int(self.settings.log_file_backup_count or 2))
        level_name = str(self.settings.log_level or "WARNING").upper()
        level = getattr(logging, level_name, logging.WARNING)

        try:
            if self.log_path.exists() and self.log_path.stat().st_size > max_bytes:
                self.log_path.unlink()
        except Exception:
            pass

        root_logger = logging.getLogger()
        for handler in list(root_logger.handlers):
            root_logger.removeHandler(handler)
            try:
                handler.close()
            except Exception:
                pass

        log_handler = RotatingFileHandler(
            self.log_path,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        log_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))

        root_logger.setLevel(level)
        root_logger.addHandler(log_handler)

        for logger_name in (
            "sqlalchemy.engine",
            "sqlalchemy.pool",
            "uvicorn",
            "uvicorn.error",
            "uvicorn.access",
            "pywebview",
        ):
            logger = logging.getLogger(logger_name)
            logger.setLevel(level)
            logger.propagate = True

    def _resource_file(self, *parts: str) -> Path:
        return Path(self.settings.resource_dir).joinpath(*parts)

    def _on_preview_closed(self) -> None:
        self.preview_window = None

    def _on_main_closing(self, *args, **kwargs) -> bool:
        if self.allow_exit:
            return True
        try:
            if self.main_window:
                self.main_window.hide()
        except Exception:
            pass
        return False

    def start_server(self) -> None:
        if self.server_thread and self.server_thread.is_alive():
            return
        os.chdir(self.settings.base_dir)
        selected_port = self._select_available_port()
        if selected_port != self.settings.port:
            logging.warning("Port %s busy. Switching to %s.", self.settings.port, selected_port)
            self.settings.port = selected_port
            self.url = f"http://{self.settings.host}:{self.settings.port}/"
        try:
            asgi_app = main_module.app
        except Exception as exc:
            logging.exception("Failed to import main app: %s", exc)
            return

        config = uvicorn.Config(
            asgi_app,
            host=self.settings.host,
            port=self.settings.port,
            log_level="warning",
            access_log=False,
            log_config=None,
        )
        self.server = uvicorn.Server(config)
        self.server_thread = threading.Thread(target=self._run_server, daemon=True)
        self.server_thread.start()
        time.sleep(0.6)
        if not getattr(self.server, "started", False):
            logging.error("Server failed to start. Check configuration or port.")

    def _run_server(self) -> None:
        try:
            logging.info("Starting server")
            if self.server:
                self.server.run()
        except Exception as exc:
            logging.exception("Server crashed: %s", exc)

    def stop_server(self) -> None:
        if not self.server:
            return
        self.server.should_exit = True
        self.server = None

    def _is_port_free(self, host: str, port: int) -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind((host, port))
                return True
            except OSError:
                return False

    def _select_available_port(self) -> int:
        host = self.settings.host
        base_port = int(self.settings.port)
        if self._is_port_free(host, base_port):
            return base_port
        for offset in range(1, 51):
            candidate = base_port + offset
            if self._is_port_free(host, candidate):
                return candidate
        raise RuntimeError("No available port found.")

    def open_preview(self, url: str, title: str) -> None:
        if not url:
            return
        try:
            if self.preview_window:
                self.preview_window.load_url(url)
                try:
                    self.preview_window.set_title(title)
                except Exception:
                    pass
                try:
                    self.preview_window.show()
                except Exception:
                    pass
                try:
                    self._inject_preview_download_guard()
                except Exception:
                    pass
                return
        except Exception:
            self.preview_window = None

        screen_w, screen_h = _get_screen_size()
        width = max(820, int(screen_w * 0.55))
        height = max(760, int(screen_h * 0.94))
        x = max(0, screen_w - width)
        y = 0
        self.preview_window = webview.create_window(
            title,
            url,
            width=width,
            height=height,
            x=x,
            y=y,
            resizable=True,
            js_api=self.api,
        )
        try:
            self.preview_window.events.closed += self._on_preview_closed
        except Exception:
            pass
        try:
            self.preview_window.events.loaded += lambda: self._inject_preview_download_guard()
        except Exception:
            pass

    def close_preview(self) -> None:
        if not self.preview_window:
            return
        try:
            self.preview_window.hide()
        except Exception:
            pass
        self.preview_window = None

    def _on_helper_closed(self) -> None:
        self.helper_window = None

    def open_selector_helper(self, url: str) -> None:
        if not url:
            return
        helper_url = url
        try:
            if self.helper_window:
                self.helper_window.load_url(helper_url)
                try:
                    self.helper_window.show()
                except Exception:
                    pass
                return
        except Exception:
            self.helper_window = None

        screen_w, screen_h = _get_screen_size()
        width = max(1200, int(screen_w * 0.96))
        height = max(800, int(screen_h * 0.95))
        self.helper_window = webview.create_window(
            "선택자 도우미",
            helper_url,
            width=width,
            height=height,
            x=0,
            y=0,
            resizable=True,
            js_api=self.api,
        )
        try:
            self.helper_window.events.closed += self._on_helper_closed
        except Exception:
            pass
        try:
            self.helper_window.events.loaded += lambda: self._inject_selector_helper()
        except Exception:
            pass

    def close_selector_helper(self) -> None:
        if not self.helper_window:
            return
        try:
            self.helper_window.hide()
        except Exception:
            pass
        self.helper_window = None

    def _inject_selector_helper(self) -> None:
        js_path = self._resource_file("presentation", "static", "selector_helper_inject.js")
        if not js_path.exists():
            return
        try:
            js_code = js_path.read_text(encoding="utf-8")
        except Exception:
            return
        if not self.helper_window:
            return
        try:
            self.helper_window.evaluate_js(js_code)
        except Exception:
            pass

    def _inject_preview_download_guard(self) -> None:
        if not self.preview_window:
            return
        js_path = self._resource_file("presentation", "static", "preview_download_guard.js")
        if not js_path.exists():
            return
        try:
            js_code = js_path.read_text(encoding="utf-8")
        except Exception:
            return
        try:
            self.preview_window.evaluate_js(js_code)
        except Exception:
            pass

    def selector_helper_picked(self, payload: dict) -> None:
        self._helper_payload = payload
        if not self.main_window:
            return
        try:
            self.main_window.evaluate_js(
                f"window.receiveSelectorHelperSelection({json.dumps(payload, ensure_ascii=False)});"
            )
        except Exception:
            pass

    def apply_selector_helper(self, payload: dict) -> None:
        self._helper_payload = payload
        if not self.main_window:
            return
        try:
            self.main_window.evaluate_js(
                f"window.applySelectorHelperSelection({json.dumps(payload, ensure_ascii=False)});"
            )
        except Exception:
            pass

    @staticmethod
    def _pick_single_path(result) -> str | None:
        if not result:
            return None
        if isinstance(result, (list, tuple)):
            if not result:
                return None
            return str(result[0])
        return str(result)

    def save_sites_export(self, payload: dict) -> dict:
        if not self.main_window:
            return {"ok": False, "message": "main_window_not_ready"}

        export_data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        filename = str(payload.get("filename") or "monitoring_sites_export.json")
        if not filename.lower().endswith(".json"):
            filename = f"{filename}.json"

        try:
            selected = self.main_window.create_file_dialog(
                webview.SAVE_DIALOG,
                save_filename=filename,
                file_types=("JSON Files (*.json)", "All files (*.*)"),
            )
            target = self._pick_single_path(selected)
            if not target:
                return {"ok": False, "cancelled": True}
            Path(target).write_text(
                json.dumps(export_data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            return {"ok": True, "path": target}
        except Exception as exc:
            logging.exception("save_sites_export failed: %s", exc)
            return {"ok": False, "message": str(exc)}

    def pick_sites_import(self) -> dict:
        if not self.main_window:
            return {"ok": False, "message": "main_window_not_ready"}

        try:
            selected = self.main_window.create_file_dialog(
                webview.OPEN_DIALOG,
                allow_multiple=False,
                file_types=("JSON Files (*.json)", "All files (*.*)"),
            )
            source = self._pick_single_path(selected)
            if not source:
                return {"ok": False, "cancelled": True}
            raw = json.loads(Path(source).read_text(encoding="utf-8-sig"))
            sites = raw.get("sites") if isinstance(raw, dict) else None
            if not isinstance(sites, list):
                return {"ok": False, "message": "invalid_format"}
            category_order = raw.get("category_order") if isinstance(raw, dict) else None
            if not isinstance(category_order, list):
                category_order = None
            return {
                "ok": True,
                "path": source,
                "sites": sites,
                "category_order": category_order,
            }
        except Exception as exc:
            logging.exception("pick_sites_import failed: %s", exc)
            return {"ok": False, "message": str(exc)}

    def open_external(self, url: str) -> None:
        if not url:
            return
        try:
            os.startfile(url)  # type: ignore[attr-defined]
            return
        except Exception:
            pass
        try:
            webbrowser.open(url)
        except Exception:
            pass

    def show_main(self, _icon=None, _item=None) -> None:
        if not self.main_window:
            return
        try:
            self.main_window.show()
        except Exception:
            pass

    def exit_app(self, _icon=None, _item=None) -> None:
        self.allow_exit = True
        set_focus_handler(None)
        self.stop_server()
        try:
            if self.preview_window:
                webview.destroy_window(self.preview_window)
        except Exception:
            pass
        try:
            if self.main_window:
                webview.destroy_window(self.main_window)
        except Exception:
            pass
        if self.tray_icon:
            try:
                self.tray_icon.stop()
            except Exception:
                pass

    def _start_tray(self) -> None:
        if self.tray_icon:
            return
        menu = pystray.Menu(
            pystray.MenuItem("Open dashboard", self.show_main),
            pystray.MenuItem("Exit", self.exit_app),
        )
        self.tray_icon = pystray.Icon("monitoring", _create_icon(), "Monitoring Dashboard", menu)
        self.tray_thread = threading.Thread(target=self.tray_icon.run, daemon=True)
        self.tray_thread.start()

    def focus_notification_intent(self, _intent: dict | None = None) -> None:
        self.show_main()
        try:
            if self.main_window:
                self.main_window.evaluate_js(
                    "window.consumeNotificationIntent && window.consumeNotificationIntent();"
                )
        except Exception:
            pass

    def run(self) -> None:
        set_focus_handler(self.focus_notification_intent)
        self.start_server()
        screen_w, screen_h = _get_screen_size()
        main_width = min(screen_w, max(1280, int(screen_w * 0.68)))
        main_height = min(screen_h, max(720, int(screen_h * 0.9)))
        api = WebviewApi(self)
        self.api = api
        self.main_window = webview.create_window(
            "Monitoring Dashboard",
            self.url,
            width=main_width,
            height=main_height,
            x=0,
            y=0,
            resizable=True,
            js_api=api,
        )
        try:
            self.main_window.events.closing += self._on_main_closing
        except Exception:
            pass
        self._start_tray()
        webview.start(gui="edgechromium", debug=False, http_server=False)


def main() -> None:
    app = WebviewApp()
    app.run()


if __name__ == "__main__":
    main()
