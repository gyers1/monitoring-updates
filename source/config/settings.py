"""Application settings for the monitoring dashboard."""

from functools import lru_cache
from pathlib import Path
import sys

from pydantic_settings import BaseSettings, SettingsConfigDict


def _resolve_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def _resolve_resource_dir(base_dir: Path) -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", base_dir)).resolve()
    return base_dir


class Settings(BaseSettings):
    """Runtime configuration loaded from environment variables/.env."""

    app_name: str = "Monitoring Dashboard"
    debug: bool = False
    sql_echo: bool = False
    log_level: str = "WARNING"
    log_file_max_mb: int = 5
    log_file_backup_count: int = 2
    crawl_log_retention_days: int = 30

    host: str = "127.0.0.1"
    port: int = 8000

    database_url: str = "sqlite:///./monitoring.db"

    crawl_interval_minutes: int = 20
    request_timeout_seconds: int = 30
    max_retries: int = 3
    retry_delay_seconds: int = 5

    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    email_from: str = ""
    email_to: str = ""

    notify_mode: str = "email"  # email | windows | none
    notify_max_per_run: int = 5
    windows_app_id: str = "Monitoring Dashboard"

    auth_script_url: str = ""
    auth_token: str = ""
    auth_cache_days: int = 7

    update_url: str = ""
    # Fallback only. Runtime version should come from .env/version.json.
    app_version: str = ""

    # Keywords used by article matcher for new bill/regulation style notifications.
    bill_keywords: list[str] = [
        "\uC785\uBC95\uC608\uACE0",
        "\uAC1C\uC815\uC548",
        "\uC2DC\uD589\uB839",
        "\uC2DC\uD589\uADDC\uCE59",
        "\uD589\uC815\uC608\uACE0",
        "\uACE0\uC2DC",
        "\uD6C8\uB839",
        "\uC608\uADDC",
        "\uC870\uB840",
        "\uADDC\uCE59",
        "\uBC95\uB960\uC548",
        "\uBC95\uB839\uC548",
        "\uD589\uC815\uADDC\uCE59",
        "\uACF5\uD3EC",
    ]

    base_dir: Path = _resolve_base_dir()
    resource_dir: Path = _resolve_resource_dir(base_dir)
    sites_config_path: Path = resource_dir / "config" / "sites.json"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8-sig",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
