from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings
from app.db.models import Base


def is_db_configured() -> bool:
    """DATABASE_URL이 설정되어 있으면 True."""
    url = (get_settings().database_url or "").strip()
    return bool(url) and url.startswith("mysql+asyncmy://")


_engine = None
_async_session_factory = None


def _get_engine():
    global _engine
    if _engine is None:
        url = get_settings().database_url.strip()
        _engine = create_async_engine(
            url,
            echo=False,
            pool_pre_ping=True,
            pool_size=5,
            max_overflow=10,
        )
    return _engine


def _get_session_factory():
    global _async_session_factory
    if _async_session_factory is None:
        _async_session_factory = async_sessionmaker(
            _get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )
    return _async_session_factory


@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """비동기 DB 세션 컨텍스트 매니저. DATABASE_URL 없으면 사용 불가."""
    if not is_db_configured():
        raise RuntimeError("DATABASE_URL is not set")
    factory = _get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db() -> None:
    """테이블 생성 (create_all). DATABASE_URL 없으면 no-op."""
    if not is_db_configured():
        return
    engine = _get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
