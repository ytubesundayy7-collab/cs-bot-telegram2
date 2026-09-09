"""Business logic for ticket management."""
from datetime import datetime, timedelta
from typing import Optional
from sqlalchemy import select, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession
from core.models import Ticket, TicketMessage, TicketStatus, TicketPriority


class TicketService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def generate_ticket_number(self) -> str:
        """Generate ticket number format: TIX-YYYYMMDD-XXXX"""
        today = datetime.utcnow().strftime("%Y%m%d")
        prefix = f"TIX-{today}-"

        # Count tickets today
        result = await self.session.execute(
            select(Ticket).where(Ticket.ticket_number.like(f"{prefix}%"))
        )
        count = len(result.scalars().all())

        return f"{prefix}{count + 1:04d}"

    async def create_ticket(
        self,
        source_chat_id: int,
        source_message_id: int,
        source_chat_title: Optional[str],
        reporter_id: int,
        reporter_name: str,
        reporter_username: Optional[str],
        content_text: Optional[str],
        content_type: str = "text",
    ) -> Ticket:
        """Create a new ticket from incoming complaint."""
        ticket_number = await self.generate_ticket_number()

        ticket = Ticket(
            ticket_number=ticket_number,
            source_chat_id=source_chat_id,
            source_message_id=source_message_id,
            source_chat_title=source_chat_title,
            reporter_id=reporter_id,
            reporter_name=reporter_name,
            reporter_username=reporter_username,
            content_text=content_text,
            content_type=content_type,
            status=TicketStatus.OPEN,
            priority=TicketPriority.MEDIUM,
        )

        self.session.add(ticket)
        await self.session.commit()
        await self.session.refresh(ticket)

        # Log the initial message
        message = TicketMessage(
            ticket_id=ticket.id,
            direction="inbound",
            chat_id=source_chat_id,
            message_id=source_message_id,
            content_text=content_text,
            content_type=content_type,
            sender_id=reporter_id,
            sender_name=reporter_name,
        )
        self.session.add(message)
        await self.session.commit()

        return ticket

    async def get_ticket_by_id(self, ticket_id: int) -> Optional[Ticket]:
        result = await self.session.execute(
            select(Ticket).where(Ticket.id == ticket_id)
        )
        return result.scalar_one_or_none()

    async def get_ticket_by_number(self, ticket_number: str) -> Optional[Ticket]:
        result = await self.session.execute(
            select(Ticket).where(Ticket.ticket_number == ticket_number)
        )
        return result.scalar_one_or_none()

    async def get_ticket_by_operator_message(self, operator_chat_id: int, operator_message_id: int) -> Optional[Ticket]:
        """Find ticket by the forwarded message in operator group."""
        result = await self.session.execute(
            select(Ticket).where(
                and_(
                    Ticket.operator_chat_id == operator_chat_id,
                    Ticket.operator_message_id == operator_message_id,
                )
            )
        )
        return result.scalar_one_or_none()

    async def update_operator_message(
        self,
        ticket_id: int,
        operator_chat_id: int,
        operator_message_id: int,
    ) -> None:
        """Update the operator group message reference after forwarding."""
        ticket = await self.get_ticket_by_id(ticket_id)
        if ticket:
            ticket.operator_chat_id = operator_chat_id
            ticket.operator_message_id = operator_message_id
            await self.session.commit()

    async def update_status(
        self,
        ticket_id: int,
        status: TicketStatus,
    ) -> Optional[Ticket]:
        ticket = await self.get_ticket_by_id(ticket_id)
        if not ticket:
            return None

        ticket.status = status
        ticket.updated_at = datetime.utcnow()

        if status == TicketStatus.RESOLVED:
            ticket.resolved_at = datetime.utcnow()

        await self.session.commit()
        await self.session.refresh(ticket)
        return ticket

    async def add_reply(
        self,
        ticket_id: int,
        direction: str,  # "inbound" or "outbound"
        chat_id: int,
        message_id: int,
        content_text: Optional[str],
        sender_id: int,
        sender_name: str,
        content_type: str = "text",
    ) -> TicketMessage:
        """Add a reply message to ticket history."""
        message = TicketMessage(
            ticket_id=ticket_id,
            direction=direction,
            chat_id=chat_id,
            message_id=message_id,
            content_text=content_text,
            content_type=content_type,
            sender_id=sender_id,
            sender_name=sender_name,
        )
        self.session.add(message)
        await self.session.commit()
        await self.session.refresh(message)
        return message

    async def get_pending_tickets_for_alert(self, threshold_minutes: int) -> list[Ticket]:
        """Get tickets that need follow-up alerts."""
        threshold_time = datetime.utcnow() - timedelta(minutes=threshold_minutes)

        result = await self.session.execute(
            select(Ticket).where(
                and_(
                    Ticket.status.in_([TicketStatus.OPEN, TicketStatus.PENDING]),
                    or_(
                        Ticket.last_alert_at.is_(None),
                        Ticket.last_alert_at <= threshold_time,
                    ),
                )
            )
        )
        return result.scalars().all()

    async def mark_alert_sent(self, ticket_id: int) -> None:
        ticket = await self.get_ticket_by_id(ticket_id)
        if ticket:
            ticket.alert_count += 1
            ticket.last_alert_at = datetime.utcnow()
            await self.session.commit()

    async def get_ticket_stats(self) -> dict:
        """Get basic ticket statistics."""
        from sqlalchemy import func

        total = await self.session.execute(select(func.count(Ticket.id)))
        open_count = await self.session.execute(
            select(func.count(Ticket.id)).where(Ticket.status == TicketStatus.OPEN)
        )
        pending_count = await self.session.execute(
            select(func.count(Ticket.id)).where(Ticket.status == TicketStatus.PENDING)
        )
        resolved_count = await self.session.execute(
            select(func.count(Ticket.id)).where(Ticket.status == TicketStatus.RESOLVED)
        )

        return {
            "total": total.scalar(),
            "open": open_count.scalar(),
            "pending": pending_count.scalar(),
            "resolved": resolved_count.scalar(),
        }
