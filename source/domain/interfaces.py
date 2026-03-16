"""
도메인 인터페이스 정의 (추상 클래스)
Dependency Inversion Principle 적용
"""

from abc import ABC, abstractmethod
from datetime import date
from typing import Optional

from .entities import Article, Site, CrawlLog, CrawlResult


class IArticleRepository(ABC):
    """게시글 저장소 인터페이스"""
    
    @abstractmethod
    def save(self, article: Article) -> Article:
        """게시글 저장 (중복 시 스킵)"""
        pass
    
    @abstractmethod
    def save_many(self, articles: list[Article]) -> int:
        """여러 게시글 저장, 신규 저장 건수 반환"""
        pass
    
    @abstractmethod
    def find_by_date(self, date_key: str) -> list[Article]:
        """날짜별 게시글 조회"""
        pass
    
    @abstractmethod
    def find_by_site_and_date(self, site_id: int, date_key: str) -> list[Article]:
        """사이트 및 날짜별 게시글 조회"""
        pass
    
    @abstractmethod
    def exists_by_url(self, url: str) -> bool:
        """URL로 중복 확인"""
        pass
    
    @abstractmethod
    def get_stats(self, date_key: Optional[str] = None) -> dict:
        """통계 조회"""
        pass


class ISiteRepository(ABC):
    """사이트 저장소 인터페이스"""
    
    @abstractmethod
    def find_all(self, active_only: bool = True) -> list[Site]:
        """전체 사이트 조회"""
        pass
    
    @abstractmethod
    def find_by_id(self, site_id: int) -> Optional[Site]:
        """ID로 사이트 조회"""
        pass
    
    @abstractmethod
    def save(self, site: Site) -> Site:
        """사이트 저장"""
        pass
    
    @abstractmethod
    def update_last_crawled(self, site_id: int) -> None:
        """마지막 크롤링 시간 업데이트"""
        pass


class ICrawlLogRepository(ABC):
    """크롤링 로그 저장소 인터페이스"""
    
    @abstractmethod
    def save(self, log: CrawlLog) -> CrawlLog:
        """로그 저장"""
        pass
    
    @abstractmethod
    def find_recent(self, limit: int = 100) -> list[CrawlLog]:
        """최근 로그 조회"""
        pass


class ICrawler(ABC):
    """크롤러 인터페이스"""
    
    @abstractmethod
    async def crawl(self, site: Site, target_date: date | None = None) -> CrawlResult:
        """사이트 크롤링 실행"""
        pass


class INotifier(ABC):
    """알림 발송 인터페이스"""
    
    @abstractmethod
    async def notify(self, articles: list[Article], subject: str = "") -> bool:
        """알림 발송"""
        pass
