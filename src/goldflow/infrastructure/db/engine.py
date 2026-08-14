"""Engine and session factories. Sync engine exists for Alembic and scripts."""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from goldflow.infrastructure.settings import Settings


def build_async_engine(settings: Settings) -> AsyncEngine:
    return create_async_engine(settings.database_url, pool_size=10, max_overflow=5)


def build_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


def build_sync_engine(settings: Settings) -> Engine:
    return create_engine(settings.database_url_sync)
