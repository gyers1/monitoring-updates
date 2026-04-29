"""
Repository 구현체
Domain 인터페이스를 SQLAlchemy로 구현
"""

from datetime import datetime
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import func, select

from domain import (
    Article, Site, CrawlLog, CrawlStatus,
    IArticleRepository, ISiteRepository, ICrawlLogRepository
)
from .models import ArticleModel, SiteModel, CrawlLogModel


class ArticleRepository(IArticleRepository):
    """게시글 저장소 구현"""
    
    def __init__(self, session: Session):
        self.session = session
    
    def save(self, article: Article) -> Article:
        """게시글 저장 (중복 URL 스킵)"""
        if self.exists_by_url(article.url):
            return article
        
        model = ArticleModel(
            site_id=article.site_id,
            title=article.title,
            url=article.url,
            content_summary=article.content_summary,
            collected_at=article.collected_at,
            date_key=article.date_key,
            source_order=article.source_order,
        )
        self.session.add(model)
        self.session.commit()
        self.session.refresh(model)
        article.id = model.id
        return article
    
    def save_many(self, articles: list[Article]) -> int:
        """여러 게시글 저장, 신규 저장 건수 반환"""
        saved_count = 0
        updated_count = 0
        for article in articles:
            existing = (
                self.session.query(ArticleModel)
                .filter(ArticleModel.url == article.url)
                .first()
            )
            if existing:
                # If saved with a wrong date_key, fix it instead of skipping.
                article_source_order = int(getattr(article, "source_order", 0) or 0)
                if (
                    existing.date_key != article.date_key
                    or existing.collected_at != article.collected_at
                    or (existing.source_order or 0) != article_source_order
                ):
                    existing.date_key = article.date_key
                    existing.collected_at = article.collected_at
                    existing.source_order = article_source_order
                    if article.title and existing.title != article.title:
                        existing.title = article.title
                    if article.content_summary and existing.content_summary != article.content_summary:
                        existing.content_summary = article.content_summary
                    updated_count += 1
                continue
            if self.exists_by_title_and_date(article.site_id, article.title, article.date_key):
                # Same title/date can be saved earlier with a list URL.
                # If we now found a better detail URL, update it in-place.
                existing_td = (
                    self.session.query(ArticleModel)
                    .filter(
                        ArticleModel.site_id == article.site_id,
                        ArticleModel.title == article.title,
                        ArticleModel.date_key == article.date_key,
                    )
                    .first()
                )
                if existing_td and article.url and existing_td.url != article.url:
                    existing_td.url = article.url
                    existing_td.source_order = int(getattr(article, "source_order", 0) or 0)
                    if article.content_summary and existing_td.content_summary != article.content_summary:
                        existing_td.content_summary = article.content_summary
                    updated_count += 1
                continue
            
            model = ArticleModel(
                site_id=article.site_id,
                title=article.title,
                url=article.url,
                content_summary=article.content_summary,
                collected_at=article.collected_at,
                date_key=article.date_key,
                source_order=article.source_order,
            )
            self.session.add(model)
            saved_count += 1
        
        if saved_count > 0 or updated_count > 0:
            self.session.commit()
        return saved_count
    
    def find_by_date(self, date_key: str) -> list[Article]:
        """날짜별 게시글 조회"""
        query = (
            self.session.query(ArticleModel, SiteModel)
            .join(SiteModel)
            .filter(ArticleModel.date_key == date_key)
            .order_by(
                ArticleModel.collected_at.desc(),
                SiteModel.id.asc(),
                ArticleModel.source_order.asc(),
                ArticleModel.id.asc(),
            )
        )
        
        return [self._to_entity(m, s) for m, s in query.all()]
    
    def find_by_site_and_date(self, site_id: int, date_key: str) -> list[Article]:
        """사이트 및 날짜별 게시글 조회"""
        query = (
            self.session.query(ArticleModel, SiteModel)
            .join(SiteModel)
            .filter(
                ArticleModel.site_id == site_id,
                ArticleModel.date_key == date_key
            )
            .order_by(
                ArticleModel.collected_at.desc(),
                ArticleModel.source_order.asc(),
                ArticleModel.id.asc(),
            )
        )
        
        return [self._to_entity(m, s) for m, s in query.all()]
    
    def exists_by_url(self, url: str) -> bool:
        """URL로 중복 확인"""
        return self.session.query(
            self.session.query(ArticleModel)
            .filter(ArticleModel.url == url)
            .exists()
        ).scalar()
    
    def exists_by_title_and_date(self, site_id: int, title: str, date_key: str) -> bool:
        """제목+날짜로 중복 확인"""
        return self.session.query(
            self.session.query(ArticleModel)
            .filter(
                ArticleModel.site_id == site_id,
                ArticleModel.title == title,
                ArticleModel.date_key == date_key
            )
            .exists()
        ).scalar()
    
    def get_stats(self, date_key: Optional[str] = None) -> dict:
        """통계 조회"""
        query = self.session.query(func.count(ArticleModel.id))
        if date_key:
            query = query.filter(ArticleModel.date_key == date_key)
        
        total = query.scalar()
        
        # 카테고리별 통계
        category_query = (
            self.session.query(
                SiteModel.category,
                func.count(ArticleModel.id)
            )
            .join(SiteModel)
            .group_by(SiteModel.category)
        )
        if date_key:
            category_query = category_query.filter(ArticleModel.date_key == date_key)
        
        by_category = {cat: cnt for cat, cnt in category_query.all()}
        
        return {
            "total": total,
            "by_category": by_category,
            "date_key": date_key or "all"
        }
    
    def _to_entity(self, model: ArticleModel, site: SiteModel) -> Article:
        """모델을 엔티티로 변환"""
        return Article(
            id=model.id,
            site_id=model.site_id,
            title=model.title,
            url=model.url,
            content_summary=model.content_summary,
            collected_at=model.collected_at,
            date_key=model.date_key,
            source_order=getattr(model, "source_order", 0) or 0,
            site_name=site.name,
            category=site.category or "기타",
        )


class SiteRepository(ISiteRepository):
    """사이트 저장소 구현"""
    
    def __init__(self, session: Session):
        self.session = session
    
    def find_all(self, active_only: bool = True) -> list[Site]:
        """전체 사이트 조회"""
        query = self.session.query(SiteModel)
        if active_only:
            query = query.filter(SiteModel.is_active == True)
        
        return [self._to_entity(m) for m in query.all()]
    
    def find_by_id(self, site_id: int) -> Optional[Site]:
        """ID로 사이트 조회"""
        model = self.session.query(SiteModel).filter(SiteModel.id == site_id).first()
        return self._to_entity(model) if model else None
    
    def find_by_url(self, url: str) -> Optional[Site]:
        """URL로 사이트 조회"""
        model = self.session.query(SiteModel).filter(SiteModel.url == url).first()
        return self._to_entity(model) if model else None
    
    def save(self, site: Site) -> Site:
        """사이트 저장"""
        if site.id:
            model = self.session.query(SiteModel).filter(SiteModel.id == site.id).first()
            if model:
                model.name = site.name
                model.url = site.url
                model.selector = site.selector
                model.date_selector = site.date_selector
                model.date_param = site.date_param
                model.start_date_param = site.start_date_param
                model.end_date_param = site.end_date_param
                model.date_format = site.date_format
                model.page_size_param = site.page_size_param
                model.page_size_value = site.page_size_value
                model.category = getattr(site.category, "value", site.category)
                model.interval_minutes = site.interval_minutes
                model.is_active = site.is_active
        else:
            category_value = getattr(site.category, "value", site.category)
            model = SiteModel(
                name=site.name,
                url=site.url,
                selector=site.selector,
                date_selector=site.date_selector,
                date_param=site.date_param,
                start_date_param=site.start_date_param,
                end_date_param=site.end_date_param,
                date_format=site.date_format,
                page_size_param=site.page_size_param,
                page_size_value=site.page_size_value,
                category=category_value,
                interval_minutes=site.interval_minutes,
                is_active=site.is_active,
            )
            self.session.add(model)
        
        self.session.commit()
        self.session.refresh(model)
        site.id = model.id
        return site
    
    def update_last_crawled(self, site_id: int) -> None:
        """마지막 크롤링 시간 업데이트"""
        model = self.session.query(SiteModel).filter(SiteModel.id == site_id).first()
        if model:
            model.last_crawled_at = datetime.now()
            self.session.commit()
    
    def delete(self, site_id: int) -> bool:
        """사이트 삭제"""
        model = self.session.query(SiteModel).filter(SiteModel.id == site_id).first()
        if model:
            self.session.query(ArticleModel).filter(ArticleModel.site_id == site_id).delete(synchronize_session=False)
            self.session.query(CrawlLogModel).filter(CrawlLogModel.site_id == site_id).delete(synchronize_session=False)
            self.session.delete(model)
            self.session.commit()
            return True
        return False
    
    def _to_entity(self, model: SiteModel) -> Site:
        """모델을 엔티티로 변환"""
        return Site(
            id=model.id,
            name=model.name,
            url=model.url,
            selector=model.selector,
            date_selector=model.date_selector or "",
            date_param=getattr(model, "date_param", "") or "",
            start_date_param=getattr(model, "start_date_param", "") or "",
            end_date_param=getattr(model, "end_date_param", "") or "",
            date_format=getattr(model, "date_format", "") or "%Y-%m-%d",
            page_size_param=getattr(model, "page_size_param", "") or "",
            page_size_value=getattr(model, "page_size_value", "") or "",
            category=model.category or "기타",
            interval_minutes=model.interval_minutes,
            is_active=model.is_active,
            last_crawled_at=model.last_crawled_at,
        )


class CrawlLogRepository(ICrawlLogRepository):
    """크롤링 로그 저장소 구현"""
    
    def __init__(self, session: Session):
        self.session = session
    
    def save(self, log: CrawlLog) -> CrawlLog:
        """로그 저장"""
        model = CrawlLogModel(
            site_id=log.site_id,
            status=log.status.value,
            message=log.message,
            articles_count=log.articles_count,
            crawled_at=log.crawled_at,
        )
        self.session.add(model)
        self.session.commit()
        self.session.refresh(model)
        log.id = model.id
        return log
    
    def find_recent(self, limit: int = 100) -> list[CrawlLog]:
        """최근 로그 조회"""
        query = (
            self.session.query(CrawlLogModel, SiteModel)
            .join(SiteModel)
            .order_by(CrawlLogModel.crawled_at.desc())
            .limit(limit)
        )
        
        return [self._to_entity(m, s) for m, s in query.all()]

    def delete_older_than(self, cutoff: datetime) -> int:
        """Delete old crawl logs and return the deleted count."""

        deleted = (
            self.session.query(CrawlLogModel)
            .filter(CrawlLogModel.crawled_at < cutoff)
            .delete(synchronize_session=False)
        )
        if deleted:
            self.session.commit()
        return deleted
    
    def _to_entity(self, model: CrawlLogModel, site: SiteModel) -> CrawlLog:
        """모델을 엔티티로 변환"""
        return CrawlLog(
            id=model.id,
            site_id=model.site_id,
            status=CrawlStatus(model.status),
            message=model.message,
            articles_count=model.articles_count,
            crawled_at=model.crawled_at,
            site_name=site.name,
        )
