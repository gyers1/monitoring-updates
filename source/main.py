"""
웹사이트 모니터링 시스템 - 메인 진입점
"""

import asyncio
import json
from datetime import datetime, date, timedelta
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import get_settings, resolve_runtime_version
from infrastructure.database import (
    init_database,
    get_session_factory,
    ArticleRepository,
    SiteRepository,
    CrawlLogRepository,
    vacuum_sqlite_database,
)
from infrastructure.crawlers import WebCrawler
from infrastructure.notifiers import get_notifier
from infrastructure.auth import is_session_ok
from infrastructure.notification_center import (
    build_dashboard_intent,
    peek_intent,
    pop_intent,
    push_intent,
)
from presentation.api import router
from application import CrawlService
from domain import Site, Category


# 스케줄러
scheduler = AsyncIOScheduler()
scheduled_category_cursor = 0
DEFAULT_SITE_INTERVAL_MINUTES = 20
LEGACY_INTERVAL_MIGRATION_MARKER = ".interval_defaults_20m_migrated"
LEGACY_SITE_URL_REPLACEMENTS = {
    ("환경부 보도·설명자료", Category.PRESS_RELEASE.value): {
        "https://www.mcee.go.kr/home/web/index.do?menuId=10525": "https://www.mcee.go.kr/home/web/index.do?menuId=10598",
    },
}


def _parse_date_key(date_key: str | None) -> date | None:
    if not date_key:
        return None
    try:
        return datetime.strptime(date_key, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="date_key must be YYYY-MM-DD")


def _select_due_sites_for_tick(sites: list[Site]) -> tuple[str | None, list[Site]]:
    global scheduled_category_cursor

    due_by_category: dict[str, list[Site]] = {}
    for site in sites:
        if not site.should_crawl():
            continue
        category = site.category or Category.OTHER.value
        due_by_category.setdefault(category, []).append(site)

    if not due_by_category:
        return None, []

    categories = sorted(due_by_category.keys())
    index = scheduled_category_cursor % len(categories)
    selected_category = categories[index]
    scheduled_category_cursor = (index + 1) % len(categories)
    return selected_category, due_by_category[selected_category]


def _interval_migration_marker_path() -> Path:
    settings = get_settings()
    return Path(settings.base_dir) / LEGACY_INTERVAL_MIGRATION_MARKER


def migrate_legacy_default_intervals(repo: SiteRepository, sites: list[Site]) -> int:
    marker_path = _interval_migration_marker_path()
    if marker_path.exists() or not sites:
        return 0

    normalized = {
        max(1, int(site.interval_minutes or DEFAULT_SITE_INTERVAL_MINUTES))
        for site in sites
    }
    if normalized != {30}:
        return 0

    for site in sites:
        site.interval_minutes = DEFAULT_SITE_INTERVAL_MINUTES
        repo.save(site)

    marker_path.write_text(
        f"migrated_at={datetime.now().isoformat()}\ninterval_minutes={DEFAULT_SITE_INTERVAL_MINUTES}\n",
        encoding="utf-8",
    )
    print(
        f"[OK] Legacy interval defaults migrated: {len(sites)} sites -> "
        f"{DEFAULT_SITE_INTERVAL_MINUTES} minutes"
    )
    return len(sites)


async def scheduled_crawl(target_date: date | None = None):
    """스케줄 자동 수집 또는 수동 전체 수집"""
    print("\n[SCHEDULE] Crawling started...")

    SessionLocal = get_session_factory()
    session = SessionLocal()

    try:
        site_repo = SiteRepository(session)
        service = CrawlService(
            article_repo=ArticleRepository(session),
            site_repo=site_repo,
            log_repo=CrawlLogRepository(session),
            crawler=WebCrawler(),
            notifier=get_notifier(),
        )

        active_sites = site_repo.find_all(active_only=True)
        selected_category = None
        crawl_sites = active_sites

        if target_date is None:
            selected_category, crawl_sites = _select_due_sites_for_tick(active_sites)
            if not crawl_sites:
                print("[SCHEDULE] No sites due for crawling.")
                return
            print(f"[SCHEDULE] Category tick: {selected_category} ({len(crawl_sites)} sites)")
        else:
            print(f"[SCHEDULE] Manual crawl: {target_date.strftime('%Y-%m-%d')} ({len(crawl_sites)} sites)")

        results = await service.crawl_all_sites(target_date=target_date, sites=crawl_sites)

        success_count = sum(1 for r in results if r.status.value == "SUCCESS")
        total_articles = sum(r.new_articles_count for r in results)
        scope_label = selected_category or (target_date.strftime('%Y-%m-%d') if target_date else 'manual')
        print(f"[OK] Crawl done [{scope_label}]: {success_count}/{len(results)} sites, new {total_articles} articles")

    except Exception as e:
        print(f"[ERROR] Scheduled crawl error: {e}")
    finally:
        session.close()


def migrate_sites_from_target_json():
    """TARGET.json에서 사이트 설정 마이그레이션"""
    settings = get_settings()
    target_path = Path(settings.resource_dir) / "TARGET.json"
    
    if not target_path.exists():
        print("[WARN] TARGET.json file not found.")
        return []
    
    try:
        with open(target_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        sites = []
        for item in data.get("data", []):
            name = item.get("name", "")
            url = item.get("uri", "")
            
            # config에서 CSS 선택자 추출
            config_str = item.get("config", "{}")
            config = json.loads(config_str)
            
            selector = ""
            selections = config.get("selections", [])
            if selections and selections[0].get("frames"):
                frames = selections[0]["frames"]
                if frames and frames[0].get("includes"):
                    includes = frames[0]["includes"]
                    if includes:
                        selector = includes[0].get("expr", "")
            
            # 카테고리 분류
            category = _guess_category(name)
            
            site = Site(
                name=name,
                url=url,
                selector=selector,
                category=category,
                interval_minutes=DEFAULT_SITE_INTERVAL_MINUTES,
                is_active=True,
            )
            sites.append(site)
        
        print(f"[LOAD] Loaded {len(sites)} sites from TARGET.json")
        return sites
        
    except Exception as e:
        print(f"[ERROR] TARGET.json migration error: {e}")
        return []


def load_sites_from_config():
    """config/sites.json에서 사이트 설정 로드"""
    settings = get_settings()
    config_path = settings.sites_config_path

    if not config_path.exists():
        fallback_candidates = [
            Path(settings.resource_dir) / "config" / "config" / "sites.json",
            Path(settings.base_dir) / "config" / "sites.json",
        ]
        for candidate in fallback_candidates:
            if candidate.exists():
                config_path = candidate
                break
        if not config_path.exists():
            return []

    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
        items = data.get("sites") or data.get("data") or []
        sites = []

        for item in items:
            name = item.get("name", "")
            url = item.get("url") or item.get("uri", "")
            if not url:
                continue

            category = _map_category(item.get("category"), name)

            site = Site(
                name=name,
                url=url,
                selector=item.get("selector", ""),
                date_selector=item.get("date_selector", ""),
                date_param=item.get("date_param", ""),
                start_date_param=item.get("start_date_param", ""),
                end_date_param=item.get("end_date_param", ""),
                date_format=item.get("date_format") or "%Y-%m-%d",
                page_size_param=item.get("page_size_param", ""),
                page_size_value=item.get("page_size_value", ""),
                category=category,
                interval_minutes=int(item.get("interval_minutes") or DEFAULT_SITE_INTERVAL_MINUTES),
                is_active=bool(item.get("is_active", True)),
            )
            sites.append(site)

        print(f"[LOAD] Loaded {len(sites)} sites from {config_path.name}")
        return sites

    except Exception as e:
        print(f"[ERROR] sites.json load error: {e}")
        return []


def _site_identity(site: Site) -> tuple[str, str]:
    return ((site.name or "").strip(), (site.category or "").strip())


def _site_name_key(site: Site) -> str:
    return (site.name or "").strip()


def _site_url_key(url: str | None) -> str:
    return (url or "").strip()


def _deactivate_legacy_site_duplicates(repo: SiteRepository) -> int:
    sites = repo.find_all(active_only=False)
    changed = 0
    for identity, replacements in LEGACY_SITE_URL_REPLACEMENTS.items():
        old_urls = set(replacements.keys())
        new_urls = set(replacements.values())
        has_new_site = any(
            _site_identity(site) == identity and _site_url_key(site.url) in new_urls and site.is_active
            for site in sites
        )
        if not has_new_site:
            continue
        for site in sites:
            if _site_identity(site) == identity and _site_url_key(site.url) in old_urls and site.is_active:
                site.is_active = False
                repo.save(site)
                changed += 1
    return changed


def sync_sites_from_config(repo: SiteRepository, config_sites: list[Site]) -> tuple[int, int]:
    """기존 DB에 없는 사이트 추가 및 누락된 날짜 선택자 보완"""
    added = 0
    updated = 0
    existing_sites = repo.find_all(active_only=False)
    by_url = {_site_url_key(site.url): site for site in existing_sites if _site_url_key(site.url)}
    by_identity: dict[tuple[str, str], Site] = {}
    by_name: dict[str, Site] = {}
    for site in existing_sites:
        by_identity.setdefault(_site_identity(site), site)
        by_name.setdefault(_site_name_key(site), site)

    for cfg in config_sites:
        if not cfg.url:
            continue

        cfg_identity = _site_identity(cfg)
        existing = (
            by_url.get(_site_url_key(cfg.url))
            or by_identity.get(cfg_identity)
            or by_name.get(_site_name_key(cfg))
        )
        if not existing:
            repo.save(cfg)
            added += 1
            continue

        changed = False
        legacy_replacements = LEGACY_SITE_URL_REPLACEMENTS.get(cfg_identity, {})
        replacement_url = legacy_replacements.get(_site_url_key(existing.url))
        if replacement_url and replacement_url == _site_url_key(cfg.url):
            existing.url = cfg.url
            changed = True

        if cfg.selector and (
            not existing.selector
            or ("first-child" in existing.selector and "first-child" not in cfg.selector)
        ):
            existing.selector = cfg.selector
            changed = True

        if cfg.date_selector and not existing.date_selector:
            existing.date_selector = cfg.date_selector
            changed = True

        for field in (
            "date_param",
            "start_date_param",
            "end_date_param",
            "date_format",
            "page_size_param",
            "page_size_value",
        ):
            cfg_value = getattr(cfg, field, "")
            if cfg_value and not getattr(existing, field, ""):
                setattr(existing, field, cfg_value)
                changed = True

        if changed:
            repo.save(existing)
            updated += 1

    updated += _deactivate_legacy_site_duplicates(repo)
    return added, updated


def _guess_category(name: str) -> str:
    if "입법예고" in name:
        return Category.LEGISLATION.value
    if "보도" in name or "설명" in name:
        return Category.PRESS_RELEASE.value
    if "의안" in name:
        return Category.BILL.value
    if "행정" in name or "규칙" in name or "훈령" in name or "고시" in name:
        return Category.REGULATION.value
    return Category.OTHER.value


def _map_category(value: str | None, name: str) -> str:
    if value:
        value = str(value).strip()
        if value:
            return value
    return _guess_category(name)


def init_sites():
    """사이트 초기화 (DB에 없으면 TARGET.json에서 로드)"""
    SessionLocal = get_session_factory()
    session = SessionLocal()
    
    try:
        repo = SiteRepository(session)
        existing = repo.find_all(active_only=False)
        config_sites = load_sites_from_config()
        
        if not existing:
            sites = config_sites or migrate_sites_from_target_json()
            for site in sites:
                repo.save(site)
            print(f"[OK] {len(sites)} sites saved to DB")
        else:
            print(f"[INFO] Using existing {len(existing)} sites")
            migrated = migrate_legacy_default_intervals(repo, existing)
            if migrated:
                existing = repo.find_all(active_only=False)
            if config_sites:
                added, updated = sync_sites_from_config(repo, config_sites)
                if added or updated:
                    print(f"[OK] Sites synced: +{added}, updated {updated}")
    finally:
        session.close()


def prune_old_crawl_logs() -> int:
    retention_days = max(1, int(get_settings().crawl_log_retention_days or 30))
    cutoff = datetime.now() - timedelta(days=retention_days)
    SessionLocal = get_session_factory()
    session = SessionLocal()

    try:
        deleted = CrawlLogRepository(session).delete_older_than(cutoff)
    finally:
        session.close()

    if deleted:
        vacuum_sqlite_database()
        print(
            f"[CLEANUP] Deleted {deleted} crawl logs older than "
            f"{retention_days} days"
        )
    return deleted


@asynccontextmanager
async def lifespan(app: FastAPI):
    """애플리케이션 생명주기 관리"""
    # 시작 시
    settings = get_settings()
    
    print("[START] Monitoring system starting...")
    init_database()
    init_sites()
    prune_old_crawl_logs()
    
    # 스케줄러 시작
    scheduler.add_job(
        scheduled_crawl,
        'interval',
        minutes=1,
        id='crawl_job',
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )
    scheduler.start()
    print('[SCHEDULE] Scheduler started: 1 min tick (category round-robin)')
    
    yield
    
    # 종료 시
    scheduler.shutdown()
    print("[STOP] Monitoring system stopped")


# FastAPI 앱 생성
app = FastAPI(
    title="웹사이트 모니터링 시스템",
    description="정부기관 웹사이트의 신규 게시물을 모니터링합니다",
    version="1.0.0",
    lifespan=lifespan,
)


@app.middleware("http")
async def auth_guard(request: Request, call_next):
    path = request.url.path or ""
    if path.startswith("/api") and not path.startswith("/api/auth"):
        if not is_session_ok():
            return JSONResponse(status_code=401, content={"detail": "AUTH_REQUIRED"})
    return await call_next(request)

# 정적 파일
settings = get_settings()
static_path = Path(settings.resource_dir) / "presentation" / "static"
static_path.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_path)), name="static")

# API 라우터
app.include_router(router)


@app.get("/", response_class=HTMLResponse)
async def dashboard():
    """대시보드 페이지"""
    settings = get_settings()
    template_path = Path(settings.resource_dir) / "presentation" / "templates" / "dashboard.html"
    
    if template_path.exists():
        html = template_path.read_text(encoding="utf-8")
        return HTMLResponse(content=html.replace("__APP_VERSION__", resolve_runtime_version(settings)))
    
    return HTMLResponse(content="<h1>Template not found</h1>", status_code=500)


@app.get("/notification-open", response_class=HTMLResponse)
async def notification_open(
    date_key: str | None = None,
    show_unread: bool = True,
    category: str = "",
):
    target = _parse_date_key(date_key)
    resolved_date = (target or date.today()).strftime("%Y-%m-%d")
    push_intent(
        build_dashboard_intent(
            date_key=resolved_date,
            show_unread=show_unread,
            category=category,
        )
    )
    return HTMLResponse(
        content=(
            "<!doctype html><html lang='ko'><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width, initial-scale=1'>"
            "<title>Monitoring Dashboard</title>"
            "<style>body{font-family:'Malgun Gothic',sans-serif;padding:28px;"
            "color:#1b1b1b;background:#f4f5f6}main{max-width:520px;margin:0 auto;"
            "background:#fff;border:1px solid #d9dde1;border-radius:16px;padding:24px;"
            "box-shadow:0 12px 28px rgba(0,0,0,.08)}a{color:#18685c;text-decoration:none;"
            "font-weight:600}</style></head><body><main><h1 style='margin-top:0'>"
            "모니터링 대시보드로 이동했습니다.</h1><p>앱이 실행 중이면 메인 화면이 열리고,"
            " <strong>오늘 + 전체 카테고리 + 보지 않은 기사</strong> 상태로 전환됩니다.</p>"
            "<p>이 창은 닫아도 됩니다. 앱이 보이지 않으면 "
            "<a href='/'>대시보드 열기</a>를 눌러주세요.</p>"
            "<script>setTimeout(function(){try{window.close();}catch(e){}}, 900);</script>"
            "</main></body></html>"
        )
    )


@app.get("/api/notification-intent")
async def get_notification_intent(consume: bool = Query(True)):
    intent = pop_intent() if consume else peek_intent()
    return {
        "ok": True,
        "has_intent": intent is not None,
        "intent": intent,
    }


@app.post("/api/crawl-all")
async def trigger_crawl_all(
    date_key: str | None = None,
    wait: bool = Query(False),
):
    """전체 크롤링 수동 실행"""
    target_date = _parse_date_key(date_key)
    if wait:
        await scheduled_crawl(target_date=target_date)
        return {"message": "크롤링이 완료되었습니다"}
    asyncio.create_task(scheduled_crawl(target_date=target_date))
    return {"message": "크롤링이 시작되었습니다"}


if __name__ == "__main__":
    import uvicorn
    
    settings = get_settings()
    
    print(f"""
==========================================================
          Website Monitoring System
==========================================================
  Server: http://{settings.host}:{settings.port}
  API Docs: http://{settings.host}:{settings.port}/docs
==========================================================
    """)
    
    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
    )
