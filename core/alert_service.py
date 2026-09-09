"""Background alert service for pending tickets."""
import logging
from telegram import Bot
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
        """Check pending tickets and send alerts to operator group."""
        async with AsyncSessionLocal() as session:
            service = TicketService(session)
            
            tickets = await service.get_pending_tickets_for_alert(
                config.PENDING_ALERT_THRESHOLD_MINUTES
            )
            
            for ticket in tickets:
                try:
                    await self._send_alert(ticket, service)
                except Exception as e:
                    logger.error(f"Failed to send alert for ticket {ticket.ticket_number}: {e}")
    
    async def _send_alert(self, ticket, service: TicketService) -> None:
        """Send alert message to operator group."""
        # Build alert message
        duration = "Belum ditindak lanjuti"
        if ticket.created_at:
            from datetime import datetime
            delta = datetime.utcnow() - ticket.created_at
            hours = delta.seconds // 3600
            minutes = (delta.seconds % 3600) // 60
            duration = f"{hours}j {minutes}m"
        
        alert_text = (
            f"🔔 *ALERT: TIKET MENUNGGU TINDAK LANJUT*\n\n"
            f"🎫 *No. Tiket:* `{ticket.ticket_number}`\n"
            f"⏰ *Terdaftar:* {ticket.created_at.strftime('%Y-%m-%d %H:%M:%S')} UTC\n"
            f"⏳ *Durasi:* {duration}\n"
            f"📍 *Dari Grup:* {ticket.source_chat_title or 'Unknown'}\n"
            f"👤 *Pelapor:* {ticket.reporter_name}\n"
            f"📝 *Isi:* {ticket.content_text[:200] if ticket.content_text else '[Media]'}...\n\n"
            f"⚠️ Alert ke-{ticket.alert_count + 1}"
        )
        
        await self.bot.send_message(
            chat_id=config.OPERATOR_GROUP_ID,
            text=alert_text,
            parse_mode=ParseMode.MARKDOWN,
        )
        
        await service.mark_alert_sent(ticket.id)
        logger.info(f"Alert sent for ticket {ticket.ticket_number}")
