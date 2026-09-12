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


# ==================== COMMAND HANDLERS ====================

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start in private chat."""
    if update.effective_chat.type != "private":
        return

    text = (
        "👋 *Halo!*\n\n"
        "Saya adalah bot *Customer Service*.\n\n"
        "📋 *Cara penggunaan:*\n"
        "1. Tambahkan saya ke grup pelanggan\n"
        "2. Tambahkan saya ke grup operator\n"
        "3. Jadikan saya admin di kedua grup\n"
        "4. Matikan *Privacy Mode* via @BotFather\n\n"
        "Saya hanya akan merespon aduan yang mengandung *Order ID* / *Nomor Referensi*."
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /help."""
    text = (
        "📖 *Panduan Bot*\n\n"
        "*Untuk Pelanggan:*\n"
        "• Sertakan Order ID / Nomor Referensi saat mengirim aduan\n"
        "• Bot akan otomatis membuat tiket dan membalas\n\n"
        "*Untuk Operator:*\n"
        "• `/broadcast [pesan]` - Kirim pesan ke semua grup aduan\n"
        "• `/stats` - Lihat statistik tiket\n"
        "• Klik tombol status untuk update progress\n"
        "• Reply chat box untuk membalas ke pelanggan"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /stats - show ticket statistics."""
    async with AsyncSessionLocal() as session:
        service = TicketService(session)
        stats = await service.get_ticket_stats()

    text = (
        "📊 *Statistik Tiket*\n\n"
        f"🎫 Total: `{stats['total']}`\n"
        f"🟢 Open: `{stats['open']}`\n"
        f"🟡 Pending: `{stats['pending']}`\n"
        f"✅ Resolved: `{stats['resolved']}`"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def chatid_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /chatid - show current chat ID."""
    chat = update.effective_chat
    text = (
        "📍 *Info Chat*\n\n"
        f"• Nama: `{chat.title or chat.full_name}`\n"
        f"• Type: `{chat.type}`\n"
        f"• Chat ID: `{chat.id}`"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle /broadcast in operator group.
    Sends message to all source groups that have sent complaints.
    Usage: /broadcast [message]
    """
    chat = update.effective_chat
    user = update.effective_user

    # Only allow in operator group
    if chat.id != config.OPERATOR_GROUP_ID:
        return

    # Extract broadcast message
    message_text = update.message.text or ""
    parts = message_text.split(" ", 1)

    if len(parts) < 2 or not parts[1].strip():
        await update.message.reply_text(
            "❌ Format salah. Gunakan: `/broadcast [pesan yang ingin dikirim]`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    broadcast_text = parts[1].strip()

    # Get all unique source groups from database
    async with AsyncSessionLocal() as session:
        service = TicketService(session)
        source_groups = await service.get_unique_source_groups()

    if not source_groups:
        await update.message.reply_text(
            "❌ Belum ada grup aduan yang tercatat."
        )
        return

    # Send broadcast to all source groups
    sent_count = 0
    failed_count = 0

    for group_id in source_groups:
        try:
            await context.bot.send_message(
                chat_id=group_id,
                text=(
                    "📢 *PENGUMUMAN DARI OPERATOR*\n\n"
                    f"{broadcast_text}\n\n"
                    f"_Dikirim oleh: {user.full_name}_"
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
            f"📤 Terkirim: `{sent_count}` grup\n"
            f"❌ Gagal: `{failed_count}` grup"
        ),
        parse_mode=ParseMode.MARKDOWN,
    )

    logger.info(
        "Broadcast by %s: sent=%s, failed=%s",
        user.full_name,
        sent_count,
        failed_count,
    )


# ==================== SOURCE GROUP HANDLER ====================

async def handle_source_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle incoming messages from source groups (customer groups).
    ONLY processes messages containing an Order ID.
    """
    message = update.effective_message
    chat = update.effective_chat
    user = update.effective_user

    # Validate
    if chat.type not in ["group", "supergroup"]:
        return

    if chat.id == config.OPERATOR_GROUP_ID:
        return

    if config.STRICT_MODE and chat.id not in config.SOURCE_GROUPS:
        return

    if user.is_bot:
        return

    # Extract content
    content_text = message.text or message.caption or ""

    # Check for Order ID
    async with AsyncSessionLocal() as session:
        service = TicketService(session)
        order_id = service.extract_order_id(
            content_text, config.ORDER_ID_MIN_LENGTH
        )

    if not order_id:
        # No Order ID found - ignore the message completely
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

    # Create ticket in database
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

    # Auto-reply to source group
    try:
        await context.bot.send_message(
            chat_id=chat.id,
            text=(
                f"{config.AUTO_REPLY_TEXT}\n\n"
                f"🎫 *No. Tiket:* `{ticket.ticket_number}`\n"
                f"📋 *Order ID:* `{order_id}`"
            ),
            parse_mode=ParseMode.MARKDOWN,
            reply_to_message_id=message.message_id,
        )
    except Exception as e:
        logger.error("Failed to send auto-reply: %s", e)

    # Build SINGLE chat box for operator group
    user_mention = f"[{user.full_name}](tg://user?id={user.id})"
    group_link = ""
    if str(chat.id).startswith("-100"):
        group_id_part = str(chat.id)[4:]
        group_link = f"https://t.me/c/{group_id_part}/{message.message_id}"

    # Format content preview
    content_preview = content_text[:300] if content_text else "[Media tanpa teks]"
    if len(content_text or "") > 300:
        content_preview += "..."

    # Build the single chat box message
    chat_box = (
        f"🎫 *{ticket.ticket_number}* | 📋 *Order ID:* `{order_id}`\n"
        f"📍 *Grup:* {chat.title or 'Unknown'} | 👤 *Pelapor:* {user_mention}\n"
        f"🆔 *User ID:* `{user.id}` | ⏰ *{ticket.created_at.strftime('%Y-%m-%d %H:%M:%S')} UTC*\n"
        f"📎 *Jenis:* {content_type.upper()}\n"
        f"📝 *Isi:* {content_preview}"
    )

    if group_link:
        chat_box += f"\n🔗 [Lihat Pesan Asli]({group_link})"

    try:
        # Send chat box with action buttons to operator group
        keyboard = [
            [
                InlineKeyboardButton(
                    "✅ Selesai", callback_data=f"status:resolved:{ticket.id}"
                ),
                InlineKeyboardButton(
                    "⏳ Pending", callback_data=f"status:pending:{ticket.id}"
                ),
            ],
            [
                InlineKeyboardButton(
                    "🔧 Proses", callback_data=f"status:in_progress:{ticket.id}"
                ),
                InlineKeyboardButton(
                    "📋 Info", callback_data=f"info:{ticket.id}"
                ),
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

        # Store operator message reference
        async with AsyncSessionLocal() as session:
            service = TicketService(session)
            await service.update_operator_message(
                ticket_id=ticket.id,
                operator_chat_id=config.OPERATOR_GROUP_ID,
                operator_message_id=operator_msg.message_id,
            )

        logger.info(
            "Ticket %s | Order ID: %s | From: %s | Reporter: %s",
            ticket.ticket_number,
            order_id,
            chat.title,
            user.full_name,
        )

    except Exception as e:
        logger.error(
            "Failed to send chat box for ticket %s: %s",
            ticket.ticket_number,
            e,
        )


# ==================== OPERATOR REPLY HANDLER ====================

async def handle_operator_reply(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle replies from operator group.
    If an operator replies to a chat box message,
    send the reply back to the source group.
    """
    message = update.effective_message
    chat = update.effective_chat
    user = update.effective_user

    # Only process in operator group
    if chat.id != config.OPERATOR_GROUP_ID:
        return

    # Must be a reply
    if not message.reply_to_message:
        return

    # Ignore bot's own messages
    if user.is_bot:
        return

    reply_to = message.reply_to_message

    # Find the ticket by operator message ID
    async with AsyncSessionLocal() as session:
        service = TicketService(session)
        ticket = await service.get_ticket_by_operator_message(
            operator_chat_id=chat.id,
            operator_message_id=reply_to.message_id,
        )

    if not ticket:
        return

    # Send reply back to source group
    reply_text = message.text or message.caption or ""
    operator_mention = f"[{user.full_name}](tg://user?id={user.id})"

    try:
        if message.text:
            sent = await context.bot.send_message(
                chat_id=ticket.source_chat_id,
                text=(
                    "📨 *Balasan Operator*\n"
                    f"🎫 *Tiket:* `{ticket.ticket_number}`\n"
                    f"📋 *Order ID:* `{ticket.order_id or '-'}`. \n"
                    f"👤 *Operator:* {operator_mention}\n\n"
                    f"{message.text}"
                ),
                parse_mode=ParseMode.MARKDOWN,
                reply_to_message_id=ticket.source_message_id,
            )
        else:
            caption = (
                "📨 *Balasan Operator*\n"
                f"🎫 *Tiket:* `{ticket.ticket_number}`\n"
                f"📋 *Order ID:* `{ticket.order_id or '-'}`. \n"
                f"👤 *Operator:* {operator_mention}"
            )

            if message.photo:
                sent = await context.bot.send_photo(
                    chat_id=ticket.source_chat_id,
                    photo=message.photo[-1].file_id,
                    caption=caption
                    + (f"\n\n{message.caption}" if message.caption else ""),
                    parse_mode=ParseMode.MARKDOWN,
                    reply_to_message_id=ticket.source_message_id,
                )
            elif message.document:
                sent = await context.bot.send_document(
                    chat_id=ticket.source_chat_id,
                    document=message.document.file_id,
                    caption=caption
                    + (f"\n\n{message.caption}" if message.caption else ""),
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

        # Log reply
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

        # Confirm to operator
        await message.reply_text(
            (
                "✅ Balasan terkirim!\n"
                f"🎫 `{ticket.ticket_number}` | 📋 `{ticket.order_id or '-'}`. "
            ),
            parse_mode=ParseMode.MARKDOWN,
        )

        logger.info(
            "Reply sent to source for ticket %s", ticket.ticket_number
        )

    except Exception as e:
        logger.error("Failed to send operator reply: %s", e)
        await message.reply_text(f"❌ Gagal mengirim balasan: {str(e)}")


# ==================== CALLBACK HANDLERS ====================

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle inline keyboard button callbacks."""
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
        }

        # Update the chat box with new status
        updated_text = (
            f"{status_emoji[new_status]} *{ticket.ticket_number}* | 📋 *Order ID:* `{ticket.order_id or '-'}`. \n"
            f"📍 *Grup:* {ticket.source_chat_title or 'Unknown'} | 👤 *Pelapor:* {ticket.reporter_name}\n"
            f"🆔 *User ID:* `{ticket.reporter_id}` | ⏰ *{ticket.created_at.strftime('%Y-%m-%d %H:%M:%S')} UTC*\n"
            f"📎 *Jenis:* {ticket.content_type.upper()}\n"
            f"📝 *Isi:* {ticket.content_text[:300] if ticket.content_text else '[Media]'}...\n\n"
            f"📌 *Status:* {new_status.value.upper()}\n"
            f"👤 *Diupdate oleh:* {user.full_name}\n"
            f"⏰ *{datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC*"
        )

        # Re-add buttons
        keyboard = [
            [
                InlineKeyboardButton(
                    "✅ Selesai", callback_data=f"status:resolved:{ticket.id}"
                ),
                InlineKeyboardButton(
                    "⏳ Pending", callback_data=f"status:pending:{ticket.id}"
                ),
            ],
            [
                InlineKeyboardButton(
                    "🔧 Proses", callback_data=f"status:in_progress:{ticket.id}"
                ),
                InlineKeyboardButton(
                    "📋 Info", callback_data=f"info:{ticket.id}"
                ),
            ],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(
            updated_text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN,
        )

        # Notify source group
        try:
            status_text = {
                TicketStatus.RESOLVED: "✅ *Tiket Anda telah DISELESAIKAN*",
                TicketStatus.PENDING: "⏳ *Tiket Anda sedang MENUNGGU*",
                TicketStatus.IN_PROGRESS: "🔧 *Tiket Anda sedang DITANGANI*",
            }

            await context.bot.send_message(
                chat_id=ticket.source_chat_id,
                text=(
                    f"{status_text[new_status]}\n\n"
                    f"🎫 *Tiket:* `{ticket.ticket_number}`\n"
                    f"📋 *Order ID:* `{ticket.order_id or '-'}`. "
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
            duration = f"{hours}j {minutes}m"

        info_text = (
            "📋 *Detail Tiket*\n\n"
            f"🎫 *No:* `{ticket.ticket_number}`\n"
            f"📋 *Order ID:* `{ticket.order_id or '-'}`. \n"
            f"📌 *Status:* {ticket.status.value.upper()}\n"
            f"🔥 *Priority:* {ticket.priority.value.upper()}\n"
            f"📍 *Grup:* {ticket.source_chat_title or 'Unknown'}\n"
            f"👤 *Pelapor:* {ticket.reporter_name}\n"
            f"🆔 *User ID:* `{ticket.reporter_id}`\n"
            f"⏰ *Dibuat:* {ticket.created_at.strftime('%Y-%m-%d %H:%M:%S')} UTC\n"
            f"⏳ *Durasi:* {duration}\n"
            f"🔔 *Alert:* {ticket.alert_count}x"
        )

        await query.edit_message_text(info_text, parse_mode=ParseMode.MARKDOWN)


# ==================== ERROR HANDLER ====================

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log errors."""
    logger.error(
        "Update %s caused error %s", update, context.error, exc_info=context.error
    )
