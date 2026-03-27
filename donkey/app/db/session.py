import asyncio
import threading
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings
from app.db.models import Base


def is_db_configured() -> bool:
    """DATABASE_URL이 설정되어 있으면 True."""
    url = (get_settings().database_url or "").strip()
    return bool(url) and url.startswith("mysql+asyncmy://")


# 워커마다 asyncio.run()으로 별도 이벤트 루프를 사용하므로 엔진/팩토리를 루프별로 분리.
# 같은 엔진을 다른 루프에서 쓰면 "Future attached to a different loop" 발생.
_engines: dict[int, Any] = {}
_session_factories: dict[int, Any] = {}
_lock = threading.Lock()


def _get_engine():
    loop = asyncio.get_running_loop()
    key = id(loop)
    with _lock:
        if key not in _engines:
            url = get_settings().database_url.strip()
            _engines[key] = create_async_engine(
                url,
                echo=False,
                pool_pre_ping=True,
                pool_size=5,
                max_overflow=10,
            )
        return _engines[key]


def _get_session_factory():
    loop = asyncio.get_running_loop()
    key = id(loop)
    engine = _get_engine()
    with _lock:
        if key not in _session_factories:
            _session_factories[key] = async_sessionmaker(
                engine,
                class_=AsyncSession,
                expire_on_commit=False,
                autoflush=False,
            )
        return _session_factories[key]


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
    """테이블 생성 (create_all). DATABASE_URL 없으면 no-op. 전역 엔진을 쓰지 않고 일회성 엔진으로 실행."""
    if not is_db_configured():
        return
    url = get_settings().database_url.strip()
    engine = create_async_engine(
        url,
        echo=False,
        pool_pre_ping=True,
        pool_size=1,
        max_overflow=0,
    )
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    finally:
        await engine.dispose()
