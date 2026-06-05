"""
Async database engine, session factory, and request-scoped session dependency.

Design notes:
  - The pool is configured with pre_ping + recycle to survive idle-connection drops
    in cloud environments (PgBouncer, RDS, Aurora) without leaking dead connections.
  - get_db() is a *non-committing* dependency. Each route handler is responsible
    for committing its own unit of work — this prevents accidental partial writes
    when a handler returns early or when a downstream middleware short-circuits
    the response. The dependency only guarantees rollback-on-exception and
    proper cleanup.
"""

from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings


engine = create_async_engine(
    settings.DATABASE_URL,
    pool_size=settings.DATABASE_POOL_SIZE,
    max_overflow=settings.DATABASE_MAX_OVERFLOW,
    pool_timeout=settings.DATABASE_POOL_TIMEOUT,
    pool_recycle=settings.DATABASE_POOL_RECYCLE,
    pool_pre_ping=settings.DATABASE_POOL_PRE_PING,
    echo=settings.DEBUG,
    future=True,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    Yield a request-scoped AsyncSession.

    Transactional contract:
      - On normal completion: nothing happens here. The handler must call
        `await db.commit()` explicitly. This makes commit boundaries explicit
        in business code instead of magic side-effects of the dependency.
      - On any exception: rollback before re-raising, so connections
        return to the pool clean.
      - Always: session is closed via async-with, releasing the connection.
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
