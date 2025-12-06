"""
Database setup and session management.
"""

from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from pylon.config import DatabaseConfig


class Base(DeclarativeBase):
    """Base class for all models."""

    pass


def get_database_url(config: DatabaseConfig) -> str:
    """Get the database URL from config."""
    if config.type == "sqlite":
        return f"sqlite:///{config.path}"
    elif config.type == "postgresql":
        return (
            f"postgresql://{config.username}:{config.password}"
            f"@{config.host}:{config.port}/{config.database}"
        )
    else:
        raise ValueError(f"Unsupported database type: {config.type}")


def get_async_database_url(config: DatabaseConfig) -> str:
    """Get the async database URL from config."""
    if config.type == "sqlite":
        return f"sqlite+aiosqlite:///{config.path}"
    elif config.type == "postgresql":
        return (
            f"postgresql+asyncpg://{config.username}:{config.password}"
            f"@{config.host}:{config.port}/{config.database}"
        )
    else:
        raise ValueError(f"Unsupported database type: {config.type}")


def create_db_engine(config: DatabaseConfig):
    """Create a synchronous database engine."""
    url = get_database_url(config)
    return create_engine(url, echo=False)


def create_async_db_engine(config: DatabaseConfig):
    """Create an async database engine."""
    # Ensure parent directory exists for SQLite
    if config.type == "sqlite" and config.path:
        db_path = Path(config.path)
        db_path.parent.mkdir(parents=True, exist_ok=True)

    url = get_async_database_url(config)
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
