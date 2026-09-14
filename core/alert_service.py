"""Alert service - ringkasan tiket harian per kategori & brand (anti-spam)."""
import logging
from datetime import datetime

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode

from core.database import AsyncSessionLocal
from core.ticket_service import TicketService
from core.models import TicketStatus
from core.brands import get_brand_name, get_category_from_prefix
from bot.config import config

logger = logging.getLogger(__name__)

ACTIVE_STATUSES = [TicketStatus.OPEN, TicketStatus.PENDING, TicketStatus.IN_PROGRESS]
DONE_STATUSES = [TicketStatus.RESOLVED, TicketStatus.CLOSED]

STATUS_LABELS = {
    TicketStatus.OPEN: "Baru",
    TicketStatus.PENDING: "Pending",
    TicketStatus.IN_PROGRESS: "Diproses",
    TicketStatus.RESOLVED: "Selesai",
    TicketStatus.CLOSED: "Ditutup",
}


class AlertService:
    def __init__(self, bot: Bot):
        self.bot = bot

    async def check_and_alert(self) -> None:
        """Kirim 1 pesan ringkasan per kategori (bukan per tiket).

        Hanya kategori yang masih punya tiket aktif yang dikirim,
        supaya grup operator tidak di-spam saat semua beres.
        """
        async with AsyncSessionLocal() as session:
            service = TicketService(session)
            tickets = await service.get_tickets_today()

        if not tickets:
            return

        by_category = {}
        for ticket in tickets:
            oid = (ticket.order_id or "").split(" | ")[0].strip()
            category = get_category_from_prefix(oid[:2]) if oid else "UNKNOWN"
            by_category.setdefault(category, []).append(ticket)

        for category, cat_tickets in by_category.items():
            has_active = any(t.status in ACTIVE_STATUSES for t in cat_tickets)
            if not has_active:
                continue
            try:
                await self._send_category_summary(category, cat_tickets)
            except Exception as e:
                logger.error("Failed to send summary for %s: %s", category, e)

    async def _send_category_summary(self, category: str, tickets: list) -> None:
        """Kirim ringkasan 1 kategori, dikelompokkan per brand."""
        by_brand = {}
        for ticket in tickets:
            oid = (ticket.order_id or "").split(" | ")[0].strip()
            brand = get_brand_name(oid[2:5]) if len(oid) >= 5 else "LAINNYA"
            by_brand.setdefault(brand, []).append(ticket)

        lines = [
            "📊 *RINGKASAN " + category + "* — " + str(len(tickets)) + " tiket hari ini",
            "",
        ]
        keyboard = []

        for brand, brand_tickets in by_brand.items():
            lines.append("🏷 *" + brand + "* (" + str(len(brand_tickets)) + ")")
            for ticket in brand_tickets:
                oid = (ticket.order_id or "").split(" | ")[0].strip() or "-"
                label = STATUS_LABELS.get(ticket.status, ticket.status.value)
                if ticket.status in DONE_STATUSES:
                    dur = self._duration(ticket.created_at, ticket.resolved_at or ticket.updated_at)
                    lines.append("✅ `" + oid + "` — " + label + " (" + dur + ")")
                else:
                    dur = self._duration(ticket.created_at, datetime.utcnow())
                    lines.append("❌ `" + oid + "` — *" + label + "* — *" + dur + "*")
                    keyboard.append([
                        InlineKeyboardButton(
                            "✅ " + ticket.ticket_number,
                            callback_data="status:resolved:" + str(ticket.id),
                        ),
                        InlineKeyboardButton(
                            "🔧 " + ticket.ticket_number,
                            callback_data="status:in_progress:" + str(ticket.id),
                        ),
                    ])
            lines.append("")

        lines.append("⏰ _Update: " + datetime.utcnow().strftime("%H:%M") + " UTC_")
        text = "\n".join(lines)

        # Pengaman batas panjang pesan Telegram (4096 karakter)
        if len(text) > 3900:
            text = text[:3900] + "\n\n... (daftar terlalu panjang, cek /stats)"

        await self.bot.send_message(
            chat_id=config.OPERATOR_GROUP_ID,
            text=text,
            reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None,
            parse_mode=ParseMode.MARKDOWN,
        )
        logger.info("Summary sent for %s (%s tickets)", category, len(tickets))

    @staticmethod
    def _duration(start, end) -> str:
        """Hitung durasi ramah-baca, mis. '2j 15m'."""
        if not start or not end:
            return "-"
        total = int((end - start).total_seconds())
        if total < 0:
            total = 0
        hours = total // 3600
        minutes = (total % 3600) // 60
        return str(hours) + "j " + str(minutes) + "m"
