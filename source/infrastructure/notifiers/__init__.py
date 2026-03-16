# Notifiers 패키지
from config import get_settings

from .email_notifier import EmailNotifier
from .null_notifier import NullNotifier
from .windows_notifier import WindowsNotifier

_email_notifier = None
_null_notifier = None
_windows_notifier = None


def get_notifier():
    global _email_notifier, _null_notifier, _windows_notifier
    settings = get_settings()
    mode = (settings.notify_mode or "").lower()
    if mode in ("windows", "win", "toast"):
        if _windows_notifier is None:
            _windows_notifier = WindowsNotifier()
        return _windows_notifier
    if mode in ("none", "off", "disabled"):
        if _null_notifier is None:
            _null_notifier = NullNotifier()
        return _null_notifier
    if _email_notifier is None:
        _email_notifier = EmailNotifier()
    return _email_notifier


__all__ = ["EmailNotifier", "WindowsNotifier", "NullNotifier", "get_notifier"]
