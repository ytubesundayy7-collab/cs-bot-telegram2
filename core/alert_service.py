"""Background alert service for pending tickets."""
import logging
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from sqlalchemy.ext.asyncio import AsyncSession
from core.database import AsyncSessionLocal
from core.ticket_service import TicketService
from core.models import TicketStatus
from bot.config import config

logger = logging.getLogger(__name__)


class AlertService:
    def __init__(self, bot: Bot):
        self.bot = bot

    async def check_and_alert(self) -> None:
        """Check pending tickets and send alerts as reply to original chat box."""
        async with AsyncSessionLocal() as session:
            service = TicketService(session)

            tickets = await service.get_pending_tickets_for_alert(
                config.PENDING_ALERT_THRESHOLD_MINUTES
            )

            for ticket in tickets:
                try:
                    await self._send_alert(ticket, service)
                except Exception as e:
                    logger.error(
                        "Failed to send alert for ticket %s: %s",
                        ticket.ticket_number,
                        e,
                    )

    async def _send_alert(self, ticket, service: TicketService) -> None:
        """Send alert with action buttons as reply to the original chat box."""
        duration = "Belum ditindak lanjuti"
        if ticket.created_at:
            from datetime import datetime
            delta = datetime.utcnow() - ticket.created_at
            hours = delta.seconds // 3600
            minutes = (delta.seconds % 3600) // 60
            duration = f"{hours}j {minutes}m"

        alert_text = (
            "🔔 *ALERT: TIKET MENUNGGU*\n\n"
            "🎫 *Tiket:* `" + ticket.ticket_number + "`\n"
            "📋 *Order ID:* `" + (ticket.order_id or "-") + "`. \n"
            "⏰ *Terdaftar:* " + ticket.created_at.strftime('%Y-%m-%d %H:%M:%S') + " UTC\n"
            "⏳ *Durasi:* " + duration + "\n"
            "⚠️ Alert ke-" + str(ticket.alert_count + 1)
        )

        keyboard = [
            [
                InlineKeyboardButton(
                    "✅ Selesai", callback_data="status:resolved:" + str(ticket.id)
                ),
                InlineKeyboardButton(
                    "⏳ Pending", callback_data="status:pending:" + str(ticket.id)
                ),
            ],
            [
                InlineKeyboardButton(
                    "🔧 Proses", callback_data="status:in_progress:" + str(ticket.id)
                ),
                InlineKeyboardButton(
                    "🛑 Abort Alert", callback_data="status:closed:" + str(ticket.id)
                ),
            ],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        if ticket.operator_message_id:
            await self.bot.send_message(
                chat_id=config.OPERATOR_GROUP_ID,
                text=alert_text,
                reply_to_message_id=ticket.operator_message_id,
                reply_markup=reply_markup,
                parse_mode=ParseMode.MARKDOWN,
            )
        else:
            await self.bot.send_message(
                chat_id=config.OPERATOR_GROUP_ID,
                text=alert_text,
                reply_markup=reply_markup,
                parse_mode=ParseMode.MARKDOWN,
            )

        await service.mark_alert_sent(ticket.id)
        logger.info("Alert sent for ticket %s", ticket.ticket_number)
