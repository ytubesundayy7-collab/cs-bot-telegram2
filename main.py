"""Entry point for the Telegram bot - optimized for Render.com deployment."""
import asyncio
import json
import logging
import os
import signal
from datetime import datetime

import tornado.httpserver
import tornado.web

from telegram import Update
from telegram.constants import ParseMode
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
    cancelall_command,
    ping_command,
    status_command,
    handle_source_message,
    handle_operator_reply,
    callback_handler,
    error_handler,
)
from core.database import init_db, AsyncSessionLocal
from core.ticket_service import TicketService
from core.alert_service import AlertService

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

START_TIME = datetime.utcnow()


def setup_handlers(application: Application) -> None:
    """Register all handlers."""
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(CommandHandler("chatid", chatid_command))
    application.add_handler(CommandHandler("ping", ping_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("broadcast", broadcast_command))
    application.add_handler(CommandHandler("cancel", cancel_command))
    application.add_handler(CommandHandler("cancelall", cancelall_command))

    application.add_handler(
        MessageHandler(
            filters.REPLY
            & filters.Chat(chat_id=config.OPERATOR_GROUP_ID)
            & ~filters.COMMAND,
            handle_operator_reply,
        )
    )

    application.add_handler(
        MessageHandler(
            filters.ChatType.GROUPS & ~filters.COMMAND,
            handle_source_message,
        )
    )

    application.add_handler(CallbackQueryHandler(callback_handler))
    application.add_error_handler(error_handler)


async def heartbeat_job(context) -> None:
    """Kirim tanda hidup berkala ke grup operator."""
    try:
        uptime = str(datetime.utcnow() - START_TIME).split(".")[0]
        async with AsyncSessionLocal() as session:
            service = TicketService(session)
            stats = await service.get_ticket_stats()
        text = (
            "💓 *Heartbeat - Bot Aktif*\n\n"
            "⏱ *Uptime:* `" + uptime + "`\n"
            "🟢 *Open:* `" + str(stats['open']) + "` | "
            "🟡 *Pending:* `" + str(stats['pending']) + "` | "
            "✅ *Resolved:* `" + str(stats['resolved']) + "`\n\n"
            "_Bot terhubung ke Render dan berjalan normal._"
        )
        await context.bot.send_message(
            chat_id=config.OPERATOR_GROUP_ID,
            text=text,
            parse_mode=ParseMode.MARKDOWN,
        )
        logger.info("Heartbeat sent to operator group.")
    except Exception as e:
        logger.error("Heartbeat failed: %s", e)


def setup_jobs(application: Application) -> None:
    """Setup background jobs (alerts + heartbeat)."""
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

    # Heartbeat: bukti bot hidup, dikirim berkala ke grup operator.
    # Set HEARTBEAT_INTERVAL_HOURS=0 di env Render untuk mematikan.
    try:
        heartbeat_hours = float(os.getenv("HEARTBEAT_INTERVAL_HOURS", "6"))
    except ValueError:
        heartbeat_hours = 6
    if heartbeat_hours > 0:
        application.job_queue.run_repeating(
            callback=heartbeat_job,
            interval=heartbeat_hours * 3600,
            first=300,
            name="heartbeat",
        )
        logger.info("Heartbeat scheduled every %s hours", heartbeat_hours)


async def post_init(application: Application) -> None:
    """Run after bot initialization."""
    logger.info("Initializing database...")
    await init_db()
    logger.info("Database initialized.")

    setup_jobs(application)
    logger.info("Bot is ready!")


class HealthHandler(tornado.web.RequestHandler):
    """GET /health dan GET / - untuk UptimeRobot & cek manual via browser."""

    async def get(self):
        uptime = str(datetime.utcnow() - START_TIME).split(".")[0]
        self.set_header("Content-Type", "application/json")
        self.write(
            json.dumps(
                {
                    "status": "ok",
                    "bot": "MDGaming CS Bot",
                    "uptime": uptime,
                    "time_utc": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
                }
            )
        )

    async def head(self):
        self.set_status(200)


class WebhookHandler(HealthHandler):
    """POST / = update dari Telegram. GET / tetap health check."""

    def initialize(self, ptb_app) -> None:
        self.ptb_app = ptb_app

    async def post(self):
        try:
            data = json.loads(self.request.body.decode("utf-8"))
            update = Update.de_json(data, self.ptb_app.bot)
            await self.ptb_app.update_queue.put(update)
        except Exception as e:
            logger.error("Failed to process webhook update: %s", e)
        self.set_status(200)


async def run() -> None:
    """Main async entry point."""
    config.validate()

    application = (
        Application.builder()
        .token(config.BOT_TOKEN)
        .updater(None)
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

    await application.initialize()
    await application.start()

    await application.bot.set_webhook(
        url=webhook_url,
        drop_pending_updates=True,
    )
    logger.info("Webhook URL: %s", webhook_url)

    tornado_app = tornado.web.Application(
        [
            (r"/health", HealthHandler),
            (r"/", WebhookHandler, dict(ptb_app=application)),
        ]
    )
    server = tornado.httpserver.HTTPServer(tornado_app)
    server.listen(port, "0.0.0.0")
    logger.info("HTTP server listening on port %s", port)

    stop_event = asyncio.Event()

    def _stop() -> None:
        logger.info("Stop signal received.")
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _stop)
        except NotImplementedError:
            pass

    await stop_event.wait()

    logger.info("Shutting down...")
    server.stop()
    await application.stop()
    await application.shutdown()


def main() -> None:
    """Main entry point."""
    asyncio.run(run())


if __name__ == "__main__":
    main()
