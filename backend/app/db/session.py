"""异步数据库 engine / session 工厂"""

from collections.abc import AsyncIterable

from app.core.config import settings
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

engine: AsyncEngine = create_async_engine(
    settings.database_url, echo=False, pool_pre_ping=True
)

AsyncSessionLocal: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=engine,
    expire_on_commit=False,
    autoflush=False,
)

# Celery 文档任务每次通过 asyncio.run 创建并关闭 event loop，不能复用 asyncpg
# 连接；Web 请求仍使用上方的默认连接池。
ingestion_engine: AsyncEngine = create_async_engine(
    settings.database_url, echo=False, pool_pre_ping=True, poolclass=NullPool
)

IngestionAsyncSessionLocal: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=ingestion_engine,
    expire_on_commit=False,
    autoflush=False,
)


async def get_session() -> AsyncIterable[AsyncSession]:
    """FastAPI依赖：提供请求级的AsyncSession"""
    async with AsyncSessionLocal() as session:
        yield session
