"""Telegram bot handlers - all user interactions."""
import logging
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from bot.config import config
from core.database import AsyncSessionLocal
from core.ticket_service import TicketService
from core.models import TicketStatus
from core.alert_service import AlertService

logger = logging.getLogger(__name__)


async def start_command(update, context):
    if update.effective_chat.type != "private":
        return
    text = (
        "👋 *Halo!*

"
        "Saya adalah bot *Customer Service*.

"
        "📋 *Cara penggunaan:*
"
        "1. Tambahkan saya ke grup pelanggan
"
        "2. Tambahkan saya ke grup operator
"
        "3. Jadikan saya admin di kedua grup
"
        "4. Matikan *Privacy Mode* via @BotFather

"
        "Saya hanya akan merespon aduan yang mengandung *Order ID* / *Nomor Referensi*."
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def help_command(update, context):
    text = (
        "📖 *Panduan Bot*

"
        "*Untuk Pelanggan:*
"
        "• Sertakan Order ID / Nomor Referensi saat mengirim aduan
"
        "• Bot akan otomatis membuat tiket dan membalas

"
        "*Untuk Operator:*
"
        "• `/broadcast [pesan]` - Kirim pesan ke semua grup aduan
"
        "• `/cancel [nomor_tiket]` - Force cancel tiket
"
        "• `/stats` - Lihat statistik tiket
"
        "• Klik tombol status untuk update progress
"
        "• Reply chat box untuk membalas ke pelanggan"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def stats_command(update, context):
    async with AsyncSessionLocal() as session:
        service = TicketService(session)
        stats = await service.get_ticket_stats()
    text = (
        "📊 *Statistik Tiket*

"
        "🎫 Total: `" + str(stats['total']) + "`
"
        "🟢 Open: `" + str(stats['open']) + "`
"
        "🟡 Pending: `" + str(stats['pending']) + "`
"
        "✅ Resolved: `" + str(stats['resolved']) + "`"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def chatid_command(update, context):
    chat = update.effective_chat
    text = (
        "📍 *Info Chat*

"
        "• Nama: `" + str(chat.title or chat.full_name) + "`
"
        "• Type: `" + str(chat.type) + "`
"
        "• Chat ID: `" + str(chat.id) + "`"
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
        source_groups = await service.get_unique_source_groups()
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
                    "📢 *PENGUMUMAN DARI OPERATOR*

"
                    + broadcast_text + "

"
                    + "_Dikirim oleh: " + user.full_name + "_"
                ),
                parse_mode=ParseMode.MARKDOWN,
            )
            sent_count += 1
        except Exception as e:
            logger.warning("Failed to broadcast to %s: %s", group_id, e)
            failed_count += 1
    await update.message.reply_text(
        (
            "✅ *Broadcast selesai!*
"
            "📤 Terkirim: `" + str(sent_count) + "` grup
"
            "❌ Gagal: `" + str(failed_count) + "` grup"
        ),
        parse_mode=ParseMode.MARKDOWN,
    )


async def cancel_command(update, context):
    """
    Handle /cancel in operator group.
    Force close/cancel a ticket by ticket number.
    Usage: /cancel TIX-20260912-0001
    """
    chat = update.effective_chat
    user = update.effective_user

    if chat.id != config.OPERATOR_GROUP_ID:
        return

    message_text = update.message.text or ""
    parts = message_text.split(" ", 1)

    if len(parts) < 2 or not parts[1].strip():
        await update.message.reply_text(
            "❌ Format salah. Gunakan: `/cancel [nomor_tiket]`

"
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

    # Notify source group
    try:
        await context.bot.send_message(
            chat_id=ticket.source_chat_id,
            text=(
                "🛑 *Tiket Anda telah DITUTUP oleh Operator*

"
                "🎫 *Tiket:* `" + ticket.ticket_number + "`
"
                "📋 *Order ID:* `" + (ticket.order_id or "-") + "`. 
"
                "👤 *Oleh:* " + user.full_name + "

"
                "_Jika masih ada kendala, silakan buat aduan baru dengan Order ID._"
            ),
            parse_mode=ParseMode.MARKDOWN,
            reply_to_message_id=ticket.source_message_id,
        )
    except Exception as e:
        logger.warning("Could not notify source group: %s", e)

    await update.message.reply_text(
        (
            "🛑 *Tiket berhasil di-CANCEL!*

"
            "🎫 *Tiket:* `" + ticket.ticket_number + "`
"
            "📋 *Order ID:* `" + (ticket.order_id or "-") + "`. 
"
            "📌 *Status:* CLOSED
"
            "👤 *Oleh:* " + user.full_name + "

"
            "✅ Alert untuk tiket ini sudah **dihentikan permanen**."
        ),
        parse_mode=ParseMode.MARKDOWN,
    )

    logger.info(
        "Ticket %s force closed by %s", ticket.ticket_number, user.full_name
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

    if not all_order_ids:
        return

    # Group by category
    async with AsyncSessionLocal() as session:
        service = TicketService(session)
        grouped = service.group_order_ids_by_category(all_order_ids)

    content_type = "text"
    if message.photo:
        content_type = "photo"
    elif message.document:
        content_type = "document"
    elif message.video:
        content_type = "video"
    elif message.voice:
        content_type = "voice"

    # Create 1 ticket PER CATEGORY
    for category, order_ids in grouped.items():
        order_id_str = " | ".join(order_ids)

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
                order_id=order_id_str,
            )

        # Auto-reply
        try:
            await context.bot.send_message(
                chat_id=chat.id,
                text=(
                    config.AUTO_REPLY_TEXT + "

"
                    "🎫 *No. Tiket:* `" + ticket.ticket_number + "`
"
                    "📂 *Kategori:* `" + category + "`
"
                    "📋 *Order ID:* `" + order_id_str + "`"
                ),
                parse_mode=ParseMode.MARKDOWN,
                reply_to_message_id=message.message_id,
            )
        except Exception as e:
            logger.error("Failed to send auto-reply: %s", e)

        # Build chat box for operator
        user_mention = "[" + user.full_name + "](tg://user?id=" + str(user.id) + ")"
        group_link = ""
        if str(chat.id).startswith("-100"):
            group_id_part = str(chat.id)[4:]
            group_link = "https://t.me/c/" + group_id_part + "/" + str(message.message_id)

        content_preview = content_text[:300] if content_text else "[Media tanpa teks]"
        if len(content_text or "") > 300:
            content_preview += "..."

        if len(order_ids) == 1:
            order_display = "`" + order_ids[0] + "`"
        else:
            order_lines = ""
            for oid in order_ids:
                order_lines += "  • `" + oid + "`
"
            order_display = "
" + order_lines.strip()

        chat_box = (
            "🎫 *" + ticket.ticket_number + "* | 📂 *" + category + "*
"
            "📋 *Order ID (" + str(len(order_ids)) + " " + category + "):* " + order_display + "
"
            "📍 *Grup:* " + (chat.title or "Unknown") + " | 👤 *Pelapor:* " + user_mention + "
"
            "🆔 *User ID:* `" + str(user.id) + "` | ⏰ *" + ticket.created_at.strftime('%Y-%m-%d %H:%M:%S') + " UTC*
"
            "📎 *Jenis:* " + content_type.upper() + "
"
            "📝 *Isi:* " + content_preview
        )

        if group_link:
            chat_box += "
🔗 [Lihat Pesan Asli](" + group_link + ")"

        try:
            keyboard = [
                [
                    InlineKeyboardButton("✅ Selesai", callback_data="status:resolved:" + str(ticket.id)),
                    InlineKeyboardButton("⏳ Pending", callback_data="status:pending:" + str(ticket.id)),
                ],
                [
                    InlineKeyboardButton("🔧 Proses", callback_data="status:in_progress:" + str(ticket.id)),
                    InlineKeyboardButton("📋 Info", callback_data="info:" + str(ticket.id)),
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

        except Exception as e:
            logger.error("Failed to send chat box: %s", e)


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
    operator_mention = "[" + user.full_name + "](tg://user?id=" + str(user.id) + ")"

    try:
        if message.text:
            sent = await context.bot.send_message(
                chat_id=ticket.source_chat_id,
                text=(
                    "📨 *Balasan Operator*
"
                    "🎫 *Tiket:* `" + ticket.ticket_number + "`
"
                    "📋 *Order ID:* `" + (ticket.order_id or "-") + "`. 
"
                    "👤 *Operator:* " + operator_mention + "

"
                    + message.text
                ),
                parse_mode=ParseMode.MARKDOWN,
                reply_to_message_id=ticket.source_message_id,
            )
        else:
            caption = (
                "📨 *Balasan Operator*
"
                "🎫 *Tiket:* `" + ticket.ticket_number + "`
"
                "📋 *Order ID:* `" + (ticket.order_id or "-") + "`. 
"
                "👤 *Operator:* " + operator_mention
            )
            if message.photo:
                sent = await context.bot.send_photo(
                    chat_id=ticket.source_chat_id,
                    photo=message.photo[-1].file_id,
                    caption=caption + ("

" + message.caption if message.caption else ""),
                    parse_mode=ParseMode.MARKDOWN,
                    reply_to_message_id=ticket.source_message_id,
                )
            elif message.document:
                sent = await context.bot.send_document(
                    chat_id=ticket.source_chat_id,
                    document=message.document.file_id,
                    caption=caption + ("

" + message.caption if message.caption else ""),
                    parse_mode=ParseMode.MARKDOWN,
                    reply_to_message_id=ticket.source_message_id,
                )
            else:
                sent = await context.bot.send_message(
                    chat_id=ticket.source_chat_id,
                    text=caption + "

[Media tidak didukung]",
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
            "✅ Balasan terkirim!
🎫 `" + ticket.ticket_number + "` | 📋 `" + (ticket.order_id or "-") + "`. ",
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

        updated_text = (
            status_emoji[new_status] + " *" + ticket.ticket_number + "* | 📋 *Order ID:* `" + (ticket.order_id or "-") + "`. 
"
            "📍 *Grup:* " + (ticket.source_chat_title or "Unknown") + " | 👤 *Pelapor:* " + ticket.reporter_name + "
"
            "🆔 *User ID:* `" + str(ticket.reporter_id) + "` | ⏰ *" + ticket.created_at.strftime('%Y-%m-%d %H:%M:%S') + " UTC*
"
            "📎 *Jenis:* " + ticket.content_type.upper() + "
"
            "📝 *Isi:* " + (ticket.content_text[:300] if ticket.content_text else "[Media]") + "...

"
            "📌 *Status:* " + new_status.value.upper() + "
"
            "👤 *Diupdate oleh:* " + user.full_name + "
"
            "⏰ *" + datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S') + " UTC*"
        )

        keyboard = [
            [
                InlineKeyboardButton("✅ Selesai", callback_data="status:resolved:" + str(ticket.id)),
                InlineKeyboardButton("⏳ Pending", callback_data="status:pending:" + str(ticket.id)),
            ],
            [
                InlineKeyboardButton("🔧 Proses", callback_data="status:in_progress:" + str(ticket.id)),
                InlineKeyboardButton("📋 Info", callback_data="info:" + str(ticket.id)),
            ],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(
            updated_text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN,
        )

        try:
            status_text = {
                TicketStatus.RESOLVED: "✅ *Tiket Anda telah DISELESAIKAN*",
                TicketStatus.PENDING: "⏳ *Tiket Anda sedang MENUNGGU*",
                TicketStatus.IN_PROGRESS: "🔧 *Tiket Anda sedang DITANGANI*",
                TicketStatus.CLOSED: "🛑 *Tiket Anda telah DITUTUP* — Alert dihentikan",
            }
            await context.bot.send_message(
                chat_id=ticket.source_chat_id,
                text=(
                    status_text[new_status] + "

"
                    "🎫 *Tiket:* `" + ticket.ticket_number + "`
"
                    "📋 *Order ID:* `" + (ticket.order_id or "-") + "`. "
                ),
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

        duration = ""
        if ticket.created_at:
            delta = datetime.utcnow() - ticket.created_at
            hours = delta.seconds // 3600
            minutes = (delta.seconds % 3600) // 60
            duration = str(hours) + "j " + str(minutes) + "m"

        info_text = (
            "📋 *Detail Tiket*

"
            "🎫 *No:* `" + ticket.ticket_number + "`
"
            "📋 *Order ID:* `" + (ticket.order_id or "-") + "`. 
"
            "📌 *Status:* " + ticket.status.value.upper() + "
"
            "🔥 *Priority:* " + ticket.priority.value.upper() + "
"
            "📍 *Grup:* " + (ticket.source_chat_title or "Unknown") + "
"
            "👤 *Pelapor:* " + ticket.reporter_name + "
"
            "🆔 *User ID:* `" + str(ticket.reporter_id) + "`
"
            "⏰ *Dibuat:* " + ticket.created_at.strftime('%Y-%m-%d %H:%M:%S') + " UTC
"
            "⏳ *Durasi:* " + duration + "
"
            "🔔 *Alert:* " + str(ticket.alert_count) + "x"
        )

        await query.edit_message_text(info_text, parse_mode=ParseMode.MARKDOWN)


async def error_handler(update, context):
    logger.error(
        "Update %s caused error %s", update, context.error, exc_info=context.error
    )
