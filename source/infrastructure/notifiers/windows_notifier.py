"""Windows toast notifier."""

from __future__ import annotations

import logging
import sys
import threading
from collections import Counter
from datetime import datetime
from pathlib import Path

from config import get_settings
from domain import Article, INotifier
from infrastructure.windows_toast_support import ensure_start_menu_shortcut, set_current_process_app_id

try:
    from winotify import Notification, audio
except Exception:  # pragma: no cover - optional dependency
    Notification = None
    audio = None


logger = logging.getLogger(__name__)


class WindowsNotifier(INotifier):
    """Show summary Windows toast notifications for new articles."""

    _buffer_lock = threading.Lock()
    _buffer_timer: threading.Timer | None = None
    _buffer_articles: dict[str, Article] = {}

    def __init__(self) -> None:
        settings = get_settings()
        self.app_id = settings.windows_app_id or "Monitoring Dashboard"
        self.max_per_run = settings.notify_max_per_run
        self.buffer_seconds = 60
        self.last_status_message = ""
        self._shortcut_ready = False
        self._shortcut_path: Path | None = None

    async def notify(self, articles: list[Article], subject: str = "") -> bool:
        if not articles:
            self.last_status_message = "표시할 알림이 없습니다."
            return True
        if not self._ensure_ready():
            return False

        # Explicit test notifications should appear immediately.
        if subject:
            return self._show_toast(articles, subject=subject)

        self._queue_articles(articles)
        return True

    def _set_error(self, message: str, exc: Exception | None = None) -> bool:
        self.last_status_message = message
        if exc is not None:
            logger.exception(message)
        else:
            logger.warning(message)
        print(f"[WARN] {message}")
        return False

    def _ensure_ready(self) -> bool:
        if sys.platform != "win32":
            return self._set_error("WindowsNotifier is only available on Windows.")
        if Notification is None:
            return self._set_error("winotify is not installed. Skipping Windows notifications.")

        try:
            set_current_process_app_id(self.app_id)
        except Exception as exc:
            return self._set_error("윈도우 AppUserModelID 등록에 실패했습니다.", exc)

        if self._shortcut_ready:
            return True

        try:
            self._shortcut_path = ensure_start_menu_shortcut(self.app_id)
            self._shortcut_ready = True
            self.last_status_message = f"윈도우 알림 바로가기를 확인했습니다: {self._shortcut_path}"
            logger.info("Windows toast shortcut ready: %s", self._shortcut_path)
            return True
        except Exception as exc:
            return self._set_error("윈도우 알림용 시작 메뉴 바로가기 준비에 실패했습니다.", exc)

    def _build_summary_message(self, articles: list[Article]) -> str:
        counts = Counter((article.category or article.site_name or "기타") for article in articles)
        parts = [f"{name} {count}건" for name, count in counts.most_common(4)]
        if len(counts) > 4:
            parts.append(f"외 {len(counts) - 4}개 분류")
        summary = " / ".join(parts).strip()
        return summary or "새 기사를 확인하세요"

    def flush_pending(self) -> bool:
        if not self._ensure_ready():
            return False

        cls = type(self)
        with cls._buffer_lock:
            articles = list(cls._buffer_articles.values())
            cls._buffer_articles = {}
            timer = cls._buffer_timer
            cls._buffer_timer = None

        if timer:
            try:
                timer.cancel()
            except Exception:
                pass

        if not articles:
            self.last_status_message = "대기 중인 윈도우 알림이 없습니다."
            return True

        logger.info("Flushing %s buffered Windows notification articles", len(articles))
        return self._show_toast(articles)

    def _queue_articles(self, articles: list[Article]) -> None:
        cls = type(self)
        should_start_timer = False
        with cls._buffer_lock:
            for article in articles:
                cls._buffer_articles[self._article_key(article)] = article
            if cls._buffer_timer is None:
                cls._buffer_timer = threading.Timer(self.buffer_seconds, self.flush_pending)
                cls._buffer_timer.daemon = True
                should_start_timer = True
                timer = cls._buffer_timer
            else:
                timer = cls._buffer_timer
            pending_count = len(cls._buffer_articles)

        self.last_status_message = (
            f"새 기사 {pending_count}건 알림을 {self.buffer_seconds}초 내 요약 알림으로 대기시켰습니다."
        )
        logger.info(
            "Buffered %s Windows notification articles (pending=%s, buffer=%ss)",
            len(articles),
            pending_count,
            self.buffer_seconds,
        )
        if should_start_timer and timer:
            timer.start()

    @staticmethod
    def _article_key(article: Article) -> str:
        if article.url:
            return article.url
        if article.id is not None:
            return f"id:{article.id}"
        return f"{article.site_name}:{article.title}:{article.date_key}"

    def _build_launch_url(self) -> str:
        settings = get_settings()
        today = datetime.now().strftime("%Y-%m-%d")
        return f"http://{settings.host}:{settings.port}/notification-open?date_key={today}&show_unread=1"

    def _show_toast(self, articles: list[Article], subject: str = "") -> bool:
        title = subject or f"새 모니터링 {len(articles)}건"
        message = self._build_summary_message(articles)
        launch_url = self._build_launch_url()

        try:
            toast = Notification(
                app_id=self.app_id,
                title=title,
                msg=message,
                launch=launch_url,
            )
            toast.add_actions(label="대시보드 열기", launch=launch_url)
            if audio:
                toast.set_audio(audio.Default, loop=False)
            toast.show()
            self.last_status_message = f"윈도우 알림 요청을 보냈습니다: {title}"
            logger.info(
                "Windows toast requested: title=%s, message=%s, launch=%s, articles=%s",
                title,
                message,
                launch_url,
                len(articles),
            )
            return True
        except Exception as exc:
            return self._set_error("윈도우 알림 표시에 실패했습니다.", exc)
