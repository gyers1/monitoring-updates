"""
웹사이트 크롤러 구현
"""

import asyncio
import re
import hashlib
from datetime import datetime, date, timedelta
from typing import Optional
from urllib.parse import urljoin, urlsplit, urlunsplit, parse_qs, urlencode

import httpx
from bs4 import BeautifulSoup

from config import get_settings
from domain import Site, Article, CrawlResult, CrawlStatus, ICrawler


class WebCrawler(ICrawler):
    """범용 웹 크롤러"""
    
    def __init__(self):
        settings = get_settings()
        self.timeout = settings.request_timeout_seconds
        self.max_retries = settings.max_retries
        self.retry_delay = settings.retry_delay_seconds
        self.max_articles = 120
        self.max_next_pages = 12
        self.debug_trace = bool(getattr(settings, "debug", False))
        
        # 브라우저처럼 보이는 User-Agent
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        }

    def _trace(self, message: str, force: bool = False) -> None:
        if force or self.debug_trace:
            print(f"[CRAWL-TRACE] {message}")
    
    async def crawl(self, site: Site, target_date: date | None = None) -> CrawlResult:
        """??? ??? ?? (??? ?? ??)"""
        last_error = ""
        
        for attempt in range(self.max_retries):
            try:
                async with httpx.AsyncClient(
                    timeout=self.timeout,
                    follow_redirects=True,
                    verify=False  # ?? ?? ??? SSL ??? ?? ??
                ) as client:
                    request_url = self._build_url_for_date(site, target_date)
                    articles = []
                    visited = set()
                    current_url = request_url
                    max_articles = self.max_articles if not target_date else max(self.max_articles, 220)
                    remaining = max_articles
                    max_pages = 1 + self.max_next_pages
                    if target_date:
                        # Past-date lookups often need deeper paging.
                        max_pages = max(max_pages, 30)
                    found_target = False
                    page_no = 0

                    self._trace(
                        f"{site.name} request={request_url} target_date={target_date} max_pages={max_pages} max_articles={max_articles}"
                    )

                    if self._is_bill_state_site(site):
                        page_targets = [request_url]
                        for extra in self._bill_state_page_targets(request_url):
                            if extra not in page_targets:
                                page_targets.append(extra)

                        seen_keys: set[tuple[str, str, str]] = set()
                        for target_url in page_targets:
                            if remaining <= 0:
                                break
                            list_url, params, headers = await self._prepare_bill_state_request(
                                client=client,
                                page_url=target_url,
                                target_date=target_date,
                            )
                            if not list_url or not params:
                                continue

                            for page_no in range(1, max_pages + 1):
                                if remaining <= 0:
                                    break
                                params["page"] = str(page_no)
                                response = await client.post(list_url, data=params, headers=headers)
                                response.raise_for_status()
                                parse_site = site
                                if "finishBillPage.do" in target_url:
                                    parse_site = Site(
                                        id=site.id,
                                        name=site.name,
                                        url=site.url,
                                        selector=site.selector,
                                        date_selector="#state-list tr td.procDt",
                                        date_param=site.date_param,
                                        start_date_param=site.start_date_param,
                                        end_date_param=site.end_date_param,
                                        date_format=site.date_format,
                                        page_size_param=site.page_size_param,
                                        page_size_value=site.page_size_value,
                                        category=site.category,
                                        interval_minutes=site.interval_minutes,
                                        is_active=site.is_active,
                                        last_crawled_at=site.last_crawled_at,
                                    )

                                page_articles = self._parse_articles(
                                    html=response.text,
                                    site=parse_site,
                                    base_url=target_url,
                                    limit=remaining,
                                )
                                self._trace(
                                    f"{site.name} bill-target={target_url} page={page_no} parsed={len(page_articles)}"
                                )
                                if not page_articles:
                                    break

                                added = 0
                                for article in page_articles:
                                    key = (self._normalize_url(article.url), article.title, article.date_key)
                                    if key in seen_keys:
                                        continue
                                    seen_keys.add(key)
                                    articles.append(article)
                                    added += 1
                                    remaining = max_articles - len(articles)
                                    if remaining <= 0:
                                        break
                                if added == 0:
                                    break

                        return CrawlResult(
                            site=site,
                            articles=articles,
                            status=CrawlStatus.SUCCESS,
                        )

                    if self._is_gwanbo_daily_site(site):
                        gwanbo_articles = await self._crawl_gwanbo_daily(
                            client=client,
                            site=site,
                            target_date=target_date,
                        )
                        return CrawlResult(
                            site=site,
                            articles=gwanbo_articles,
                            status=CrawlStatus.SUCCESS,
                        )

                    if self._is_assembly_agenda_site(site):
                        agenda_articles = await self._crawl_assembly_agenda(
                            client=client,
                            site=site,
                            target_date=target_date,
                        )
                        return CrawlResult(
                            site=site,
                            articles=agenda_articles,
                            status=CrawlStatus.SUCCESS,
                        )

                    # Follow next page links up to max_next_pages.
                    for _ in range(max_pages):
                        if remaining <= 0 or not current_url or current_url in visited:
                            break
                        visited.add(current_url)
                        page_no += 1

                        response = await client.get(current_url, headers=self.headers)
                        response.raise_for_status()

                        page_articles = self._parse_articles(
                            html=response.text,
                            site=site,
                            base_url=current_url,
                            limit=remaining
                        )
                        self._trace(f"{site.name} page={page_no} parsed={len(page_articles)} url={current_url}")
                        articles.extend(page_articles)
                        remaining = max_articles - len(articles)
                        if remaining <= 0:
                            break

                        if target_date and page_articles:
                            page_dates = [a.collected_at.date() for a in page_articles if a.collected_at]
                            if page_dates:
                                if any(d == target_date for d in page_dates):
                                    found_target = True
                                min_date = min(page_dates)
                                max_date = max(page_dates)
                                # If we already saw target date and list is now older, stop.
                                if found_target and min_date < target_date:
                                    break
                                # If even newest date is older than target, no need to continue.
                                if max_date < target_date and not found_target:
                                    break

                        next_url = self._find_next_page_url(response.text, current_url)
                        self._trace(f"{site.name} next={next_url or '-'} from={current_url}")
                        if not next_url or next_url == current_url:
                            break
                        current_url = next_url
                    
                    return CrawlResult(
                        site=site,
                        articles=articles,
                        status=CrawlStatus.SUCCESS,
                    )
                    
            except httpx.TimeoutException:
                last_error = f"???? ({self.timeout}? ??)"
            except httpx.HTTPStatusError as e:
                last_error = f"HTTP {e.response.status_code} ??"
            except Exception as e:
                last_error = str(e)
            
            # ??? ? ??
            if attempt < self.max_retries - 1:
                await asyncio.sleep(self.retry_delay)
        
        # ?? ??? ??
        return CrawlResult(
            site=site,
            articles=[],
            status=CrawlStatus.FAILED if "????" not in last_error else CrawlStatus.TIMEOUT,
            error_message=f"{self.max_retries}? ??? ??: {last_error}",
        )

    def _is_bill_state_site(self, site: Site) -> bool:
        url = site.url or ""
        return "likms.assembly.go.kr" in url and "mooringBillPage.do" in url

    def _bill_state_page_targets(self, page_url: str) -> list[str]:
        """Likms bill-state pages to crawl together (pending + processed)."""
        url = page_url or ""
        if "mooringBillPage.do" not in url:
            return []
        parts = urlsplit(url)
        finish_path = "/bill/bi/bill/state/finishBillPage.do"
        finish_query = "mainProcYn=N"
        finish_url = urlunsplit((parts.scheme, parts.netloc, finish_path, finish_query, ""))
        return [finish_url]

    def _is_gwanbo_daily_site(self, site: Site) -> bool:
        url = (site.url or "").lower()
        return "gwanbo.go.kr" in url and "searchdaily" in url

    def _is_assembly_agenda_site(self, site: Site) -> bool:
        url = (site.url or "").lower()
        return "assembly.go.kr" in url and "/portal/na/agenda/agendaschl.do" in url

    async def _crawl_gwanbo_daily(
        self,
        client: httpx.AsyncClient,
        site: Site,
        target_date: date | None,
    ) -> list[Article]:
        base_url = "https://www.gwanbo.go.kr"
        if target_date is None:
            target_date = datetime.now().date()
        date_key = target_date.strftime("%Y%m%d")
        query = f"keyword_field_regdate:[{date_key} TO {date_key}] AND keyword_category_order:(@@ORDER_NUM)"
        data = {
            "mode": "daily",
            "index": "gwanbo",
            "query": query,
            "pQuery_tmp": "",
            "pageNo": "1",
            "listSize": "10000",
            "sort": "",
        }
        headers = dict(self.headers)
        headers["Referer"] = f"{base_url}/user/search/searchDaily.do"
        headers["Origin"] = base_url
        response = await client.post(f"{base_url}/SearchRestApi.jsp", data=data, headers=headers)
        response.raise_for_status()
        try:
            payload = response.json()
        except Exception as e:
            raise RuntimeError("gwanbo daily api returned non-JSON response") from e

        articles: list[Article] = []
        for category in payload.get("data", []):
            rows = category.get("list") or []
            for item in rows:
                raw_date = (
                    item.get("keyword_field_regdate")
                    or f"{item.get('stored_field_year','')}{item.get('stored_field_month','')}{item.get('stored_field_day','')}"
                )
                parsed_date = self._parse_date(raw_date)
                if not parsed_date:
                    continue

                title = item.get("stored_field_subject") or item.get("keyword_field_subject") or ""
                if not title:
                    continue

                url = item.get("stored_field_url") or item.get("stored_pdf_file_path") or ""
                if url:
                    url = urljoin(base_url, url)
                else:
                    url = site.url

                articles.append(
                    Article(
                        site_id=site.id,
                        title=title,
                        url=url,
                        collected_at=parsed_date,
                    )
                )
        return articles

    async def _crawl_assembly_agenda(
        self,
        client: httpx.AsyncClient,
        site: Site,
        target_date: date | None,
    ) -> list[Article]:
        base_url = "https://www.assembly.go.kr"
        page_url = site.url or f"{base_url}/portal/na/agenda/agendaSchl.do?menuNo=600015"
        if target_date is None:
            target_date = datetime.now().date()

        csrf_token = ""
        try:
            page_resp = await client.get(page_url, headers=self.headers)
            page_resp.raise_for_status()
            soup = BeautifulSoup(page_resp.text, "lxml")
            csrf_meta = soup.find("meta", attrs={"name": "_csrf"})
            if csrf_meta:
                csrf_token = (csrf_meta.get("content") or "").strip()
        except Exception as e:
            self._trace(f"assembly page bootstrap failed: {e}", force=True)

        rows = await self._fetch_assembly_agenda_rows(client, base_url, page_url, target_date)
        if not rows:
            self._trace("assembly findAgendaSchl empty; fallback to list.json", force=True)
            rows = await self._fetch_assembly_agenda_list_rows(
                client=client,
                base_url=base_url,
                page_url=page_url,
                target_date=target_date,
                csrf_token=csrf_token,
            )

        articles: list[Article] = []
        used_links: set[str] = set()
        for idx, item in enumerate(rows):
            title = self._clean_text(item.get("title") or item.get("sj") or "")
            if not title:
                continue

            date_text = " ".join(
                [
                    str(item.get("meettingDate") or item.get("meettingDt") or "").strip(),
                    str(item.get("meettingTime") or "").strip(),
                ]
            ).strip()
            parsed_date = self._parse_date(date_text)
            if not parsed_date:
                parsed_date = self._parse_date(str(item.get("meettingDate") or item.get("meettingDt") or ""))
            if not parsed_date:
                continue
            if target_date and parsed_date.date() != target_date:
                continue

            link = self._resolve_assembly_link(item=item, site_url=page_url, base_url=base_url)
            # Some assembly schedules (e.g. seminars/briefings) share the same list URL.
            # Use a deterministic fragment key so records remain unique and DB insert does not fail.
            if link in used_links:
                uniq_seed = (
                    f"{item.get('uniqId') or ''}|{item.get('gubun') or item.get('scheduleDivCd') or ''}|"
                    f"{title}|{parsed_date.strftime('%Y-%m-%d %H:%M')}|{idx}"
                )
                uniq_suffix = hashlib.sha1(uniq_seed.encode("utf-8")).hexdigest()[:10]
                if "#" in link:
                    link = re.sub(r"#.*$", f"#item-{uniq_suffix}", link)
                else:
                    link = f"{link}#item-{uniq_suffix}"
            used_links.add(link)
            articles.append(
                Article(
                    site_id=site.id,
                    title=title,
                    url=link,
                    collected_at=parsed_date,
                )
            )

        self._trace(f"assembly parsed rows={len(rows)} articles={len(articles)} target={target_date}", force=True)
        return articles

    async def _fetch_assembly_agenda_rows(
        self,
        client: httpx.AsyncClient,
        base_url: str,
        page_url: str,
        target_date: date,
    ) -> list[dict]:
        params = {
            "meetYear": f"{target_date.year}",
            "meetMonth": f"{target_date.month:02d}",
            "meetDate": f"{target_date.day:02d}",
        }
        headers = dict(self.headers)
        headers["Referer"] = page_url
        headers["X-Requested-With"] = "XMLHttpRequest"
        try:
            response = await client.get(
                f"{base_url}/portal/na/agenda/findAgendaSchl.json",
                params=params,
                headers=headers,
            )
            response.raise_for_status()
            payload = response.json()
            rows = payload.get("agendaSchl") or []
            if isinstance(rows, list):
                return rows
        except Exception as e:
            self._trace(f"assembly findAgendaSchl failed: {e}", force=True)
        return []

    async def _fetch_assembly_agenda_list_rows(
        self,
        client: httpx.AsyncClient,
        base_url: str,
        page_url: str,
        target_date: date,
        csrf_token: str = "",
    ) -> list[dict]:
        parts = urlsplit(page_url)
        query = parse_qs(parts.query, keep_blank_values=True)
        menu_no = (query.get("menuNo") or ["600015"])[0] or "600015"
        schedule_div_cd = (query.get("scheduleDivCd") or ["ALL"])[0] or "ALL"
        target_str = target_date.strftime("%Y-%m-%d")

        params = {
            "menuNo": menu_no,
            "pageIndex": "1",
            "scheduleDivCd": schedule_div_cd,
            "schlDivId": "",
            "beginDate": target_str,
            "endDate": target_str,
            "searchKey": "all",
            "searchVal": "",
        }
        if csrf_token:
            params["_csrf"] = csrf_token

        headers = dict(self.headers)
        headers["Referer"] = page_url
        headers["X-Requested-With"] = "XMLHttpRequest"
        try:
            response = await client.post(
                f"{base_url}/portal/na/agenda/list.json",
                data=params,
                headers=headers,
            )
            response.raise_for_status()
            payload = response.json()
            rows = payload.get("resultList") or []
            if isinstance(rows, list):
                return rows
        except Exception as e:
            self._trace(f"assembly list.json fallback failed: {e}", force=True)
        return []

    def _resolve_assembly_link(self, item: dict, site_url: str, base_url: str) -> str:
        link = (item.get("linkUrl") or item.get("liveUrl") or "").strip()
        if link:
            return self._normalize_url(urljoin(base_url, link))

        uniq_id = str(item.get("uniqId") or "").strip()
        gubun = str(item.get("gubun") or item.get("scheduleDivCd") or "ALL").strip() or "ALL"
        if uniq_id:
            parts = urlsplit(site_url)
            query = parse_qs(parts.query, keep_blank_values=True)
            menu_no = (query.get("menuNo") or ["600015"])[0] or "600015"
            detail_query = urlencode(
                {
                    "menuNo": menu_no,
                    "scheduleDivCd": gubun,
                    "uniqId": uniq_id,
                },
                doseq=True,
            )
            return self._normalize_url(
                urlunsplit(
                    (
                        parts.scheme or "https",
                        parts.netloc or urlsplit(base_url).netloc,
                        "/portal/na/agenda/agendaSchl.do",
                        detail_query,
                        "",
                    )
                )
            )
        return self._normalize_url(site_url)

    async def _prepare_bill_state_request(
        self,
        client: httpx.AsyncClient,
        page_url: str,
        target_date: date | None,
    ) -> tuple[str, dict, dict]:
        response = await client.get(page_url, headers=self.headers)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "lxml")
        form = soup.find("form", attrs={"id": "form"})
        if not form:
            return "", {}, {}

        params = {}
        for field in form.select("input, select, textarea"):
            name = field.get("name") or field.get("id")
            if not name:
                continue
            tag_name = (field.name or "").lower()
            if tag_name == "select":
                selected = field.find("option", selected=True) or field.find("option")
                params[name] = (selected.get("value") if selected else "") if selected is not None else ""
                continue
            input_type = (field.get("type") or "").lower()
            if input_type == "checkbox":
                # Preserve checked-state semantics expected by server.
                if field.has_attr("checked"):
                    params[name] = field.get("value") or "on"
                continue
            params[name] = field.get("value", "")

        if target_date:
            date_str = target_date.strftime("%Y-%m-%d")
            date_pairs = (
                ("fromPropDt", "toPropDt"),   # 계류의안
                ("procFrom", "procTo"),       # 처리의안
                ("fromDispSe", "toDispSe"),   # 화면별 보조 기간키
                ("fromDate", "toDate"),
                ("beginDate", "endDate"),
            )
            applied = False
            for from_key, to_key in date_pairs:
                if from_key in params or to_key in params:
                    params[from_key] = date_str
                    params[to_key] = date_str
                    applied = True
                    break
            if not applied:
                # Keep backward compatibility for older pages.
                params["fromPropDt"] = date_str
                params["toPropDt"] = date_str

        csrf_meta = soup.find("meta", attrs={"name": "_csrf"})
        csrf_token = csrf_meta.get("content") if csrf_meta else ""

        headers = dict(self.headers)
        headers["Referer"] = page_url
        headers["X-Requested-With"] = "XMLHttpRequest"
        if csrf_token:
            headers["X-CSRF-TOKEN"] = csrf_token

        list_url = urljoin(page_url, "/bill/bi/bill/state/searchBillStatePaging.do")
        return list_url, params, headers

    def _parse_articles(
        self, 
        html: str, 
        site: Site, 
        base_url: str,
        limit: int | None = None,
    ) -> list[Article]:
        """HTML parse"""
        soup = BeautifulSoup(html, "lxml")
        articles = []
        
        # ?? ???? ??? ?? ???? ?? ??
        date_elements = []
        if site.date_selector:
            date_elements = soup.select(site.date_selector)
        
        try:
            # CSS ???? ?? ??
            elements = soup.select(site.selector)
            if limit is not None:
                elements = elements[:limit]
            skipped_no_date = 0
            skipped_no_title = 0
            base_norm = self._normalize_url(base_url)
            
            for idx, elem in enumerate(elements):
                date_text = ""
                parsed_date = None
                if site.date_selector:
                    date_text = self._find_date_text(elem, idx, site, date_elements)
                    parsed_date = self._parse_date(date_text)
                    if not parsed_date:
                        parsed_date = self._parse_date(elem.get_text(" ", strip=True))
                else:
                    parsed_date = self._parse_date(elem.get_text(" ", strip=True))

                if parsed_date:
                    article_date = parsed_date
                else:
                    # 날짜 파싱 실패 시 잘못된 날짜 저장을 피하기 위해 스킵
                    skipped_no_date += 1
                    continue

                title = self._extract_title_text(elem, date_text)
                if not title:
                    skipped_no_title += 1
                    continue

                # ?? ??
                link = self._find_link(elem, base_url)
                if not link or self._normalize_url(link) == base_norm:
                    link = self._build_fallback_article_url(base_url, title, article_date)
                
                article = Article(
                    site_id=site.id,
                    title=title,
                    url=link,
                    collected_at=article_date,
                )
                articles.append(article)

            if skipped_no_date or skipped_no_title:
                self._trace(
                    f"{site.name} parsed={len(articles)} skipped(no_date={skipped_no_date}, no_title={skipped_no_title}) selector={site.selector}",
                    force=True,
                )
                
        except Exception as e:
            print(f"[WARN] Parse error [{site.name}]: {e}")
        
        return articles

    def _find_next_page_url(self, html: str, base_url: str) -> str:
        soup = BeautifulSoup(html, "lxml")

        link = soup.find("link", rel=lambda v: v and "next" in v.lower())
        if link and link.get("href"):
            return urljoin(base_url, link["href"])

        anchor = soup.find("a", rel=lambda v: v and "next" in v.lower())
        if self._is_valid_next_link(anchor):
            return urljoin(base_url, anchor["href"])

        anchor = soup.find("a", class_=re.compile(r"(sib-)?paging-next|next", re.I))
        if self._is_valid_next_link(anchor):
            return urljoin(base_url, anchor["href"])

        for selector in (".pagination", ".paging", ".pager", ".page", ".pageNavi"):
            container = soup.select_one(selector)
            if not container:
                continue
            anchor = container.find("a", string=re.compile(r"(next|>)", re.I))
            if self._is_valid_next_link(anchor):
                return urljoin(base_url, anchor["href"])

        anchor = soup.find("a", attrs={"title": re.compile(r"다음|next", re.I)})
        if self._is_valid_next_link(anchor):
            return urljoin(base_url, anchor["href"])

        anchor = soup.find("a", string=re.compile(r"^(next|>)$", re.I))
        if self._is_valid_next_link(anchor):
            return urljoin(base_url, anchor["href"])

        # JS pagination fallback (goPage(2), pageMove(2), onclick handlers, etc.)
        for a in soup.find_all("a"):
            if not self._is_next_anchor_candidate(a):
                continue
            js_url = self._next_page_from_anchor(a, base_url)
            if js_url and js_url != base_url:
                return js_url

        return self._increment_page_param(base_url)

    def _increment_page_param(self, url: str, page_no: int | None = None) -> str:
        parts = urlsplit(url)
        query = parse_qs(parts.query, keep_blank_values=True)
        page_keys = ("page", "pageIndex", "pageNo", "pageNum", "pageNumber", "currentPage", "curPage")
        if page_no is not None and page_no > 0:
            for key in page_keys:
                if key in query:
                    query[key] = [str(page_no)]
                    new_query = urlencode(query, doseq=True)
                    return urlunsplit((parts.scheme, parts.netloc, parts.path, new_query, parts.fragment))
            query["page"] = [str(page_no)]
            new_query = urlencode(query, doseq=True)
            return urlunsplit((parts.scheme, parts.netloc, parts.path, new_query, parts.fragment))
        for key in page_keys:
            if key in query and query[key]:
                value = query[key][0]
                if value.isdigit():
                    query[key] = [str(int(value) + 1)]
                    new_query = urlencode(query, doseq=True)
                    return urlunsplit((parts.scheme, parts.netloc, parts.path, new_query, parts.fragment))
        return ""

    def _is_next_anchor_candidate(self, anchor) -> bool:
        if not anchor:
            return False
        attrs = " ".join(
            [
                " ".join(anchor.get("class", [])),
                anchor.get("title", "") or "",
                anchor.get("aria-label", "") or "",
                anchor.get_text(" ", strip=True),
            ]
        )
        return bool(re.search("(next|\uB2E4\uC74C|>|\u00BB|\u203A|paging-next|btn_next|pg_next)", attrs, re.I))

    def _next_page_from_anchor(self, anchor, base_url: str) -> str:
        if not anchor:
            return ""
        href = (anchor.get("href") or "").strip()
        if href and not href.startswith("#") and not href.lower().startswith("javascript"):
            return self._normalize_url(urljoin(base_url, href))

        onclick = (anchor.get("onclick") or "").strip()
        js_sources = []
        if href and href.lower().startswith("javascript"):
            js_sources.append(href)
        if onclick:
            js_sources.append(onclick)

        for js in js_sources:
            page_match = re.search(r"(?:\\(|,|\\s)(\\d{1,4})(?:\\)|,|\\s|$)", js)
            if page_match:
                page_no = int(page_match.group(1))
                if page_no > 0:
                    return self._increment_page_param(base_url, page_no=page_no)
        return ""

    def _is_valid_next_link(self, anchor) -> bool:
        if not anchor or not anchor.get("href"):
            return False
        href = anchor.get("href").strip()
        if not href or href.startswith("#") or href.lower().startswith("javascript"):
            return False
        classes = " ".join(anchor.get("class", []))
        if re.search(r"disabled|inactive|off", classes, re.I):
            return False
        if anchor.get("aria-disabled") == "true":
            return False
        return True

    def _extract_article_date(
        self,
        element,
        idx: int,
        site: Site,
        date_elements: list,
    ) -> datetime:
        if not site.date_selector:
            return datetime.now()

        date_text = self._find_date_text(element, idx, site, date_elements)
        if date_text:
            parsed_date = self._parse_date(date_text)
            if parsed_date:
                return parsed_date
        return datetime.now()

    def _extract_title_text(self, element, date_text: str) -> str:
        link = element if element.name == "a" else element.find("a")
        if link:
            parts = []
            for text_node in link.find_all(string=True):
                text = text_node.strip()
                if not text:
                    continue
                parent = text_node.parent
                parent_classes = " ".join(parent.get("class", [])) if parent and parent.get("class") else ""
                if parent and parent.name == "i":
                    continue
                if parent_classes and re.search(r"\bico\b|ico_", parent_classes, re.I):
                    continue
                parts.append(text)
            link_text = self._clean_text(" ".join(parts))
            if link_text:
                return link_text

        raw_text = self._clean_text(element.get_text(" ", strip=True))
        if date_text and date_text in raw_text:
            raw_text = self._clean_text(raw_text.replace(date_text, " "))
        return raw_text

    def _find_date_text(
        self,
        element,
        idx: int,
        site: Site,
        date_elements: list,
    ) -> str:
        row = element.find_parent(["tr", "li"])
        if row:
            relative_selector = self._strip_to_row_selector(site.date_selector, row.name)
            candidates = []
            if relative_selector:
                candidates.append(relative_selector)
            if site.date_selector and site.date_selector not in candidates:
                candidates.append(site.date_selector)

            for sel in candidates:
                date_elem = row.select_one(sel)
                if date_elem:
                    return self._clean_text(date_elem.get_text())

        if date_elements and idx < len(date_elements):
            return self._clean_text(date_elements[idx].get_text())

        return ""

    def _strip_to_row_selector(self, selector: str, row_tag: str) -> str:
        if not selector or not row_tag:
            return selector
        pattern = re.compile(rf"(?:^|\s){row_tag}(?:[^\s>]*)\s*(?:>|\s)\s*")
        matches = list(pattern.finditer(selector))
        if not matches:
            return selector
        return selector[matches[-1].end():].strip()

    def _build_url_for_date(self, site: Site, target_date: date | None) -> str:
        parts = urlsplit(site.url)
        query = parse_qs(parts.query, keep_blank_values=True)
        updated = False

        def set_param(name: str, value: str) -> None:
            nonlocal updated
            if name:
                query[name] = [value]
                updated = True

        if target_date:
            date_format = site.date_format or "%Y-%m-%d"
            try:
                date_str = target_date.strftime(date_format)
            except Exception:
                date_str = target_date.strftime("%Y-%m-%d")

            start_str = date_str
            end_str = date_str

            if site.date_param:
                set_param(site.date_param, date_str)
            if site.start_date_param or site.end_date_param:
                set_param(site.start_date_param, start_str)
                set_param(site.end_date_param, end_str)

            if not updated:
                updated = self._apply_known_date_params(query, start_str, end_str)

        if self._apply_page_size_param(site, query):
            updated = True

        if not updated:
            return site.url

        new_query = urlencode(query, doseq=True)
        return urlunsplit((parts.scheme, parts.netloc, parts.path, new_query, parts.fragment))

    def _apply_known_date_params(self, query: dict, start_str: str, end_str: str) -> bool:
        updated = False
        start_keys = (
            "startDate", "startDt", "start_date", "from", "fromDt", "fromRegDt", "stDt", "sdate", "start"
        )
        end_keys = (
            "endDate", "endDt", "end_date", "to", "toDt", "toRegDt", "edDt", "edate", "end"
        )
        for key in start_keys:
            if key in query:
                query[key] = [start_str]
                updated = True
        for key in end_keys:
            if key in query:
                query[key] = [end_str]
                updated = True
        if not updated:
            single_keys = ("date", "regDt", "searchDate", "schDt", "d")
            for key in single_keys:
                if key in query:
                    query[key] = [start_str]
                    updated = True
        return updated

    def _apply_page_size_param(self, site: Site, query: dict) -> bool:
        param = (site.page_size_param or "").strip()
        value = (site.page_size_value or "").strip()
        if not param or not value:
            return False
        query[param] = [value]
        return True

    def _parse_date(self, date_text: str) -> Optional[datetime]:
        """다양한 날짜 형식 파싱"""
        import re

        raw = date_text or ""
        hour = 0
        minute = 0
        time_match = re.search(r'(\\d{1,2}):(\\d{2})', raw)
        if time_match:
            hour = int(time_match.group(1))
            minute = int(time_match.group(2))
            if re.search(r'(오후|PM|pm)', raw) and hour < 12:
                hour += 12
            if re.search(r'(오전|AM|am)', raw) and hour == 12:
                hour = 0
        
        # 공백과 마지막 점 제거하여 정규화
        normalized = re.sub(r'\s+', '', raw.strip()).rstrip('.')

        if re.search(r'(오늘|금일|당일)', raw):
            today = datetime.now().date()
            return datetime(today.year, today.month, today.day, hour, minute)
        if re.search(r'어제', raw):
            d = datetime.now().date() - timedelta(days=1)
            return datetime(d.year, d.month, d.day, hour, minute)
        
        # 날짜 패턴들 (정규화된 텍스트에 적용)
        patterns = [
            (r'(\d{4})-(\d{1,2})-(\d{1,2})', None),    # 2026-01-22, 2026-1-22
            (r'(\d{4})\.(\d{1,2})\.(\d{1,2})', None),  # 2026.01.22, 2026.1.21
            (r'(\d{4})/(\d{1,2})/(\d{1,2})', None),    # 2026/01/22, 2026/1/22
            (r'(\d{2})-(\d{1,2})-(\d{1,2})', None),    # 26-01-22
            (r'(\d{2})\.(\d{1,2})\.(\d{1,2})', None),  # 26.01.22
            (r'(\d{4})(\d{2})(\d{2})(?!\d)', None),  # 20260122
        ]
        
        for pattern, _ in patterns:
            match = re.search(pattern, normalized)
            if match:
                try:
                    year, month, day = match.groups()
                    year = int(year)
                    month = int(month)
                    day = int(day)
                    
                    # 2자리 연도 처리
                    if year < 100:
                        year += 2000
                    
                    return datetime(year, month, day, hour, minute)
                except:
                    continue
        
        return None
    
    def _find_link(self, element, base_url: str) -> str:
        """요소에서 링크 추출"""
        def bill_detail_link(node) -> str:
            if not node:
                return ""
            candidates = []
            if hasattr(node, "get"):
                candidates.append(node)
            if hasattr(node, "find_parent"):
                parent_a = node.find_parent("a")
                if parent_a:
                    candidates.append(parent_a)
            if hasattr(node, "find"):
                child_a = node.find("a")
                if child_a:
                    candidates.append(child_a)
            for cand in candidates:
                if not hasattr(cand, "get"):
                    continue
                bill_id = cand.get("data-bill-id")
                if bill_id:
                    parts = urlsplit(base_url)
                    query = urlencode({"billId": bill_id})
                    return urlunsplit((parts.scheme, parts.netloc, "/bill/bi/billDetailPage.do", query, ""))
            return ""

        def normalize_href(href: str, element_node=None) -> str:
            if not href:
                return ""
            href = href.strip()
            if href.lower().startswith("javascript:"):
                js_link = self._href_from_javascript(href, base_url)
                if js_link:
                    return self._normalize_url(js_link)
                row_link = row_button_link(element_node)
                if row_link:
                    return self._normalize_url(row_link)
                return ""
            return self._normalize_url(urljoin(base_url, href))

        def href_from_onclick(onclick: str) -> str:
            if not onclick:
                return ""
            match = re.search(r"['\"]((?:https?://|//|/)[^'\"]+)['\"]", onclick)
            if not match:
                return ""
            return self._normalize_url(urljoin(base_url, match.group(1)))

        def row_button_link(element_node) -> str:
            if not element_node:
                return ""
            row = element_node.find_parent(["tr", "li"])
            if not row:
                return ""
            button = row.find("button", onclick=True)
            if not button:
                return ""
            return href_from_onclick(button.get("onclick"))

        bill_link = bill_detail_link(element)
        if bill_link:
            return bill_link

        # 1. 요소 자체가 <a> 태그인 경우
        if element.name == "a":
            href = normalize_href(element.get("href"), element)
            if href:
                return href
        
        # 2. 부모에서 <a> 태그 찾기
        parent_a = element.find_parent("a")
        if parent_a:
            href = normalize_href(parent_a.get("href"), parent_a)
            if href:
                return href
        
        # 3. 자식에서 <a> 태그 찾기
        child_a = element.find("a")
        if child_a:
            href = normalize_href(child_a.get("href"), child_a)
            if href:
                return href
        
        # 4. 인접 형제에서 찾기
        for sibling in element.find_next_siblings("a", limit=4):
            href = normalize_href(sibling.get("href"))
            if href:
                return href

        # 5. onclick에 포함된 링크 찾기 (button 등)
        href = href_from_onclick(element.get("onclick"))
        if href:
            return href

        row = element.find_parent(["tr", "li"])
        if row:
            button = row.find("button", onclick=True)
            if button:
                href = href_from_onclick(button.get("onclick"))
                if href:
                    return href

            for key in ("data-href", "data-url", "data-link"):
                if row.get(key):
                    href = normalize_href(row.get(key))
                    if href:
                        return href
                node = row.find(attrs={key: True})
                if node:
                    href = normalize_href(node.get(key))
                    if href:
                        return href
        
        # 링크를 찾지 못한 경우 사이트 URL 반환
        return self._normalize_url(base_url)

    def _href_from_javascript(self, js: str, base_url: str) -> str:
        if not js:
            return ""
        text = js.strip()
        if text.lower().startswith("javascript:"):
            text = text[len("javascript:"):].strip()

        # 1) javascript 내부에 URL 리터럴이 직접 들어있는 경우
        #    예) location.href='/path/view.do?id=1', window.open('/path')
        direct = re.search(r"(?:location\.href|location\.assign|location\.replace|window\.open)\s*\(\s*['\"]([^'\"]+)['\"]", text, re.I)
        if direct:
            return self._normalize_url(urljoin(base_url, direct.group(1)))
        quoted_url = re.search(r"['\"]((?:https?://|//|/)[^'\"]+)['\"]", text)
        if quoted_url and not text.lower().startswith("fn_egov_select("):
            return self._normalize_url(urljoin(base_url, quoted_url.group(1)))

        match = re.search(r"([a-zA-Z0-9_]+)\((.*)\)", text)
        if not match:
            return ""

        func = match.group(1).lower()
        args = match.group(2)
        arg_values = []
        for item in re.findall(r"'([^']+)'|\"([^\"]+)\"|(\d+)", args):
            val = item[0] or item[1] or item[2]
            if val:
                arg_values.append(val)

        if func in ("fntbbsview", "goview", "fnview", "fnboardview", "goboardview"):
            if func == "goview" and len(arg_values) >= 4:
                bill_no, bill_type_cd, bill_num, prop_type_cd = arg_values[:4]
                parts = urlsplit(base_url)
                query = parse_qs(parts.query, keep_blank_values=True)
                query["billNo"] = [bill_no]
                query["billTypeCd"] = [bill_type_cd]
                query["billNum"] = [bill_num]
                query["propTypeCd"] = [prop_type_cd]
                if "url" not in query:
                    query["url"] = ["/bpsList01.do"]
                new_query = urlencode(query, doseq=True)
                return self._normalize_url(
                    urlunsplit((parts.scheme, parts.netloc, "/info/bpsBillRead.do", new_query, parts.fragment))
                )

            if not arg_values:
                return ""
            arg_value = arg_values[0]
            parts = urlsplit(base_url)
            query = parse_qs(parts.query, keep_blank_values=True)
            query["nttNo"] = [arg_value]
            new_query = urlencode(query, doseq=True)
            return self._normalize_url(
                urlunsplit((parts.scheme, parts.netloc, parts.path, new_query, parts.fragment))
            )

        # Example:
        # javascript:fn_egov_select('MOSF_000000000076690');
        # Build a direct detail URL so dashboard opens the article page, not the list page.
        if func in ("fn_egov_select", "fnegovselect", "egov_select"):
            if not arg_values:
                return ""

            ntt_id = arg_values[0]
            parts = urlsplit(base_url)
            query = parse_qs(parts.query, keep_blank_values=True)

            bbs_id = ""
            for key in ("bbsId", "searchBbsId", "searchBbsId1", "searchBbsId2"):
                if key in query and query[key]:
                    bbs_id = query[key][0]
                    break

            menu_no = ""
            for key in ("menuNo", "searchMenu"):
                if key in query and query[key]:
                    menu_no = query[key][0]
                    break

            detail_query = {"searchNttId1": ntt_id}
            if bbs_id:
                detail_query["searchBbsId1"] = bbs_id
            if menu_no:
                detail_query["menuNo"] = menu_no

            detail_path = "/nw/nes/detailNesDtaView.do"
            if "/nw/nes/" not in parts.path:
                # Fallback for non-MOEF pages using similar JS function name.
                detail_path = parts.path

            new_query = urlencode(detail_query, doseq=True)
            return self._normalize_url(
                urlunsplit((parts.scheme, parts.netloc, detail_path, new_query, parts.fragment))
            )

        return ""

    def _normalize_url(self, url: str) -> str:
        if not url:
            return url
        parts = urlsplit(url)
        path = re.sub(r";jsessionid=[^/?#]+", "", parts.path, flags=re.I)
        return urlunsplit((parts.scheme, parts.netloc, path, parts.query, parts.fragment))

    def _build_fallback_article_url(self, base_url: str, title: str, article_date: datetime) -> str:
        key = f"{title}|{article_date.strftime('%Y-%m-%d')}"
        token = hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]
        normalized = self._normalize_url(base_url)
        parts = urlsplit(normalized)
        return urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, f"item-{token}"))
    
    def _clean_text(self, text: str) -> str:
        """텍스트 정제"""
        if not text:
            return ""
        # 공백 정규화
        text = re.sub(r'\s+', ' ', text.strip())
        # 150자 제한
        if len(text) > 150:
            text = text[:147] + "..."
        return text


# 의안정보시스템 전용 크롤러 (키워드 필터링)
class BillCrawler(WebCrawler):
    """의안정보시스템 전용 크롤러"""
    
    def __init__(self):
        super().__init__()
        settings = get_settings()
        self.keywords = settings.bill_keywords
    
    async def crawl(self, site: Site, target_date: date | None = None) -> CrawlResult:
        """크롤링 후 키워드 필터링"""
        result = await super().crawl(site, target_date=target_date)
        
        if result.status == CrawlStatus.SUCCESS:
            # 키워드 매칭되는 게시글만 필터링
            filtered = [
                a for a in result.articles 
                if a.matches_keywords(self.keywords)
            ]
            result.articles = filtered
        
        return result
