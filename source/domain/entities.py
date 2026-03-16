"""Domain entities for the monitoring application."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class CrawlStatus(Enum):
    """Result of a crawl attempt."""

    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    TIMEOUT = "TIMEOUT"


class Category(Enum):
    """Supported article categories."""

    LEGISLATION = "\uC785\uBC95\uC608\uACE0"
    PRESS_RELEASE = "\uBCF4\uB3C4\uC790\uB8CC"
    BILL = "\uC758\uC548\uC815\uBCF4"
    REGULATION = "\uD589\uC815\uADDC\uCE59"
    NOTICE = "\uACF5\uACE0"
    OTHER = "\uAE30\uD0C0"


@dataclass
class Site:
    """A monitored source site."""

    id: Optional[int] = None
    name: str = ""
    url: str = ""
    selector: str = ""
    date_selector: str = ""
    date_param: str = ""
    start_date_param: str = ""
    end_date_param: str = ""
    date_format: str = "%Y-%m-%d"
    page_size_param: str = ""
    page_size_value: str = ""
    category: str = Category.OTHER.value
    interval_minutes: int = 20
    is_active: bool = True
    last_crawled_at: Optional[datetime] = None

    def should_crawl(self) -> bool:
        """Return True when the site is due for crawling."""

        if not self.is_active:
            return False
        if self.last_crawled_at is None:
            return True
        elapsed = datetime.now() - self.last_crawled_at
        return elapsed.total_seconds() >= self.interval_minutes * 60


@dataclass
class Article:
    """A collected article row."""

    id: Optional[int] = None
    site_id: int = 0
    title: str = ""
    url: str = ""
    content_summary: str = ""
    collected_at: datetime = field(default_factory=datetime.now)
    date_key: str = ""
    site_name: str = ""
    category: str = Category.OTHER.value

    def __post_init__(self) -> None:
        if not self.date_key and self.collected_at:
            self.date_key = self.collected_at.strftime("%Y-%m-%d")

    def matches_keywords(self, keywords: list[str]) -> bool:
        """Return True when the title contains any keyword."""

        return any(kw in self.title for kw in keywords)


@dataclass
class CrawlResult:
    """Result payload returned by crawlers."""

    site: Site
    status: CrawlStatus
    articles: list[Article] = field(default_factory=list)
    new_articles_count: int = 0
    error_message: str = ""


@dataclass
class CrawlLog:
    """Persisted crawl execution log."""

    id: Optional[int] = None
    site_id: int = 0
    status: CrawlStatus = CrawlStatus.SUCCESS
    message: str = ""
    articles_count: int = 0
    crawled_at: datetime = field(default_factory=datetime.now)
    site_name: str = ""
