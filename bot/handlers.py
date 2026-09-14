"""Telegram bot handlers - all user interactions."""
import logging
import os
import re
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from bot.config import config
from core.database import AsyncSessionLocal
from core.ticket_service import TicketService
from core.models import TicketStatus
from core.alert_service import AlertService
from sqlalchemy import text as sql_text

logger = logging.getLogger(__name__)

BOT_START_TIME = datetime.utcnow()


def esc(text):
    """Escape Markdown special characters for Telegram."""
    if not text:
        return ""
    return re.sub(r'([_*\[\]()~`>#+\-=|{}.!])', r'\\\1', str(text))


async def start_command(update, context):
    if update.effective_chat.type != "private":
        return
    text = """👋 *Halo!*

Saya adalah bot *Customer Service*.

📋 *Cara penggunaan:*
1. Tambahkan saya ke grup pelanggan
2. Tambahkan saya ke grup operator
3. Jadikan saya admin di kedua grup
4. Matikan *Privacy Mode* via @BotFather

Saya hanya akan merespon aduan yang mengandung *Order ID* / *Nomor Referensi*."""
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def help_command(update, context):
    text = """📖 *Panduan Bot*

*Untuk Pelanggan:*
• Sertakan Order ID / Nomor Referensi saat mengirim aduan
• Bot akan otomatis membuat tiket dan membalas

*Untuk Operator:*
• `/broadcast [pesan]` - Kirim pesan ke semua grup aduan
• `/cancel [nomor_tiket]` - Cancel 1 tiket
• `/cancelall` - Cancel SEMUA tiket pending
• `/stats` - Lihat statistik tiket
• `/status` - Cek status bot, database & webhook
• `/ping` - Cek cepat bot hidup/mati
• Klik tombol status untuk update progress
• Reply chat box untuk membalas ke pelanggan"""
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def stats_command(update, context):
    async with AsyncSessionLocal() as session:
        service = TicketService(session)
        stats = await service.get_ticket_stats()
    text = (
        "📊 *Statistik Tiket*\n\n"
        "🎫 Total: `" + str(stats['total']) + "`\n"
        "🟢 Open: `" + str(stats['open']) + "`\n"
        "🟡 Pending: `" + str(stats['pending']) + "`\n"
        "✅ Resolved: `" + str(stats['resolved']) + "`"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def chatid_command(update, context):
    chat = update.effective_chat
    text = (
        "📍 *Info Chat*\n\n"
        "• Nama: `" + str(chat.title or chat.full_name) + "`\n"
        "• Type: `" + str(chat.type) + "`\n"
        "• Chat ID: `" + str(chat.id) + "`"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def ping_command(update, context):
    """Cek cepat apakah bot hidup. Bisa dipakai di mana saja."""
    now = datetime.utcnow()
    uptime = str(now - BOT_START_TIME).split(".")[0]
    text = (
        "🏓 *Pong!* Bot aktif dan merespon.\n\n"
        "⏱ *Uptime:* `" + uptime + "`\n"
        "🕐 *Waktu server:* `" + now.strftime("%Y-%m-%d %H:%M:%S") + " UTC`"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def status_command(update, context):
    """Status lengkap bot: Render, database, webhook. Hanya untuk operator/private."""
    chat = update.effective_chat
    if chat.type in ["group", "supergroup"] and chat.id != config.OPERATOR_GROUP_ID:
        return

    now = datetime.utcnow()
    uptime = str(now - BOT_START_TIME).split(".")[0]

    # 1. Cek koneksi database
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(sql_text("SELECT 1"))
        db_status = "✅ Terhubung"
    except Exception as e:
        db_status = "❌ Error: " + str(e)[:80]

    # 2. Cek webhook Telegram
    try:
        wh = await context.bot.get_webhook_info()
        webhook_url = wh.url or "-"
        webhook_pending = str(wh.pending_update_count)
        webhook_error = wh.last_error_message or "Tidak ada"
    except Exception as e:
        webhook_url = "-"
        webhook_pending = "-"
        webhook_error = "Gagal cek: " + str(e)[:60]

    # 3. Statistik tiket
    try:
        async with AsyncSessionLocal() as session:
            service = TicketService(session)
            stats = await service.get_ticket_stats()
        stats_line = (
            "🎫 Total: `" + str(stats['total']) + "` | "
            "🟢 Open: `" + str(stats['open']) + "` | "
            "🟡 Pending: `" + str(stats['pending']) + "` | "
            "✅ Resolved: `" + str(stats['resolved']) + "`"
        )
    except Exception:
        stats_line = "⚠️ Gagal mengambil statistik"

    heartbeat_hours = os.getenv("HEARTBEAT_INTERVAL_HOURS", "6")

    text = (
        "🖥 *STATUS BOT MDGAMING*\n\n"
        "🤖 *Bot:* ✅ Online & merespon\n"
        "⏱ *Uptime:* `" + uptime + "`\n"
        "🕐 *Waktu server:* `" + now.strftime("%Y-%m-%d %H:%M:%S") + " UTC`\n\n"
        "🗄 *Database:* " + db_status + "\n"
        "🌐 *Webhook:* `" + webhook_url + "`\n"
        "📥 *Update tertunda:* `" + webhook_pending + "`\n"
        "⚠️ *Error webhook terakhir:* `" + webhook_error + "`\n\n"
        "📊 *Statistik Tiket:*\n" + stats_line + "\n\n"
        "🔔 *Interval alert:* `" + str(config.ALERT_INTERVAL_MINUTES) + " menit`\n"
        "💓 *Heartbeat:* tiap `" + heartbeat_hours + " jam`\n\n"
        "_Catatan: jika bot tidak membalas command ini, berarti bot sedang tidur/mati di Render._"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def broadcast_command(update, context):
    chat = update.effective_chat
    user = update.effective_user
    if chat.id != config.OPERATOR_GROUP_ID:
        return
    message_text = update.message.text or ""
    parts = message_text.split(" ", 1)
    if len(parts) < 2 or not parts[1].strip():
        await update.message.reply_text(
            "❌ Format salah. Gunakan: `/broadcast [pesan yang ingin dikirim]`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    broadcast_text = parts[1].strip()
    async with AsyncSessionLocal() as session:
        service = TicketService(session)
        source_groups = await service.get_all_source_groups()
    if not source_groups:
        await update.message.reply_text("❌ Belum ada grup aduan yang tercatat.")
        return
    sent_count = 0
    failed_count = 0
    for group_id in source_groups:
        try:
            await context.bot.send_message(
                chat_id=group_id,
                text=(
                    "📢 *PENGUMUMAN DARI OPERATOR*\n\n"
                    + broadcast_text + "\n\n"
                    + "_Dikirim oleh: " + esc(user.full_name) + "_"
                ),
                parse_mode=ParseMode.MARKDOWN,
            )
            sent_count += 1
        except Exception as e:
            logger.warning("Failed to broadcast to %s: %s", group_id, e)
            failed_count += 1
    await update.message.reply_text(
        (
            "✅ *Broadcast selesai!*\n"
            "📤 Terkirim: `" + str(sent_count) + "` grup\n"
            "❌ Gagal: `" + str(failed_count) + "` grup"
        ),
        parse_mode=ParseMode.MARKDOWN,
    )


async def cancel_command(update, context):
    """Cancel 1 tiket by ticket number (SILENT - no notification to source group)."""
    chat = update.effective_chat
    user = update.effective_user
    if chat.id != config.OPERATOR_GROUP_ID:
        return
    message_text = update.message.text or ""
    parts = message_text.split(" ", 1)
    if len(parts) < 2 or not parts[1].strip():
        await update.message.reply_text(
            "❌ Format salah. Gunakan: `/cancel [nomor_tiket]`\n\n"
            "Contoh: `/cancel TIX-20260912-0001`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    ticket_number = parts[1].strip().upper()
    async with AsyncSessionLocal() as session:
        service = TicketService(session)
        ticket = await service.force_close_ticket(ticket_number)
    if not ticket:
        await update.message.reply_text(
            "❌ Tiket `" + ticket_number + "` tidak ditemukan.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    # SILENT CANCEL - no notification to source group
    await update.message.reply_text(
        (
            "🛑 *Tiket di-CANCEL!*\n\n"
            "🎫 *Tiket:* `" + ticket.ticket_number + "`\n"
            "📋 *Order ID:* `" + (ticket.order_id or "-") + "`. \n"
            "📌 *Status:* CLOSED\n"
            "👤 *Oleh:* " + esc(user.full_name) + "\n\n"
            "✅ Alert untuk tiket ini sudah **dihentikan**."
        ),
        parse_mode=ParseMode.MARKDOWN,
    )
    logger.info(
        "Ticket %s force closed by %s (silent)", ticket.ticket_number, user.full_name
    )


async def cancelall_command(update, context):
    """Cancel ALL pending/open tickets at once (SILENT)."""
    chat = update.effective_chat
    user = update.effective_user
    if chat.id != config.OPERATOR_GROUP_ID:
        return

    async with AsyncSessionLocal() as session:
        service = TicketService(session)
        # Get all pending tickets
        pending_tickets = await service.get_pending_tickets_for_alert(
            threshold_minutes=0
        )

    if not pending_tickets:
        await update.message.reply_text(
            "✅ Tidak ada tiket pending yang perlu di-cancel.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    cancelled_count = 0
    failed_count = 0

    for ticket in pending_tickets:
        try:
            async with AsyncSessionLocal() as session:
                service = TicketService(session)
                await service.force_close_ticket(ticket.ticket_number)
            cancelled_count += 1
        except Exception as e:
            logger.error("Failed to cancel ticket %s: %s", ticket.ticket_number, e)
            failed_count += 1

    await update.message.reply_text(
        (
            "🛑 *CANCEL ALL SELESAI!*\n\n"
            "✅ *Berhasil:* `" + str(cancelled_count) + "` tiket\n"
            "❌ *Gagal:* `" + str(failed_count) + "` tiket\n\n"
            "👤 *Oleh:* " + esc(user.full_name) + "\n\n"
            "Semua tiket pending sudah di-CANCEL dan alert dihentikan."
        ),
        parse_mode=ParseMode.MARKDOWN,
    )

    logger.info(
        "CancelAll by %s: cancelled=%s, failed=%s",
        user.full_name,
        cancelled_count,
        failed_count,
    )


async def handle_source_message(update, context):
    message = update.effective_message
    chat = update.effective_chat
    user = update.effective_user
    if chat.type not in ["group", "supergroup"]:
        return
    if chat.id == config.OPERATOR_GROUP_ID:
        return
    if config.STRICT_MODE and chat.id not in config.SOURCE_GROUPS:
        return
    if user.is_bot:
        return

    content_text = message.text or message.caption or ""

    # Extract ALL valid Order IDs (strict brand validation)
    async with AsyncSessionLocal() as session:
        service = TicketService(session)
        all_order_ids = service.extract_all_order_ids(content_text)

    # Auto-register group even if no Order ID (for broadcast)
    async with AsyncSessionLocal() as session:
        service = TicketService(session)
        await service.register_source_group(chat.id, chat.title)

    if not all_order_ids:
        return

    # Determine content type
    content_type = "text"
    if message.photo:
        content_type = "photo"
    elif message.document:
        content_type = "document"
    elif message.video:
        content_type = "video"
    elif message.voice:
        content_type = "voice"

    created_tickets = []
    duplicate_tickets = []

    # Create 1 ticket PER ORDER ID (independent + anti-duplikat)
    for order_id in all_order_ids:
        prefix = order_id[:2].upper()
        cat_map = {"DP": "DEPOSIT", "WD": "WITHDRAW", "ST": "SETTLEMENT"}
        category = cat_map.get(prefix, "UNKNOWN")

        # Anti-duplikat: abaikan kalau Order ID ini masih punya tiket aktif
        async with AsyncSessionLocal() as session:
            service = TicketService(session)
            existing = await service.find_active_ticket_by_order_id(order_id)
        if existing:
            duplicate_tickets.append(existing)
            logger.info(
                "Duplicate complaint ignored: %s (masih aktif di %s)",
                order_id,
                existing.ticket_number,
            )
            continue

        async with AsyncSessionLocal() as session:
            service = TicketService(session)
            ticket = await service.create_ticket(
                source_chat_id=chat.id,
                source_message_id=message.message_id,
                source_chat_title=chat.title,
                reporter_id=user.id,
                reporter_name=user.full_name,
                reporter_username=user.username,
                content_text=content_text,
                content_type=content_type,
                order_id=order_id,
            )
            created_tickets.append((ticket, category, order_id))

        # === SIMPLIFIED CHAT BOX (with Markdown escape) ===
        safe_title = esc(chat.title) if chat.title else "Unknown"

        chat_box = (
            "🎫 *" + ticket.ticket_number + "*\n"
            "📋 *Order ID:* `" + order_id + "`\n"
            "📍 *Grup:* " + safe_title + "\n"
            "⏰ *Waktu:* " + ticket.created_at.strftime('%Y-%m-%d %H:%M:%S') + " UTC"
        )

        try:
            keyboard = [
                [
                    InlineKeyboardButton("✅ Selesai", callback_data="status:resolved:" + str(ticket.id)),
                    InlineKeyboardButton("⏳ Pending", callback_data="status:pending:" + str(ticket.id)),
                ],
                [
                    InlineKeyboardButton("🔧 Proses", callback_data="status:in_progress:" + str(ticket.id)),
                    InlineKeyboardButton("🛑 Cancel", callback_data="status:closed:" + str(ticket.id)),
                ],
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            operator_msg = await context.bot.send_message(
                chat_id=config.OPERATOR_GROUP_ID,
                text=chat_box,
                reply_markup=reply_markup,
                parse_mode=ParseMode.MARKDOWN,
                disable_web_page_preview=True,
            )

            async with AsyncSessionLocal() as session:
                service = TicketService(session)
                await service.update_operator_message(
                    ticket_id=ticket.id,
                    operator_chat_id=config.OPERATOR_GROUP_ID,
                    operator_message_id=operator_msg.message_id,
                )

            logger.info(
                "Ticket %s | Order ID: %s | From: %s",
                ticket.ticket_number,
                order_id,
                chat.title,
            )

        except Exception as e:
            logger.error(
                "Failed to send chat box for ticket %s: %s",
                ticket.ticket_number,
                e,
            )

    # Auto-reply ONCE ke grup aduan (tiket baru + info duplikat)
    if created_tickets or duplicate_tickets:
        reply_lines = []

        if created_tickets:
            reply_lines.append(config.AUTO_REPLY_TEXT)
            reply_lines.append("")
            for ticket, category, order_id in created_tickets:
                reply_lines.append(
                    "🎫 *No. Tiket:* `" + ticket.ticket_number + "` | 📂 *" + category + "*"
                )
                reply_lines.append("📋 *Order ID:* `" + order_id + "`")
                reply_lines.append("")
            reply_lines.append(
                "Mohon ditunggu ya, kami akan kabari lagi segera "
                "setelah ada perkembangan 😊"
            )

        if duplicate_tickets:
            if reply_lines:
                reply_lines.append("")
                reply_lines.append("➖➖➖➖➖")
                reply_lines.append("")
            else:
                reply_lines.append(
                    "🙏 *Terima kasih! Aduan Anda sudah kami terima sebelumnya.*"
                )
                reply_lines.append("")
            for dup in duplicate_tickets:
                reply_lines.append(
                    "⏳ `" + (dup.order_id or "-") + "` — sudah terdaftar di tiket `"
                    + dup.ticket_number + "` dan masih dalam proses"
                )
            reply_lines.append("")
            reply_lines.append(
                "Saat tim kami sedang menanganinya, "
                "Di mohon kesediaannya menunggu 🙏"
            )

        try:
            await context.bot.send_message(
                chat_id=chat.id,
                text="\n".join(reply_lines),
                parse_mode=ParseMode.MARKDOWN,
                reply_to_message_id=message.message_id,
            )
        except Exception as e:
            logger.error("Failed to send auto-reply: %s", e)


async def handle_operator_reply(update, context):
    message = update.effective_message
    chat = update.effective_chat
    user = update.effective_user
    if chat.id != config.OPERATOR_GROUP_ID:
        return
    if not message.reply_to_message:
        return
    if user.is_bot:
        return

    reply_to = message.reply_to_message

    async with AsyncSessionLocal() as session:
        service = TicketService(session)
        ticket = await service.get_ticket_by_operator_message(
            operator_chat_id=chat.id,
            operator_message_id=reply_to.message_id,
        )

    if not ticket:
        return

    reply_text = message.text or message.caption or ""
    try:
        if message.text:
            sent = await context.bot.send_message(
                chat_id=ticket.source_chat_id,
                text=(
                    "📨 *Pesan dari tim kami*\n\n"
                    "🎫 *No. Tiket:* `" + ticket.ticket_number + "`\n"
                    "📋 *Order ID:* `" + (ticket.order_id or "-") + "`\n\n"
                    + message.text
                ),
                parse_mode=ParseMode.MARKDOWN,
                reply_to_message_id=ticket.source_message_id,
            )
        else:
            caption = (
                "📨 *Pesan dari tim kami*\n\n"
                "🎫 *No. Tiket:* `" + ticket.ticket_number + "`\n"
                "📋 *Order ID:* `" + (ticket.order_id or "-") + "`"
            )
            if message.photo:
                sent = await context.bot.send_photo(
                    chat_id=ticket.source_chat_id,
                    photo=message.photo[-1].file_id,
                    caption=caption + ("\n\n" + message.caption if message.caption else ""),
                    parse_mode=ParseMode.MARKDOWN,
                    reply_to_message_id=ticket.source_message_id,
                )
            elif message.document:
                sent = await context.bot.send_document(
                    chat_id=ticket.source_chat_id,
                    document=message.document.file_id,
                    caption=caption + ("\n\n" + message.caption if message.caption else ""),
                    parse_mode=ParseMode.MARKDOWN,
                    reply_to_message_id=ticket.source_message_id,
                )
            else:
                sent = await context.bot.send_message(
                    chat_id=ticket.source_chat_id,
                    text=caption + "\n\n[Media tidak didukung]",
                    parse_mode=ParseMode.MARKDOWN,
                    reply_to_message_id=ticket.source_message_id,
                )

        async with AsyncSessionLocal() as session:
            service = TicketService(session)
            await service.add_reply(
                ticket_id=ticket.id,
                direction="outbound",
                chat_id=ticket.source_chat_id,
                message_id=sent.message_id,
                content_text=reply_text,
                sender_id=user.id,
                sender_name=user.full_name,
                content_type="text" if message.text else "media",
            )

        await message.reply_text(
            "✅ Balasan terkirim!\n🎫 `" + ticket.ticket_number + "` | 📋 `" + (ticket.order_id or "-") + "`. ",
            parse_mode=ParseMode.MARKDOWN,
        )

    except Exception as e:
        logger.error("Failed to send operator reply: %s", e)
        await message.reply_text("❌ Gagal mengirim balasan: " + str(e))


async def callback_handler(update, context):
    query = update.callback_query
    await query.answer()
    data = query.data
    user = query.from_user

    if data.startswith("status:"):
        parts = data.split(":")
        if len(parts) != 3:
            return
        _, status_str, ticket_id_str = parts
        ticket_id = int(ticket_id_str)

        status_map = {
            "resolved": TicketStatus.RESOLVED,
            "pending": TicketStatus.PENDING,
            "in_progress": TicketStatus.IN_PROGRESS,
            "closed": TicketStatus.CLOSED,
        }
        new_status = status_map.get(status_str)
        if not new_status:
            return

        async with AsyncSessionLocal() as session:
            service = TicketService(session)
            ticket = await service.update_status(ticket_id, new_status)

        if not ticket:
            await query.edit_message_text("❌ Tiket tidak ditemukan.")
            return

        status_emoji = {
            TicketStatus.RESOLVED: "✅",
            TicketStatus.PENDING: "⏳",
            TicketStatus.IN_PROGRESS: "🔧",
            TicketStatus.CLOSED: "🛑",
        }

        # Simplified update text (same format as chat box)
        safe_title = esc(ticket.source_chat_title)
        updated_text = (
            status_emoji[new_status] + " *" + ticket.ticket_number + "*\n"
            "📋 *Order ID:* `" + (ticket.order_id or "-") + "`\n"
            "📍 *Grup:* " + safe_title + "\n"
            "⏰ *Waktu:* " + ticket.created_at.strftime('%Y-%m-%d %H:%M:%S') + " UTC\n\n"
            "📌 *Status:* " + new_status.value.upper() + "\n"
            "👤 *Oleh:* " + esc(user.full_name)
        )

        keyboard = [
            [
                InlineKeyboardButton("✅ Selesai", callback_data="status:resolved:" + str(ticket.id)),
                InlineKeyboardButton("⏳ Pending", callback_data="status:pending:" + str(ticket.id)),
            ],
            [
                InlineKeyboardButton("🔧 Proses", callback_data="status:in_progress:" + str(ticket.id)),
                InlineKeyboardButton("🛑 Cancel", callback_data="status:closed:" + str(ticket.id)),
            ],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(
            updated_text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN,
        )

        # Notify source group for status changes (CLOSED/cancel tetap silent)
        status_messages = {
            TicketStatus.RESOLVED: (
                "✅ *Transaksi Anda telah SELESAI diproses!*\n\n"
                "🎫 *No. Tiket:* `" + ticket.ticket_number + "`\n"
                "📋 *Order ID:* `" + (ticket.order_id or "-") + "`\n\n"
                "Silakan lakukan pengecekan (crosscheck) pada transaksi Anda.\n"
                "Jika masih ada kendala, cukup kirim pesan baru dengan\n"
                "Order ID yang sama — tiket baru akan otomatis dibuat 🙏"
            ),
            TicketStatus.PENDING: (
                "⏳ *Update untuk tiket Anda*\n\n"
                "🎫 *No. Tiket:* `" + ticket.ticket_number + "`\n"
                "📋 *Order ID:* `" + (ticket.order_id or "-") + "`\n"
                "📌 *Status:* PENDING\n\n"
                "Transaksi Anda masih dalam antrian konfirmasi.\n"
                "Mohon menunggu sampai ada status selanjutnya ya —\n"
                "tidak perlu mengirim aduan ulang, tiket Anda tetap\n"
                "aktif dan terpantau oleh tim kami 🙏"
            ),
            TicketStatus.IN_PROGRESS: (
                "🔧 *Kabar baik, tiket Anda sedang ditangani!*\n\n"
                "🎫 *No. Tiket:* `" + ticket.ticket_number + "`\n"
                "📋 *Order ID:* `" + (ticket.order_id or "-") + "`\n"
                "📌 *Status:* SEDANG DIPROSES\n\n"
                "Tim kami sedang bekerja menyelesaikan transaksi Anda.\n"
                "Mohon ditunggu sampai ada status selanjutnya ya 🙏"
            ),
        }
        if new_status in status_messages:
            try:
                await context.bot.send_message(
                    chat_id=ticket.source_chat_id,
                    text=status_messages[new_status],
                    parse_mode=ParseMode.MARKDOWN,
                    reply_to_message_id=ticket.source_message_id,
                )
            except Exception as e:
                logger.warning("Could not notify source group: %s", e)

    elif data.startswith("info:"):
        ticket_id = int(data.split(":")[1])
        async with AsyncSessionLocal() as session:
            service = TicketService(session)
            ticket = await service.get_ticket_by_id(ticket_id)

        if not ticket:
            await query.edit_message_text("❌ Tiket tidak ditemukan.")
            return

        info_text = (
            "📋 *Detail Tiket*\n\n"
            "🎫 *No:* `" + ticket.ticket_number + "`\n"
            "📋 *Order ID:* `" + (ticket.order_id or "-") + "`\n"
            "📌 *Status:* " + ticket.status.value.upper() + "\n"
            "📍 *Grup:* " + esc(ticket.source_chat_title) + "\n"
            "👤 *Pelapor:* " + esc(ticket.reporter_name) + "\n"
            "⏰ *Dibuat:* " + ticket.created_at.strftime('%Y-%m-%d %H:%M:%S') + " UTC\n"
            "🔔 *Alert:* " + str(ticket.alert_count) + "x"
        )

        await query.edit_message_text(info_text, parse_mode=ParseMode.MARKDOWN)


async def error_handler(update, context):
    logger.error(
        "Update %s caused error %s", update, context.error, exc_info=context.error
    )
