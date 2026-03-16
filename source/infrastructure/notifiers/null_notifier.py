"""
No-op notifier.
"""

from domain import Article, INotifier


class NullNotifier(INotifier):
    """Do nothing."""

    async def notify(self, articles: list[Article], subject: str = "") -> bool:
        return True
