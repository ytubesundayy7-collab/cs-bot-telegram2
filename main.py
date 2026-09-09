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
    handle_source_message,
    handle_operator_reply,
    callback_handler,
    error_handler,
)
from core.database import init_db
from core.alert_service import AlertService

# Setup logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def setup_handlers(application: Application) -> None:
    """Register all handlers."""
    # Commands
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(CommandHandler("chatid", chatid_command))

    # Operator replies (must be before general group handler)
    application.add_handler(
        MessageHandler(
            filters.REPLY & filters.Chat(chat_id=config.OPERATOR_GROUP_ID) & ~filters.COMMAND,
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

    # Run alert check every X minutes
    application.job_queue.run_repeating(
        callback=lambda ctx: alert_service.check_and_alert(),
        interval=config.ALERT_INTERVAL_MINUTES * 60,
        first=60,  # First run after 1 minute
        name="pending_ticket_alert",
    )

    logger.info(f"Alert job scheduled every {config.ALERT_INTERVAL_MINUTES} minutes")


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

    # Build application
    application = (
        Application.builder()
        .token(config.BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    setup_handlers(application)

    # Render.com specific settings
    port = int(os.getenv("PORT", "10000"))
    webhook_url = os.getenv("WEBHOOK_URL", "")

    if not webhook_url:
        logger.error("WEBHOOK_URL environment variable is required for Render deployment!")
        logger.error("Please set WEBHOOK_URL in Render dashboard Environment settings.")
        return

    logger.info(f"Starting webhook on port {port}")
    logger.info(f"Webhook URL: {webhook_url}")

    # Start webhook (production mode for Render)
    application.run_webhook(
        listen="0.0.0.0",
        port=port,
        webhook_url=webhook_url,
        drop_pending_updates=True,
    )


if __name__ == "__main__":
    main()
