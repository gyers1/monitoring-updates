"""
크롤링 서비스 (Use Case)
"""

import asyncio
from datetime import datetime, date

from config import get_settings
from domain import Site, Article, CrawlLog, CrawlResult, CrawlStatus, Category
from domain.interfaces import IArticleRepository, ISiteRepository, ICrawlLogRepository, ICrawler, INotifier


class CrawlService:
    """크롤링 유스케이스"""
    
    def __init__(
        self,
        article_repo: IArticleRepository,
        site_repo: ISiteRepository,
        log_repo: ICrawlLogRepository,
        crawler: ICrawler,
        notifier: INotifier,
    ):
        self.article_repo = article_repo
        self.site_repo = site_repo
        self.log_repo = log_repo
        self.crawler = crawler
        self.notifier = notifier
        self.settings = get_settings()
    
    async def crawl_all_sites(
        self,
        target_date: date | None = None,
        sites: list[Site] | None = None,
    ) -> list[CrawlResult]:
        """모든 활성 사이트 또는 전달된 사이트 목록을 크롤링"""
        sites_to_crawl = sites if sites is not None else self.site_repo.find_all(active_only=True)
        results = []
        all_new_articles = []
        notify_mode = (self.settings.notify_mode or "").lower()
        notify_enabled = notify_mode not in ("none", "off", "disabled")
        notify_all = notify_mode in ("windows", "win", "toast")
        today_key = datetime.now().strftime("%Y-%m-%d")
        notify_only_today = target_date is None or target_date.strftime("%Y-%m-%d") == today_key

        for site in sites_to_crawl:
            result = await self.crawl_site(site, target_date=target_date)
            results.append(result)

            if result.new_articles_count > 0 and notify_only_today:
                new_articles = result.articles[:result.new_articles_count]
                if notify_all:
                    all_new_articles.extend([a for a in new_articles if a.date_key == today_key])
                else:
                    # 키워드 매칭 게시글 수집
                    for article in new_articles:
                        if article.date_key == today_key and article.matches_keywords(self.settings.bill_keywords):
                            all_new_articles.append(article)

        # 키워드 매칭된 새 게시글이 있으면 알림 발송
        if notify_enabled and all_new_articles:
            await self.notifier.notify(all_new_articles)
        
        return results
    
    async def crawl_site(self, site: Site, target_date: date | None = None) -> CrawlResult:
        """단일 사이트 크롤링"""
        print(f"[CRAWL] Start: {site.name}")
        
        # 크롤링 실행
        result = await self.crawler.crawl(site, target_date=target_date)

        if target_date:
            date_key = target_date.strftime("%Y-%m-%d")
            result.articles = [a for a in result.articles if a.date_key == date_key]

        for source_order, article in enumerate(result.articles):
            article.source_order = source_order
        
        # 신규 게시글 저장 (중복 제외)
        if result.status == CrawlStatus.SUCCESS and result.articles:
            new_count = self.article_repo.save_many(result.articles)
            result.new_articles_count = new_count
            print(f"[OK] {site.name}: {new_count} new articles saved")
        else:
            print(f"[WARN] {site.name}: {result.error_message}")
        
        # 마지막 크롤링 시간 업데이트
        self.site_repo.update_last_crawled(site.id)
        
        # 로그 저장
        log = CrawlLog(
            site_id=site.id,
            status=result.status,
            message=result.error_message,
            articles_count=result.new_articles_count,
        )
        self.log_repo.save(log)
        
        return result
    
    async def crawl_site_by_id(self, site_id: int, target_date: date | None = None) -> CrawlResult:
        """ID로 사이트 크롤링"""
        site = self.site_repo.find_by_id(site_id)
        if not site:
            return CrawlResult(
                site=Site(),
                status=CrawlStatus.FAILED,
                error_message=f"사이트를 찾을 수 없습니다: {site_id}"
            )
        return await self.crawl_site(site, target_date=target_date)
