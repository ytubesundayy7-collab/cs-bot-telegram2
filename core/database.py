"""Database connection and session management."""
import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    create_async_engine,
    AsyncSession,
    async_sessionmaker,
)
from sqlalchemy.orm import declarative_base
from bot.config import config

engine = create_async_engine(
    config.DATABASE_URL,
    echo=False,
    future=True,
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)

Base = declarative_base()

logger = logging.getLogger(__name__)


async def init_db() -> None:
    """Create all tables + auto-migrasi enum status baru."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Tambahkan value 'FAILED' ke enum PostgreSQL (aman dijalankan berulang)
    # Catatan: SQLAlchemy menyimpan NAMA member enum (huruf besar), bukan value-nya
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text("ALTER TYPE ticketstatus ADD VALUE IF NOT EXISTS 'FAILED'")
            )
        logger.info("Enum ticketstatus: value 'FAILED' siap digunakan.")
    except Exception as e:
        logger.warning("Migrasi enum 'FAILED' dilewati: %s", e)


async def get_db() -> AsyncSession:
    """Dependency to get DB session."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()
