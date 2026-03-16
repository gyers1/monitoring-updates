"""SQLAlchemy models and database helpers."""

from datetime import datetime
from pathlib import Path
import sqlite3

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    create_engine,
)
from sqlalchemy.orm import Session, declarative_base, relationship, sessionmaker

from config import get_settings

Base = declarative_base()


class SiteModel(Base):
    """Monitored source site."""

    __tablename__ = "sites"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(200), nullable=False)
    url = Column(Text, nullable=False)
    selector = Column(Text, nullable=False)
    date_selector = Column(Text, default="")
    date_param = Column(Text, default="")
    start_date_param = Column(Text, default="")
    end_date_param = Column(Text, default="")
    date_format = Column(String(32), default="%Y-%m-%d")
    page_size_param = Column(Text, default="")
    page_size_value = Column(Text, default="")
    category = Column(String(50), default="\uAE30\uD0C0")
    interval_minutes = Column(Integer, default=20)
    is_active = Column(Boolean, default=True)
    last_crawled_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.now)

    articles = relationship("ArticleModel", back_populates="site")
    crawl_logs = relationship("CrawlLogModel", back_populates="site")


class ArticleModel(Base):
    """Collected article row."""

    __tablename__ = "articles"

    id = Column(Integer, primary_key=True, autoincrement=True)
    site_id = Column(Integer, ForeignKey("sites.id"), nullable=False)
    title = Column(Text, nullable=False)
    url = Column(Text, nullable=False, unique=True)
    content_summary = Column(Text, default="")
    collected_at = Column(DateTime, default=datetime.now)
    date_key = Column(String(10), nullable=False)

    site = relationship("SiteModel", back_populates="articles")

    __table_args__ = (
        Index("ix_articles_date_key", "date_key"),
        Index("ix_articles_site_date", "site_id", "date_key"),
    )


class CrawlLogModel(Base):
    """Stored crawl execution log."""

    __tablename__ = "crawl_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    site_id = Column(Integer, ForeignKey("sites.id"), nullable=False)
    status = Column(String(20), nullable=False)
    message = Column(Text, default="")
    articles_count = Column(Integer, default=0)
    crawled_at = Column(DateTime, default=datetime.now)

    site = relationship("SiteModel", back_populates="crawl_logs")


_engine = None
_SessionLocal = None


def get_engine():
    """Return a singleton SQLAlchemy engine."""

    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_engine(
            settings.database_url,
            connect_args={"check_same_thread": False},
            echo=settings.sql_echo,
        )
    return _engine


def get_session_factory():
    """Return a singleton session factory."""

    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=get_engine(),
        )
    return _SessionLocal


def get_db() -> Session:
    """FastAPI dependency that yields a database session."""

    SessionLocal = get_session_factory()
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_database():
    """Create missing tables and patch legacy site columns."""

    engine = get_engine()
    Base.metadata.create_all(bind=engine)
    _ensure_site_columns(engine)
    print("[OK] Database tables created")


def _ensure_site_columns(engine):
    """Ensure legacy SQLite databases have required site columns."""

    with engine.begin() as conn:
        cols = conn.exec_driver_sql("PRAGMA table_info(sites)").fetchall()
        existing = {row[1] for row in cols}
        additions = {
            "date_param": "TEXT",
            "start_date_param": "TEXT",
            "end_date_param": "TEXT",
            "date_format": "TEXT",
            "page_size_param": "TEXT",
            "page_size_value": "TEXT",
            "category": "TEXT DEFAULT ''",
            "interval_minutes": "INTEGER DEFAULT 20",
            "last_crawled_at": "TIMESTAMP",
            "created_at": "TIMESTAMP",
        }
        for name, col_type in additions.items():
            if name not in existing:
                conn.exec_driver_sql(f"ALTER TABLE sites ADD COLUMN {name} {col_type}")


def _resolve_sqlite_path() -> Path | None:
    settings = get_settings()
    database_url = str(settings.database_url or "").strip()
    if not database_url.startswith("sqlite:///"):
        return None
    raw_path = database_url[len("sqlite:///"):]
    if not raw_path:
        return None
    path = Path(raw_path)
    if not path.is_absolute():
        path = Path(settings.base_dir) / path
    return path.resolve()


def vacuum_sqlite_database() -> bool:
    """Compact SQLite database file after cleanup."""

    db_path = _resolve_sqlite_path()
    if not db_path or not db_path.exists():
        return False
    with sqlite3.connect(db_path) as conn:
        conn.execute("VACUUM")
    return True
