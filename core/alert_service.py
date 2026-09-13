"""Background alert service for pending tickets."""
import logging
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from sqlalchemy.ext.asyncio import AsyncSession
from core.database import AsyncSessionLocal
from core.ticket_service import TicketService
from core.models import TicketStatus
from core.brands import get_brand_code_from_order_id, get_brand_name
from bot.config import config

logger = logging.getLogger(__name__)


class AlertService:
    def __init__(self, bot: Bot):
        self.bot = bot

    async def check_and_alert(self) -> None:
        """Send category summary alerts every 15 minutes."""
        async with AsyncSessionLocal() as session:
            service = TicketService(session)

            # Get ALL tickets today (pending + resolved)
            tickets = await service.get_tickets_today()

            if not tickets:
                return

            # Group by category
            by_category = {}
            for ticket in tickets:
                # Determine category from first order_id
                order_ids = (ticket.order_id or "").split(" | ")
                first_oid = order_ids[0] if order_ids else ""
                prefix = first_oid[:2].upper() if first_oid else "XX"
                
                cat_map = {"DP": "DEPOSIT", "WD": "WITHDRAW", "ST": "SETTLEMENT"}
                category = cat_map.get(prefix, "UNKNOWN")
                
                if category not in by_category:
                    by_category[category] = []
                by_category[category].append(ticket)

            # Send summary for each category
            for category, cat_tickets in by_category.items():
                # Only send if there's at least 1 pending ticket
                has_pending = any(
                    t.status in [TicketStatus.OPEN, TicketStatus.PENDING]
                    for t in cat_tickets
                )
                if not has_pending:
                    continue

                await self._send_category_summary(
                    category, cat_tickets, service
                )

    async def _send_category_summary(
        self, category: str, tickets: list, service: TicketService
    ) -> None:
        """Send summary alert for a category, grouped by brand."""
        
        # Group tickets by brand
        by_brand = {}
        for ticket in tickets:
            order_ids = (ticket.order_id or "").split(" | ")
            first_oid = order_ids[0] if order_ids else ""
            brand_code = get_brand_code_from_order_id(first_oid)
            brand_name = get_brand_name(brand_code)
            
            if brand_name not in by_brand:
                by_brand[brand_name] = []
            by_brand[brand_name].append(ticket)

        # Build summary text
        lines = [
            "📊 *RINGKASAN: " + category + "*",
            "(" + str(len(tickets)) + " Tiket Hari Ini)\n",
        ]

        # Build keyboard buttons
        keyboard = []

        for brand_name, brand_tickets in by_brand.items():
            lines.append("🏷️ *" + brand_name + "* (" + str(len(brand_tickets)) + ")")
            
            for ticket in brand_tickets:
                order_ids = (ticket.order_id or "").split(" | ")
                first_oid = order_ids[0] if order_ids else "-"
                
                # Check status icon
                if ticket.status in [TicketStatus.RESOLVED, TicketStatus.CLOSED]:
                    icon = "✅"
                    status_text = "Selesai"
                else:
                    icon = "❌"
                    status_text = "Pending"
                
                # Calculate duration
                duration = ""
                if ticket.created_at:
                    from datetime import datetime
                    delta = datetime.utcnow() - ticket.created_at
                    hours = delta.seconds // 3600
                    minutes = (delta.seconds % 3600) // 60
                    if ticket.status in [TicketStatus.RESOLVED, TicketStatus.CLOSED]:
                        duration = " (" + str(hours) + "j " + str(minutes) + "m)"
                    else:
                        duration = " — *" + str(hours) + "j " + str(minutes) + "m*"
                
                lines.append(
                    icon + " `" + first_oid + "` — " + status_text + duration
                )
                
                # Add action button for pending tickets
                if ticket.status in [TicketStatus.OPEN, TicketStatus.PENDING]:
                    keyboard.append([
                        InlineKeyboardButton(
                            "✅ " + first_oid[:10] + "...",
                            callback_data="status:resolved:" + str(ticket.id),
                        ),
                        InlineKeyboardButton(
                            "🔧 Proses",
                            callback_data="status:in_progress:" + str(ticket.id),
                        ),
                    ])
            
            lines.append("")  # Empty line between brands

        from datetime import datetime
        lines.append("⏰ *Update:* " + datetime.utcnow().strftime('%H:%M') + " UTC")

        summary_text = "\n".join(lines)

        # Send summary (reply to first pending ticket's chat box if available)
        first_pending = None
        for t in tickets:
            if t.status in [TicketStatus.OPEN, TicketStatus.PENDING]:
                first_pending = t
                break

        try:
            if first_pending and first_pending.operator_message_id:
                await self.bot.send_message(
                    chat_id=config.OPERATOR_GROUP_ID,
                    text=summary_text,
                    reply_to_message_id=first_pending.operator_message_id,
                    reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None,
                    parse_mode=ParseMode.MARKDOWN,
                )
            else:
                await self.bot.send_message(
                    chat_id=config.OPERATOR_GROUP_ID,
                    text=summary_text,
                    reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None,
                    parse_mode=ParseMode.MARKDOWN,
                )
        except Exception as e:
            logger.error("Failed to send category summary: %s", e)

        # Mark alert sent for all pending tickets in this category
        for ticket in tickets:
            if ticket.status in [TicketStatus.OPEN, TicketStatus.PENDING]:
                try:
                    await service.mark_alert_sent(ticket.id)
                except Exception as e:
                    logger.warning("Failed to mark alert for %s: %s", ticket.ticket_number, e)

        logger.info("Category summary sent for %s (%s tickets)", category, len(tickets))
