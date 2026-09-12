"""Configuration module - all settings loaded from environment variables."""
import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
    OPERATOR_GROUP_ID: int = int(os.getenv("OPERATOR_GROUP_ID", "0"))

    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        "postgresql+asyncpg://postgres:password@localhost:5432/botdb",
    )

    _source_groups_raw = os.getenv("SOURCE_GROUPS", "")
    SOURCE_GROUPS: list[int] = (
        [
            int(x.strip())
            for x in _source_groups_raw.split(",")
            if x.strip()
        ]
        if _source_groups_raw
        else []
    )
    STRICT_MODE: bool = bool(SOURCE_GROUPS)

    WEBHOOK_URL: str = os.getenv("WEBHOOK_URL", "")

    ALERT_INTERVAL_MINUTES: int = int(
        os.getenv("ALERT_INTERVAL_MINUTES", "15")
    )
    PENDING_ALERT_THRESHOLD_MINUTES: int = int(
        os.getenv("PENDING_ALERT_THRESHOLD_MINUTES", "15")
    )

    # Auto-reply message when ticket is created
    AUTO_REPLY_TEXT: str = os.getenv(
        "AUTO_REPLY_TEXT",
        "Baik, mohon ditunggu. Tim kami sedang mengecek transaksi Anda.",
    )

    # Minimum length for Order ID detection
    ORDER_ID_MIN_LENGTH: int = int(
        os.getenv("ORDER_ID_MIN_LENGTH", "5")
    )

    @classmethod
    def validate(cls) -> None:
        if not cls.BOT_TOKEN:
            raise ValueError("BOT_TOKEN is required")
        if not cls.OPERATOR_GROUP_ID:
            raise ValueError("OPERATOR_GROUP_ID is required")


config = Config()
