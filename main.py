"""Entry point for the Telegram bot - optimized for Render.com deployment."""
import logging
import os
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)

from bot.config import config
from bot.handlers import (
    start_command,
    help_command,
    stats_command,
    chatid_command,
    broadcast_command,
    cancel_command,
    handle_source_message,
    handle_operator_reply,
    callback_handler,
    error_handler,
)
from core.database import init_db
from core.alert_service import AlertService

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def setup_handlers(application: Application) -> None:
    """Register all handlers."""
    # Commands (available everywhere)
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(CommandHandler("chatid", chatid_command))
    application.add_handler(CommandHandler("broadcast", broadcast_command))
    application.add_handler(CommandHandler("cancel", cancel_command))
    # Operator replies (only in operator group, must be reply)
    application.add_handler(
        MessageHandler(
            filters.REPLY
            & filters.Chat(chat_id=config.OPERATOR_GROUP_ID)
            & ~filters.COMMAND,
            handle_operator_reply,
        )
    )

    # Source group messages (all non-command messages in groups)
    application.add_handler(
        MessageHandler(
            filters.ChatType.GROUPS & ~filters.COMMAND,
            handle_source_message,
        )
    )

    # Callbacks
    application.add_handler(CallbackQueryHandler(callback_handler))

    # Errors
    application.add_error_handler(error_handler)


def setup_jobs(application: Application) -> None:
    """Setup background jobs (alerts)."""
    alert_service = AlertService(application.bot)

    application.job_queue.run_repeating(
        callback=lambda ctx: alert_service.check_and_alert(),
        interval=config.ALERT_INTERVAL_MINUTES * 60,
        first=60,
        name="pending_ticket_alert",
    )

    logger.info(
        "Alert job scheduled every %s minutes",
        config.ALERT_INTERVAL_MINUTES,
    )


async def post_init(application: Application) -> None:
    """Run after bot initialization."""
    logger.info("Initializing database...")
    await init_db()
    logger.info("Database initialized.")

    setup_jobs(application)
    logger.info("Bot is ready!")


def main() -> None:
    """Main entry point."""
    config.validate()

    application = (
        Application.builder()
        .token(config.BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    setup_handlers(application)

    port = int(os.getenv("PORT", "10000"))
    webhook_url = os.getenv("WEBHOOK_URL", "")

    if not webhook_url:
        logger.error(
            "WEBHOOK_URL environment variable is required for Render deployment!"
        )
        return

    logger.info("Starting webhook on port %s", port)
    logger.info("Webhook URL: %s", webhook_url)

    application.run_webhook(
        listen="0.0.0.0",
        port=port,
        webhook_url=webhook_url,
        drop_pending_updates=True,
    )


if __name__ == "__main__":
    main()
