"""Telegram bot handlers - all user interactions."""
import logging
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ContextTypes
from sqlalchemy.ext.asyncio import AsyncSession

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
        "Saya adalah bot *Customer Service* yang akan membantu menyalurkan aduan dari grup pelanggan ke grup operator.\n\n"
        "📋 *Cara penggunaan:*\n"
        "1. Tambahkan saya ke grup pelanggan\n"
        "2. Tambahkan saya ke grup operator\n"
        "3. Jadikan saya admin di kedua grup\n"
        "4. Matikan *Privacy Mode* via @BotFather\n\n"
        "Setiap aduan akan otomatis mendapatkan nomor tiket dan diteruskan ke grup operator."
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /help."""
    text = (
        "📖 *Panduan Penggunaan Bot*\n\n"
        "*Untuk Pelanggan (Grup Sumber):*\n"
        "• Kirim aduan di grup, bot akan otomatis membuat tiket\n"
        "• Bot akan meneruskan ke grup operator\n\n"
        "*Untuk Operator (Grup Operator):*\n"
        "• Balas pesan yang diforward untuk membalas ke pelanggan\n"
        "• Gunakan tombol status untuk update progress\n\n"
        "*Perintah yang tersedia:*\n"
        "`/stats` - Lihat statistik tiket\n"
        "`/chatid` - Cek ID grup ini\n"
        "`/help` - Tampilkan bantuan ini"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /stats - show ticket statistics."""
    async with AsyncSessionLocal() as session:
        service = TicketService(session)
        stats = await service.get_ticket_stats()
    
    text = (
        "📊 *Statistik Tiket*\n\n"
        f"🎫 Total Tiket: `{stats['total']}`\n"
        f"🟢 Open: `{stats['open']}`\n"
        f"🟡 Pending: `{stats['pending']}`\n"
        f"✅ Resolved: `{stats['resolved']}`"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def chatid_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /chatid - show current chat ID."""
    chat = update.effective_chat
    text = (
        f"📍 *Info Chat*\n\n"
        f"• Nama: `{chat.title or chat.full_name}`\n"
        f"• Type: `{chat.type}`\n"
        f"• Chat ID: `{chat.id}`"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


# ==================== MESSAGE HANDLERS ====================

async def handle_source_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle incoming messages from source groups (customer groups).
    Creates a ticket and forwards to operator group.
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
        )
    
    # Build notification for operator group
    user_mention = f"[{user.full_name}](tg://user?id={user.id})"
    group_link = ""
    if str(chat.id).startswith("-100"):
        group_id_part = str(chat.id)[4:]
        group_link = f"https://t.me/c/{group_id_part}/{message.message_id}"
    
    header = (
        f"🚨 *ADUAN BARU*\n"
        f"🎫 *No. Tiket:* `{ticket.ticket_number}`\n\n"
        f"📍 *Dari Grup:* {chat.title or 'Unknown'}\n"
        f"👤 *Pelapor:* {user_mention}\n"
        f"🆔 *User ID:* `{user.id}`\n"
        f"📎 *Tipe:* {content_type.upper()}\n"
        f"⏰ *Waktu:* {ticket.created_at.strftime('%Y-%m-%d %H:%M:%S')} UTC\n"
    )
    
    if group_link:
        header += f"🔗 [Link ke Pesan Asli]({group_link})\n"
    
    header += f"\n{'─' * 30}\n\n"
    
    if content_text:
        header += f"📝 *Isi Aduan:*\n{content_text[:800]}"
        if len(content_text) > 800:
            header += "..."
    else:
        header += "📝 *[Media tanpa teks]*"
    
    try:
        # Send header to operator group
        header_msg = await context.bot.send_message(
            chat_id=config.OPERATOR_GROUP_ID,
            text=header,
            parse_mode=ParseMode.MARKDOWN,
            disable_web_page_preview=True,
        )
        
        # Forward original message (preserves media)
        forwarded = await message.forward(chat_id=config.OPERATOR_GROUP_ID)
        
        # Send action buttons
        keyboard = [
            [
                InlineKeyboardButton("✅ Selesai", callback_data=f"status:resolved:{ticket.id}"),
                InlineKeyboardButton("⏳ Pending", callback_data=f"status:pending:{ticket.id}"),
            ],
            [
                InlineKeyboardButton("🔧 Sedang Diproses", callback_data=f"status:in_progress:{ticket.id}"),
                InlineKeyboardButton("📋 Info Tiket", callback_data=f"info:{ticket.id}"),
            ],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        action_msg = await context.bot.send_message(
            chat_id=config.OPERATOR_GROUP_ID,
            text=f"⚡ *Tiket:* `{ticket.ticket_number}`\nPilih status tindak lanjut:",
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN,
        )
        
        # Update ticket with operator message references
        async with AsyncSessionLocal() as session:
            service = TicketService(session)
            await service.update_operator_message(
                ticket_id=ticket.id,
                operator_chat_id=config.OPERATOR_GROUP_ID,
                operator_message_id=action_msg.message_id,
            )
        
        logger.info(f"Ticket {ticket.ticket_number} created and forwarded from {chat.title}")
        
    except Exception as e:
        logger.error(f"Failed to forward ticket {ticket.ticket_number}: {e}")


async def handle_operator_reply(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle replies from operator group.
    If an operator replies to a forwarded message or action message,
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
    
    # Find the ticket
    async with AsyncSessionLocal() as session:
        service = TicketService(session)
        
        # Try to find by action message ID
        ticket = await service.get_ticket_by_operator_message(
            operator_chat_id=chat.id,
            operator_message_id=reply_to.message_id,
        )
        
        # If not found, try to find by forwarded message
        if not ticket and reply_to.forward_from_chat:
            from sqlalchemy import select
            from core.models import Ticket
            result = await session.execute(
                select(Ticket).where(
                    Ticket.source_chat_id == reply_to.forward_from_chat.id,
                    Ticket.source_message_id == reply_to.forward_from_message_id,
                )
            )
            ticket = result.scalar_one_or_none()
    
    if not ticket:
        return
    
    # Send reply back to source group
    reply_text = message.text or message.caption or ""
    operator_mention = f"[{user.full_name}](tg://user?id={user.id})"
    
    try:
        # If it's text only
        if message.text:
            sent = await context.bot.send_message(
                chat_id=ticket.source_chat_id,
                text=(
                    f"📨 *Balasan dari Operator*\n"
                    f"🎫 *Tiket:* `{ticket.ticket_number}`\n"
                    f"👤 *Operator:* {operator_mention}\n"
                    f"\n{'─' * 20}\n\n"
                    f"{message.text}"
                ),
                parse_mode=ParseMode.MARKDOWN,
                reply_to_message_id=ticket.source_message_id,
            )
        else:
            # For media, send media with caption
            caption = (
                f"📨 *Balasan dari Operator*\n"
                f"🎫 *Tiket:* `{ticket.ticket_number}`\n"
                f"👤 *Operator:* {operator_mention}\n"
                f"\n{'─' * 20}"
            )
            
            if message.photo:
                sent = await context.bot.send_photo(
                    chat_id=ticket.source_chat_id,
                    photo=message.photo[-1].file_id,
                    caption=caption + (f"\n\n{message.caption}" if message.caption else ""),
                    parse_mode=ParseMode.MARKDOWN,
                    reply_to_message_id=ticket.source_message_id,
                )
            elif message.document:
                sent = await context.bot.send_document(
                    chat_id=ticket.source_chat_id,
                    document=message.document.file_id,
                    caption=caption + (f"\n\n{message.caption}" if message.caption else ""),
                    parse_mode=ParseMode.MARKDOWN,
                    reply_to_message_id=ticket.source_message_id,
                )
            else:
                # Fallback for other media types
                sent = await context.bot.send_message(
                    chat_id=ticket.source_chat_id,
                    text=caption + "\n\n[Media tidak didukung untuk dikirim balik]",
                    parse_mode=ParseMode.MARKDOWN,
                    reply_to_message_id=ticket.source_message_id,
                )
        
        # Log the reply in database
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
            f"✅ Balasan terkirim ke grup sumber!\n🎫 Tiket: `{ticket.ticket_number}`",
            parse_mode=ParseMode.MARKDOWN,
        )
        
        logger.info(f"Operator reply sent to source for ticket {ticket.ticket_number}")
        
    except Exception as e:
        logger.error(f"Failed to send operator reply: {e}")
        await message.reply_text(
            f"❌ Gagal mengirim balasan: {str(e)}",
        )


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
        
        await query.edit_message_text(
            (
                f"{status_emoji[new_status]} *Status Diperbarui*\n\n"
                f"🎫 *Tiket:* `{ticket.ticket_number}`\n"
                f"📌 *Status:* {new_status.value.upper()}\n"
                f"👤 *Oleh:* {user.full_name}\n"
                f"⏰ {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC"
            ),
            parse_mode=ParseMode.MARKDOWN,
        )
        
        # Notify source group about status update (optional)
        try:
            status_text = {
                TicketStatus.RESOLVED: "✅ *Tiket Anda telah DISELESAIKAN*",
                TicketStatus.PENDING: "⏳ *Tiket Anda sedang MENUNGGU* - mohon kesabarannya",
                TicketStatus.IN_PROGRESS: "🔧 *Tiket Anda sedang DITANGANI* oleh tim kami",
            }
            
            await context.bot.send_message(
                chat_id=ticket.source_chat_id,
                text=f"{status_text[new_status]}\n\n🎫 *No. Tiket:* `{ticket.ticket_number}`",
                parse_mode=ParseMode.MARKDOWN,
                reply_to_message_id=ticket.source_message_id,
            )
        except Exception as e:
            logger.warning(f"Could not notify source group: {e}")
    
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
            f"📋 *Detail Tiket*\n\n"
            f"🎫 *No:* `{ticket.ticket_number}`\n"
            f"📌 *Status:* {ticket.status.value.upper()}\n"
            f"🔥 *Priority:* {ticket.priority.value.upper()}\n"
            f"📍 *Grup:* {ticket.source_chat_title or 'Unknown'}\n"
            f"👤 *Pelapor:* {ticket.reporter_name}\n"
            f"⏰ *Dibuat:* {ticket.created_at.strftime('%Y-%m-%d %H:%M:%S')} UTC\n"
            f"⏳ *Durasi:* {duration}\n"
            f"🔔 *Alert:* {ticket.alert_count}x"
        )
        
        await query.edit_message_text(info_text, parse_mode=ParseMode.MARKDOWN)


# ==================== ERROR HANDLER ====================

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log errors."""
    logger.error(f"Update {update} caused error {context.error}", exc_info=context.error)
