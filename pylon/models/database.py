"""
Database setup and session management.
"""

from pathlib import Path
from urllib.parse import urlparse

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from pylon.config import DatabaseConfig


class Base(DeclarativeBase):
    """Base class for all models."""

    pass


def get_database_url(config: DatabaseConfig) -> str:
    """Get the synchronous database URL from config.

    Converts async URLs to sync URLs if needed.
    e.g., sqlite+aiosqlite:// -> sqlite://
          postgresql+asyncpg:// -> postgresql://
    """
    url = config.url

    # Convert async driver to sync driver
    if "+aiosqlite" in url:
        return url.replace("+aiosqlite", "")
    elif "+asyncpg" in url:
        return url.replace("+asyncpg", "")

    return url


def get_async_database_url(config: DatabaseConfig) -> str:
    """Get the async database URL from config.

    Converts sync URLs to async URLs if needed.
    e.g., sqlite:// -> sqlite+aiosqlite://
          postgresql:// -> postgresql+asyncpg://
    """
    url = config.url

    # Already async
    if "+aiosqlite" in url or "+asyncpg" in url:
        return url

    # Convert sync driver to async driver
    if url.startswith("sqlite://"):
        return url.replace("sqlite://", "sqlite+aiosqlite://")
    elif url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://")

    return url


def _ensure_sqlite_parent_dir(url: str) -> None:
    """Ensure parent directory exists for SQLite database."""
    if "sqlite" in url:
        # Parse the URL to get the file path
        # Format: sqlite+aiosqlite:///./data/pylon.db or sqlite:///./data/pylon.db
        parsed = urlparse(url)
        if parsed.path:
            # Remove leading slashes
            path = parsed.path.lstrip("/")
            if path:
                db_path = Path(path)
                db_path.parent.mkdir(parents=True, exist_ok=True)


def create_db_engine(config: DatabaseConfig):
    """Create a synchronous database engine."""
    url = get_database_url(config)
    return create_engine(url, echo=False)


def create_async_db_engine(config: DatabaseConfig):
    """Create an async database engine."""
    url = get_async_database_url(config)
    _ensure_sqlite_parent_dir(url)
    return create_async_engine(url, echo=False)


def create_session_factory(engine):
    """Create a synchronous session factory."""
    return sessionmaker(bind=engine)


def create_async_session_factory(engine) -> async_sessionmaker[AsyncSession]:
    """Create an async session factory."""
    return async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)


async def init_db(config: DatabaseConfig):
    """Initialize the database, creating all tables."""
    engine = create_async_db_engine(config)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine
