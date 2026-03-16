"""
FastAPI 라우터 및 API 엔드포인트
"""

from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import zipfile
import hashlib
from pathlib import Path
import httpx
from bs4 import BeautifulSoup
from urllib.parse import urlparse, urljoin
import re
import json

from config import get_settings
from config.versioning import resolve_runtime_version
from infrastructure.database import get_db, ArticleRepository, SiteRepository, CrawlLogRepository
from infrastructure.crawlers import WebCrawler
from infrastructure.notifiers import get_notifier
from application import CrawlService
from domain import CrawlStatus, Article
from infrastructure.auth import get_auth_snapshot, verify_auth
from infrastructure.ui_prefs import load_ui_prefs, save_ui_prefs


# Pydantic 스키마
class ArticleResponse(BaseModel):
    id: int
    site_name: str
    category: str
    title: str
    url: str
    collected_at: datetime
    
    class Config:
        from_attributes = True


class SiteResponse(BaseModel):
    id: int
    name: str
    url: str
    category: str
    interval_minutes: int
    is_active: bool
    last_crawled_at: Optional[datetime]
    
    class Config:
        from_attributes = True


class StatsResponse(BaseModel):
    total: int
    by_category: dict
    date_key: str


class CrawlLogResponse(BaseModel):
    id: int
    site_id: int
    site_name: str
    status: str
    message: str
    articles_count: int
    crawled_at: datetime
    
    class Config:
        from_attributes = True


class CrawlResultResponse(BaseModel):
    site_name: str
    status: str
    new_articles_count: int
    message: str


class UpdateResponse(BaseModel):
    ok: bool
    message: str


class VersionResponse(BaseModel):
    version: str


class UiPrefsResponse(BaseModel):
    category_order: list[str]
    site_priority: dict[str, int]


class UiPrefsUpdateRequest(BaseModel):
    category_order: Optional[list[str]] = None
    site_priority: Optional[dict[str, int]] = None


class SelectorTestRequest(BaseModel):
    url: str
    selector: str
    date_selector: Optional[str] = None


class SelectorTestResponse(BaseModel):
    ok: bool
    title_count: int
    date_count: int
    sample_titles: list[str]
    sample_dates: list[str]
    range_info: Optional[str] = None


def _sanitize_remote_html(html: str) -> tuple[str, str]:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup.find_all(["noscript", "iframe"]):
        tag.decompose()
    for tag in soup.find_all("meta", attrs={"http-equiv": re.compile("content-security-policy", re.I)}):
        tag.decompose()
    for tag in soup.find_all("meta", attrs={"http-equiv": re.compile("refresh", re.I)}):
        tag.decompose()
    for tag in soup.find_all("base"):
        tag.decompose()
    for tag in soup.find_all(True):
        for attr in list(tag.attrs):
            if attr.lower().startswith("on"):
                del tag.attrs[attr]

    head_links = ""
    if soup.head:
        head_tags = soup.head.find_all(["link", "style", "script"])
        head_links = "".join(str(t) for t in head_tags)

    body = soup.body if soup.body else soup
    body_html = body.decode_contents() if hasattr(body, "decode_contents") else str(body)
    return head_links, body_html


def _build_selector_helper_page(target_url: str, raw_html: str) -> str:
    settings = get_settings()
    template_path = Path(settings.resource_dir) / "presentation" / "templates" / "selector_helper.html"
    if not template_path.exists():
        return "<h1>selector_helper.html not found</h1>"

    head_links, body_html = _sanitize_remote_html(raw_html)
    base_href = urljoin(target_url, ".")
    template = template_path.read_text(encoding="utf-8")
    template = template.replace("__BASE_HREF__", base_href)
    template = template.replace("__HEAD_LINKS__", head_links or "")
    template = template.replace("__REMOTE_BODY__", body_html or "<p>내용을 불러올 수 없습니다.</p>")
    return template


def _extract_text_samples(elements: list, limit: int = 5) -> list[str]:
    samples: list[str] = []
    for el in elements:
        text = " ".join(el.stripped_strings) if hasattr(el, "stripped_strings") else str(el)
        text = re.sub(r"\s+", " ", text).strip()
        if not text:
            continue
        samples.append(text[:160])
        if len(samples) >= limit:
            break
    return samples


def _normalize_selector(selector: str) -> str:
    """사용자가 복사한 선택자를 리스트 수집용으로 완만하게 정규화."""
    text = (selector or "").strip()
    if not text:
        return ""
    # 첫 번째 행 클릭으로 생기는 과도한 인덱스 선택자는 제거한다.
    text = re.sub(r":nth-child\(\d+\)", "", text, flags=re.I)
    text = re.sub(r":nth-of-type\(\d+\)", "", text, flags=re.I)
    text = re.sub(r"\[(?:data-)?index=['\"]?\d+['\"]?\]", "", text, flags=re.I)
    text = re.sub(r"\s*>\s*", " > ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _safe_rel_path(path: Path) -> Optional[Path]:
    if path.is_absolute() or ".." in path.parts:
        return None
    if not path.parts:
        return None
    return path


def _detect_common_root(members: list[zipfile.ZipInfo]) -> Optional[str]:
    roots: list[str] = []
    for member in members:
        rel = Path(member.filename)
        if rel.is_absolute() or not rel.parts:
            return None
        roots.append(rel.parts[0])
    if not roots:
        return None
    return roots[0] if len(set(roots)) == 1 else None


def _extract_update(zip_path: Path, extract_dir: Optional[Path] = None) -> Path:
    if extract_dir is None:
        temp_dir = Path(tempfile.mkdtemp())
        extract_dir = temp_dir / "payload"
    else:
        extract_dir = Path(extract_dir)
        if extract_dir.exists():
            shutil.rmtree(extract_dir, ignore_errors=True)
    extract_dir.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(zip_path, "r") as zf:
        members = [m for m in zf.infolist() if not m.is_dir()]
        common_root = _detect_common_root(members)
        for member in members:
            rel_path = Path(member.filename)
            if common_root and rel_path.parts and rel_path.parts[0] == common_root:
                rel_path = Path(*rel_path.parts[1:])
            rel_path = _safe_rel_path(rel_path)
            if not rel_path:
                continue
            if rel_path.name in {"monitoring.db", ".env", "auth_cache.json", "ui_prefs.json"}:
                continue
            rel_str = str(rel_path).replace("\\", "/")
            if rel_str.startswith("doc/backups"):
                continue
            if rel_str.startswith("venv/") or rel_str.startswith("__pycache__/"):
                continue

            target_path = extract_dir / rel_path
            target_path.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(member, "r") as src, open(target_path, "wb") as dst:
                shutil.copyfileobj(src, dst)

    return extract_dir


def _extract_release_tag_from_url(url: str) -> Optional[str]:
    if not url:
        return None
    patterns = [
        r"/releases/download/([^/]+)/",
        r"/releases/tag/([^/?#]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


def _extract_release_tag_from_response(resp: httpx.Response, requested_url: str) -> Optional[str]:
    candidates: list[str] = [requested_url, str(resp.url)]
    for history_resp in resp.history:
        candidates.append(str(history_resp.url))
        location = history_resp.headers.get("location")
        if location:
            candidates.append(location)

    for candidate in candidates:
        tag = _extract_release_tag_from_url(candidate)
        if tag:
            return tag
    return None


def _extract_release_tag_from_payload(payload_dir: Path) -> Optional[str]:
    version_path = payload_dir / "version.json"
    if not version_path.exists():
        return None
    try:
        data = json.loads(version_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    value = (data.get("version") if isinstance(data, dict) else None) or ""
    value = str(value).strip()
    return value or None


def _ps_single_quoted(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _write_update_script(base_dir: Path, payload_dir: Path, stage_dir: Path, exe_name: str, pid: int) -> Path:
    script_path = base_dir / "apply_update.ps1"
    ps_values = {
        "pid": str(pid),
        "dst": _ps_single_quoted(str(base_dir.resolve())),
        "src": _ps_single_quoted(str(payload_dir.resolve())),
        "stage": _ps_single_quoted(str(stage_dir.resolve())),
        "tag_file": _ps_single_quoted(str((stage_dir / "update_tag.txt").resolve())),
        "log": _ps_single_quoted(str((base_dir / "update_restart.log").resolve())),
        "exe_path": _ps_single_quoted(str((base_dir / exe_name).resolve())),
        "source_launcher": _ps_single_quoted(str((base_dir / "tray_start.bat").resolve())),
    }
    script = f"""$ErrorActionPreference = 'Stop'
$pidToWait = {ps_values["pid"]}
$dst = {ps_values["dst"]}
$src = {ps_values["src"]}
$stage = {ps_values["stage"]}
$tagFile = {ps_values["tag_file"]}
$logPath = {ps_values["log"]}
$exePath = {ps_values["exe_path"]}
$sourceLauncher = {ps_values["source_launcher"]}
$verifyRel = 'version.json'

function Write-Log([string]$Message) {{
    Add-Content -LiteralPath $logPath -Value $Message -Encoding UTF8
}}

function Copy-DirectoryTree([string]$From, [string]$To) {{
    Get-ChildItem -LiteralPath $From -Recurse -Force | ForEach-Object {{
        $rel = $_.FullName.Substring($From.Length).TrimStart('\\')
        if ([string]::IsNullOrWhiteSpace($rel)) {{
            return
        }}
        $target = Join-Path $To $rel
        if ($_.PSIsContainer) {{
            if (-not (Test-Path -LiteralPath $target)) {{
                New-Item -ItemType Directory -Path $target -Force | Out-Null
            }}
            return
        }}
        $targetDir = Split-Path -Parent $target
        if ($targetDir -and -not (Test-Path -LiteralPath $targetDir)) {{
            New-Item -ItemType Directory -Path $targetDir -Force | Out-Null
        }}
        Copy-Item -LiteralPath $_.FullName -Destination $target -Force
    }}
}}

function Preserve-UserFiles([string]$Root, [string]$PreserveRoot, [string[]]$Names) {{
    if (-not (Test-Path -LiteralPath $PreserveRoot)) {{
        New-Item -ItemType Directory -Path $PreserveRoot -Force | Out-Null
    }}
    foreach ($name in $Names) {{
        $sourcePath = Join-Path $Root $name
        if (-not (Test-Path -LiteralPath $sourcePath)) {{
            continue
        }}
        $targetPath = Join-Path $PreserveRoot $name
        $targetDir = Split-Path -Parent $targetPath
        if ($targetDir -and -not (Test-Path -LiteralPath $targetDir)) {{
            New-Item -ItemType Directory -Path $targetDir -Force | Out-Null
        }}
        Copy-Item -LiteralPath $sourcePath -Destination $targetPath -Recurse -Force
    }}
}}

function Clear-InstallDirectory([string]$Root, [string[]]$ExcludeNames) {{
    Get-ChildItem -LiteralPath $Root -Force | ForEach-Object {{
        if ($ExcludeNames -contains $_.Name) {{
            return
        }}
        Remove-Item -LiteralPath $_.FullName -Recurse -Force -ErrorAction Stop
    }}
}}

try {{
    Write-Log '============================================================'
    Write-Log ('[UPDATE] ' + (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'))
    Write-Log ('PID=' + $pidToWait + ' SRC=' + $src + ' DST=' + $dst)

    for ($i = 0; $i -lt 180; $i++) {{
        if (-not (Get-Process -Id $pidToWait -ErrorAction SilentlyContinue)) {{
            break
        }}
        Start-Sleep -Seconds 1
    }}

    $processName = [System.IO.Path]::GetFileNameWithoutExtension($exePath)
    if ($processName) {{
        Get-Process -Name $processName -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    }}

    if (-not (Test-Path -LiteralPath $src)) {{
        throw 'source payload dir not found'
    }}

    $preserveNames = @('monitoring.db', '.env', 'auth_cache.json', 'ui_prefs.json')
    $preserveDir = Join-Path $stage 'preserve'
    Write-Log '[STEP] preserve user data'
    Preserve-UserFiles -Root $dst -PreserveRoot $preserveDir -Names $preserveNames

    Write-Log '[STEP] clean install dir'
    Clear-InstallDirectory -Root $dst -ExcludeNames @(
        [System.IO.Path]::GetFileName($stage),
        [System.IO.Path]::GetFileName($PSCommandPath),
        [System.IO.Path]::GetFileName($logPath)
    )

    Write-Log '[STEP] copy payload'
    Copy-DirectoryTree -From $src -To $dst

    if (Test-Path -LiteralPath $preserveDir) {{
        Write-Log '[STEP] restore user data'
        Copy-DirectoryTree -From $preserveDir -To $dst
    }}

    $srcVerify = Join-Path $src $verifyRel
    $dstVerify = Join-Path $dst $verifyRel
    if (Test-Path -LiteralPath $srcVerify) {{
        if (-not (Test-Path -LiteralPath $dstVerify)) {{
            throw 'version.json missing after copy'
        }}
        $srcHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $srcVerify).Hash
        $dstHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $dstVerify).Hash
        if ($srcHash -ne $dstHash) {{
            Copy-Item -LiteralPath $srcVerify -Destination $dstVerify -Force
            $dstHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $dstVerify).Hash
            if ($srcHash -ne $dstHash) {{
                throw 'critical file verify failed'
            }}
        }}
    }}

    if (Test-Path -LiteralPath $tagFile) {{
        $ver = (Get-Content -LiteralPath $tagFile -Raw).Trim()
        if ($ver) {{
            Write-Log ('[STEP] set version=' + $ver)
            $versionJson = @{{ version = $ver }} | ConvertTo-Json -Compress
            [System.IO.File]::WriteAllText((Join-Path $dst 'version.json'), $versionJson, [System.Text.UTF8Encoding]::new($false))

            $envPath = Join-Path $dst '.env'
            if (Test-Path -LiteralPath $envPath) {{
                $content = [System.IO.File]::ReadAllText($envPath, [System.Text.Encoding]::UTF8)
                $content = [regex]::Replace($content, '(?m)^APP_VERSION=.*$', ('APP_VERSION=' + $ver))
                if ($content -notmatch '(?m)^APP_VERSION=') {{
                    $content = $content.TrimEnd() + [Environment]::NewLine + ('APP_VERSION=' + $ver) + [Environment]::NewLine
                }}
                [System.IO.File]::WriteAllText($envPath, $content, [System.Text.UTF8Encoding]::new($false))
            }}
        }}
    }}

    if (Test-Path -LiteralPath $exePath) {{
        Write-Log '[STEP] launch gui exe directly'
        Start-Process -FilePath $exePath -WorkingDirectory $dst | Out-Null
        Write-Log '[OK] restart success'
    }}
    elseif (Test-Path -LiteralPath $sourceLauncher) {{
        Write-Log '[STEP] source-mode launch via hidden cmd'
        Start-Process -WindowStyle Hidden -FilePath 'cmd.exe' -ArgumentList '/d','/s','/c',$sourceLauncher -WorkingDirectory $dst | Out-Null
        Write-Log '[OK] restart success'
    }}
    else {{
        Write-Log '[ERROR] restart failed'
    }}
}}
catch {{
    Write-Log ('[ERROR] ' + $_.Exception.Message)
}}
finally {{
    Remove-Item -LiteralPath $stage -Recurse -Force -ErrorAction SilentlyContinue
    Write-Log ('[DONE] ' + (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'))
}}
"""
    script_path.write_text(script, encoding="utf-8-sig")
    return script_path


def _schedule_exit(delay: float = 1.0) -> None:
    def _exit() -> None:
        time.sleep(delay)
        os._exit(0)

    threading.Thread(target=_exit, daemon=True).start()


def _launch_update_script(base_dir: Path, log_path: Path) -> str:
    """
    Launch the hidden PowerShell updater once.
    """
    creation_flags = 0
    for attr in ("CREATE_NEW_PROCESS_GROUP", "DETACHED_PROCESS", "CREATE_NO_WINDOW"):
        creation_flags |= int(getattr(subprocess, attr, 0))

    launch_plan = [(
        "powershell -File apply_update.ps1",
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            "apply_update.ps1",
        ],
    )]

    last_error = None
    for launch_name, args in launch_plan:
        try:
            subprocess.Popen(
                args,
                cwd=base_dir,
                creationflags=creation_flags,
            )
            return launch_name
        except Exception as e:
            last_error = e
            try:
                with open(log_path, "a", encoding="utf-8") as f:
                    f.write(f"launch_error={launch_name}: {e}\r\n")
            except Exception:
                pass

    raise RuntimeError(f"failed to launch updater: {last_error}")


class AuthVerifyRequest(BaseModel):
    name: Optional[str] = None


# 라우터
router = APIRouter(prefix="/api", tags=["API"])


@router.get("/auth/status")
def auth_status():
    """Return cached auth info for the current device."""
    return get_auth_snapshot()


@router.post("/auth/verify")
async def auth_verify(req: AuthVerifyRequest):
    """Verify access against Google Apps Script."""
    return await verify_auth(req.name)


@router.get("/selector-helper", response_class=HTMLResponse)
async def selector_helper(url: str = Query(..., description="Target page url")):
    """Selector helper preview page for picking CSS selectors."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise HTTPException(status_code=400, detail="Invalid url")

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"
    }

    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=True, headers=headers) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            html = resp.text
    except Exception as e:
        message = f"<h2>페이지를 불러올 수 없습니다</h2><p>{e}</p>"
        return HTMLResponse(content=_build_selector_helper_page(url, message), status_code=200)

    content = _build_selector_helper_page(url, html)
    return HTMLResponse(content=content, status_code=200)


@router.post("/selector-test", response_model=SelectorTestResponse)
async def selector_test(req: SelectorTestRequest):
    parsed = urlparse(req.url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise HTTPException(status_code=400, detail="Invalid url")
    if not req.selector:
        raise HTTPException(status_code=400, detail="selector required")

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"
    }
    async with httpx.AsyncClient(timeout=20, follow_redirects=True, headers=headers) as client:
        resp = await client.get(req.url)
        resp.raise_for_status()
        html = resp.text

    soup = BeautifulSoup(html, "lxml")
    title_elements = soup.select(req.selector)
    date_elements = soup.select(req.date_selector) if req.date_selector else []
    sample_titles = _extract_text_samples(title_elements)
    sample_dates = _extract_text_samples(date_elements)

    range_info = None
    if sample_dates:
        m = re.findall(r"(\\d{4}-\\d{2}-\\d{2})", sample_dates[0])
        if len(m) >= 2:
            range_info = f"{m[0]} ~ {m[1]} (시작일 기준)"

    return SelectorTestResponse(
        ok=True,
        title_count=len(title_elements),
        date_count=len(date_elements),
        sample_titles=sample_titles,
        sample_dates=sample_dates,
        range_info=range_info,
    )

def _parse_date_key(date_key: Optional[str]) -> date | None:
    if not date_key:
        return None
    try:
        return datetime.strptime(date_key, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="date_key must be YYYY-MM-DD")


@router.get("/articles", response_model=list[ArticleResponse])
def get_articles(
    date_key: Optional[str] = Query(None, description="날짜 (YYYY-MM-DD)"),
    category: Optional[str] = Query(None, description="카테고리"),
    db: Session = Depends(get_db)
):
    """게시글 목록 조회"""
    repo = ArticleRepository(db)
    
    if not date_key:
        date_key = date.today().strftime("%Y-%m-%d")
    
    articles = repo.find_by_date(date_key)
    
    if category:
        articles = [a for a in articles if a.category == category]
    
    return [
        ArticleResponse(
            id=a.id,
            site_name=a.site_name,
            category=a.category,
            title=a.title,
            url=a.url,
            collected_at=a.collected_at,
        )
        for a in articles
    ]


@router.get("/sites", response_model=list[SiteResponse])
def get_sites(
    active_only: bool = Query(True),
    db: Session = Depends(get_db)
):
    """사이트 목록 조회"""
    repo = SiteRepository(db)
    sites = repo.find_all(active_only=active_only)
    
    return [
        SiteResponse(
            id=s.id,
            name=s.name,
            url=s.url,
            category=s.category,
            interval_minutes=s.interval_minutes,
            is_active=s.is_active,
            last_crawled_at=s.last_crawled_at,
        )
        for s in sites
    ]


@router.post("/update", response_model=UpdateResponse)
async def update_app():
    """원격 업데이트 zip을 내려받아 적용"""
    settings = get_settings()
    if not settings.update_url:
        raise HTTPException(status_code=400, detail="UPDATE_URL not configured")

    base_dir = Path(settings.base_dir)
    stage_dir = base_dir / "_update_stage"
    if stage_dir.exists():
        shutil.rmtree(stage_dir, ignore_errors=True)
    stage_dir.mkdir(parents=True, exist_ok=True)
    zip_path = stage_dir / "update.zip"
    launched = False
    release_tag: Optional[str] = None
    log_path = base_dir / "update_restart.log"

    try:
        req_url = settings.update_url.strip()
        sep = "&" if "?" in req_url else "?"
        req_url = f"{req_url}{sep}_ts={int(time.time())}"
        async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
            resp = await client.get(
                req_url,
                headers={"Cache-Control": "no-cache", "Pragma": "no-cache"},
            )
            resp.raise_for_status()
            zip_path.write_bytes(resp.content)
        payload_sha256 = hashlib.sha256(resp.content).hexdigest()
        payload_dir = _extract_update(zip_path, stage_dir / "payload")
        release_tag = _extract_release_tag_from_payload(payload_dir)
        if not release_tag:
            release_tag = _extract_release_tag_from_response(resp, req_url)
        if release_tag:
            (stage_dir / "update_tag.txt").write_text(release_tag, encoding="ascii")
        exe_name = Path(sys.executable).name if getattr(sys, "frozen", False) else "MonitoringDashboard.exe"
        script_path = _write_update_script(base_dir, payload_dir, stage_dir, exe_name, os.getpid())
        try:
            log_path.write_text(
                f"[UPDATE_TRIGGER] {time.strftime('%Y-%m-%d %H:%M:%S')}\r\n"
                f"request_url={req_url}\r\n"
                f"resolved_url={resp.url}\r\n"
                f"download_sha256={payload_sha256}\r\n"
                f"script={script_path}\r\n",
                encoding="utf-8",
            )
        except Exception:
            pass
        launched_by = _launch_update_script(base_dir, log_path)
        try:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(f"launch={launched_by}\r\n")
        except Exception:
            pass
        launched = True
        _schedule_exit()
        return UpdateResponse(ok=True, message="업데이트 적용을 시작했습니다. 잠시 후 자동 재시작됩니다.")
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"Update download failed: {e}")
    except zipfile.BadZipFile:
        raise HTTPException(status_code=400, detail="Invalid update file")
    finally:
        if not launched:
            shutil.rmtree(stage_dir, ignore_errors=True)


@router.get("/version", response_model=VersionResponse)
def get_app_version():
    return VersionResponse(version=resolve_runtime_version())


@router.get("/ui-prefs", response_model=UiPrefsResponse)
def get_ui_prefs():
    settings = get_settings()
    prefs = load_ui_prefs(settings.base_dir)
    return UiPrefsResponse(**prefs)


@router.put("/ui-prefs", response_model=UiPrefsResponse)
def update_ui_prefs(req: UiPrefsUpdateRequest):
    settings = get_settings()
    prefs = save_ui_prefs(
        settings.base_dir,
        category_order=req.category_order,
        site_priority=req.site_priority,
    )
    return UiPrefsResponse(**prefs)


@router.post("/sites/{site_id}/crawl", response_model=CrawlResultResponse)
async def crawl_site(site_id: int, date_key: Optional[str] = Query(None), db: Session = Depends(get_db)):
    """특정 사이트 즉시 크롤링"""
    article_repo = ArticleRepository(db)
    site_repo = SiteRepository(db)
    log_repo = CrawlLogRepository(db)
    crawler = WebCrawler()
    notifier = get_notifier()
    
    target_date = _parse_date_key(date_key)

    service = CrawlService(
        article_repo=article_repo,
        site_repo=site_repo,
        log_repo=log_repo,
        crawler=crawler,
        notifier=notifier,
    )
    
    result = await service.crawl_site_by_id(site_id, target_date=target_date)
    
    return CrawlResultResponse(
        site_name=result.site.name,
        status=result.status.value,
        new_articles_count=result.new_articles_count,
        message=result.error_message or "완료",
    )


@router.post("/notify-test", response_model=UpdateResponse)
async def notify_test():
    """윈도우 알림 테스트"""
    settings = get_settings()
    notifier = get_notifier()
    base_url = f"http://{settings.host}:{settings.port}/"
    sample = Article(
        title="알림 테스트",
        url=base_url,
        site_name="모니터링 알림",
    )
    ok = await notifier.notify([sample], subject="알림 테스트")
    message = getattr(notifier, "last_status_message", "") or (
        "윈도우 알림 요청을 보냈습니다." if ok else "윈도우 알림 요청에 실패했습니다."
    )
    if not ok:
        raise HTTPException(status_code=500, detail=message)
    return UpdateResponse(ok=True, message=message)


@router.get("/stats", response_model=StatsResponse)
def get_stats(
    date_key: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    """통계 조회"""
    repo = ArticleRepository(db)
    
    if not date_key:
        date_key = date.today().strftime("%Y-%m-%d")
    
    return repo.get_stats(date_key)


@router.get("/logs", response_model=list[CrawlLogResponse])
def get_logs(
    limit: int = Query(50, le=200),
    db: Session = Depends(get_db)
):
    """크롤링 로그 조회"""
    repo = CrawlLogRepository(db)
    logs = repo.find_recent(limit=limit)
    
    return [
        CrawlLogResponse(
            id=log.id,
            site_id=log.site_id,
            site_name=log.site_name,
            status=log.status.value,
            message=log.message,
            articles_count=log.articles_count,
            crawled_at=log.crawled_at,
        )
        for log in logs
    ]


# ==================== 사이트 CRUD ====================

class SiteCreateRequest(BaseModel):
    name: str
    url: str
    selector: str
    date_selector: str = ""
    keep_raw_selectors: bool = False
    date_param: str = ""
    start_date_param: str = ""
    end_date_param: str = ""
    date_format: str = "%Y-%m-%d"
    page_size_param: str = ""
    page_size_value: str = ""
    category: str = "기타"
    interval_minutes: int = 20


class SiteUpdateRequest(BaseModel):
    name: Optional[str] = None
    url: Optional[str] = None
    selector: Optional[str] = None
    date_selector: Optional[str] = None
    keep_raw_selectors: Optional[bool] = None
    date_param: Optional[str] = None
    start_date_param: Optional[str] = None
    end_date_param: Optional[str] = None
    date_format: Optional[str] = None
    page_size_param: Optional[str] = None
    page_size_value: Optional[str] = None
    category: Optional[str] = None
    interval_minutes: Optional[int] = None
    is_active: Optional[bool] = None


class SiteDetailResponse(BaseModel):
    id: int
    name: str
    url: str
    selector: str
    date_selector: str
    date_param: str
    start_date_param: str
    end_date_param: str
    date_format: str
    page_size_param: str
    page_size_value: str
    category: str
    interval_minutes: int
    is_active: bool
    last_crawled_at: Optional[datetime]
    
    class Config:
        from_attributes = True


@router.get("/sites/{site_id}", response_model=SiteDetailResponse)
def get_site(site_id: int, db: Session = Depends(get_db)):
    """사이트 상세 조회"""
    repo = SiteRepository(db)
    site = repo.find_by_id(site_id)
    
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")
    
    return SiteDetailResponse(
        id=site.id,
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
        category=site.category,
        interval_minutes=site.interval_minutes,
        is_active=site.is_active,
        last_crawled_at=site.last_crawled_at,
    )


@router.post("/sites", response_model=SiteDetailResponse)
def create_site(req: SiteCreateRequest, db: Session = Depends(get_db)):
    """사이트 생성"""
    from domain import Site

    category = (req.category or "기타").strip() or "기타"

    selector_value = req.selector if req.keep_raw_selectors else _normalize_selector(req.selector)
    date_selector_value = req.date_selector if req.keep_raw_selectors else _normalize_selector(req.date_selector)

    site = Site(
        name=req.name,
        url=req.url,
        selector=selector_value,
        date_selector=date_selector_value,
        date_param=req.date_param,
        start_date_param=req.start_date_param,
        end_date_param=req.end_date_param,
        date_format=req.date_format,
        page_size_param=req.page_size_param,
        page_size_value=req.page_size_value,
        category=category,
        interval_minutes=max(1, int(req.interval_minutes)),
        is_active=True,
    )
    
    repo = SiteRepository(db)
    saved = repo.save(site)
    
    return SiteDetailResponse(
        id=saved.id,
        name=saved.name,
        url=saved.url,
        selector=saved.selector,
        date_selector=saved.date_selector,
        date_param=saved.date_param,
        start_date_param=saved.start_date_param,
        end_date_param=saved.end_date_param,
        date_format=saved.date_format,
        page_size_param=saved.page_size_param,
        page_size_value=saved.page_size_value,
        category=saved.category,
        interval_minutes=saved.interval_minutes,
        is_active=saved.is_active,
        last_crawled_at=saved.last_crawled_at,
    )


@router.put("/sites/{site_id}", response_model=SiteDetailResponse)
def update_site(site_id: int, req: SiteUpdateRequest, db: Session = Depends(get_db)):
    """사이트 수정"""
    
    repo = SiteRepository(db)
    site = repo.find_by_id(site_id)
    
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")
    
    keep_raw_selectors = bool(req.keep_raw_selectors)

    # 업데이트할 필드만 적용
    if req.name is not None:
        site.name = req.name
    if req.url is not None:
        site.url = req.url
    if req.selector is not None:
        site.selector = req.selector if keep_raw_selectors else _normalize_selector(req.selector)
    if req.date_selector is not None:
        site.date_selector = req.date_selector if keep_raw_selectors else _normalize_selector(req.date_selector)
    if req.date_param is not None:
        site.date_param = req.date_param
    if req.start_date_param is not None:
        site.start_date_param = req.start_date_param
    if req.end_date_param is not None:
        site.end_date_param = req.end_date_param
    if req.date_format is not None:
        site.date_format = req.date_format
    if req.page_size_param is not None:
        site.page_size_param = req.page_size_param
    if req.page_size_value is not None:
        site.page_size_value = req.page_size_value
    if req.is_active is not None:
        site.is_active = req.is_active
    if req.category is not None:
        cat = (req.category or "").strip()
        site.category = cat if cat else "기타"
    if req.interval_minutes is not None:
        site.interval_minutes = max(1, int(req.interval_minutes))
    
    saved = repo.save(site)
    
    return SiteDetailResponse(
        id=saved.id,
        name=saved.name,
        url=saved.url,
        selector=saved.selector,
        date_selector=saved.date_selector,
        date_param=saved.date_param,
        start_date_param=saved.start_date_param,
        end_date_param=saved.end_date_param,
        date_format=saved.date_format,
        page_size_param=saved.page_size_param,
        page_size_value=saved.page_size_value,
        category=saved.category,
        interval_minutes=saved.interval_minutes,
        is_active=saved.is_active,
        last_crawled_at=saved.last_crawled_at,
    )


@router.delete("/sites/{site_id}")
def delete_site(site_id: int, db: Session = Depends(get_db)):
    """사이트 삭제"""
    repo = SiteRepository(db)
    success = repo.delete(site_id)
    
    if not success:
        raise HTTPException(status_code=404, detail="Site not found")
    
    return {"message": "Site deleted"}


# 설정 내보내기/가져오기
class SiteExportItem(BaseModel):
    name: str
    url: str
    selector: str
    date_selector: str
    date_param: str = ""
    start_date_param: str = ""
    end_date_param: str = ""
    date_format: str = "%Y-%m-%d"
    page_size_param: str = ""
    page_size_value: str = ""
    category: str
    interval_minutes: int = 20
    is_active: bool


class SitesImportRequest(BaseModel):
    sites: list[SiteExportItem]
    mode: str = "merge"  # "merge" or "replace"
    category_order: Optional[list[str]] = None


@router.get("/sites/export/all")
def export_sites(db: Session = Depends(get_db)):
    """모든 사이트 설정 내보내기 (JSON)"""
    repo = SiteRepository(db)
    settings = get_settings()
    prefs = load_ui_prefs(settings.base_dir)
    sites = repo.find_all()
    
    return {
        "version": "1.0",
        "exported_at": datetime.now().isoformat(),
        "category_order": prefs.get("category_order", []),
        "sites": [
            {
                "name": s.name,
                "url": s.url,
                "selector": s.selector,
                "date_selector": s.date_selector or "",
                "date_param": s.date_param or "",
                "start_date_param": s.start_date_param or "",
                "end_date_param": s.end_date_param or "",
                "date_format": s.date_format or "%Y-%m-%d",
                "page_size_param": s.page_size_param or "",
                "page_size_value": s.page_size_value or "",
                "category": s.category,
                "interval_minutes": s.interval_minutes,
                "is_active": s.is_active,
            }
            for s in sites
        ]
    }


@router.post("/sites/import/all")
def import_sites(req: SitesImportRequest, db: Session = Depends(get_db)):
    """사이트 설정 가져오기 (JSON)"""
    from domain import Site

    repo = SiteRepository(db)

    # replace 모드: 기존 데이터 모두 삭제
    if req.mode == "replace":
        existing = repo.find_all()
        for site in existing:
            repo.delete(site.id)

    imported_count = 0
    skipped_count = 0
    
    for item in req.sites:
        # merge 모드: URL이 같으면 스킵
        if req.mode == "merge":
            existing = repo.find_by_url(item.url)
            if existing:
                skipped_count += 1
                continue
        
        category = (item.category or "기타").strip() or "기타"
        site = Site(
            name=item.name,
            url=item.url,
            selector=item.selector,
            date_selector=item.date_selector,
            date_param=item.date_param,
            start_date_param=item.start_date_param,
            end_date_param=item.end_date_param,
            date_format=item.date_format or "%Y-%m-%d",
            page_size_param=item.page_size_param or "",
            page_size_value=item.page_size_value or "",
            category=category,
            interval_minutes=max(1, int(item.interval_minutes)),
            is_active=item.is_active,
        )
        repo.save(site)
        imported_count += 1

    if req.category_order is not None:
        settings = get_settings()
        save_ui_prefs(settings.base_dir, category_order=req.category_order)
    
    return {
        "message": f"Import completed",
        "imported": imported_count,
        "skipped": skipped_count,
        "mode": req.mode,
    }


@router.delete("/articles/clear")
def clear_articles(
    site_id: Optional[int] = Query(None, description="특정 사이트만 삭제"),
    db: Session = Depends(get_db)
):
    """게시글 데이터 삭제"""
    from infrastructure.database.models import ArticleModel
    
    query = db.query(ArticleModel)
    if site_id:
        query = query.filter(ArticleModel.site_id == site_id)
    
    count = query.delete()
    db.commit()
    
    return {"message": "Deleted", "count": count}

