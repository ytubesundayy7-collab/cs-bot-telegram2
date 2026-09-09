"""SQLAlchemy models for the ticket system."""
from datetime import datetime
from sqlalchemy import Column, Integer, BigInteger, String, Text, DateTime, Enum, ForeignKey
from sqlalchemy.orm import relationship
from core.database import Base
import enum


class TicketStatus(str, enum.Enum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    PENDING = "pending"
    RESOLVED = "resolved"
    CLOSED = "closed"


class TicketPriority(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"


class Ticket(Base):
    __tablename__ = "tickets"

    id = Column(Integer, primary_key=True, index=True)
    ticket_number = Column(String(50), unique=True, nullable=False, index=True)

    # Source (customer group) info
    source_chat_id = Column(BigInteger, nullable=False)
    source_message_id = Column(BigInteger, nullable=False)
    source_chat_title = Column(String(255), nullable=True)

    # Operator group info
    operator_chat_id = Column(BigInteger, nullable=True)
    operator_message_id = Column(BigInteger, nullable=True)  # The forwarded message ID in operator group

    # Reporter info
    reporter_id = Column(BigInteger, nullable=False)
    reporter_name = Column(String(255), nullable=False)
    reporter_username = Column(String(100), nullable=True)

    # Content
    content_text = Column(Text, nullable=True)
    content_type = Column(String(50), default="text")  # text, photo, document, etc.

    # Status tracking
    status = Column(Enum(TicketStatus), default=TicketStatus.OPEN, nullable=False)
    priority = Column(Enum(TicketPriority), default=TicketPriority.MEDIUM, nullable=False)
    category = Column(String(100), nullable=True)  # For future AI classification

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    resolved_at = Column(DateTime, nullable=True)

    # Alert tracking
    alert_count = Column(Integer, default=0)
    last_alert_at = Column(DateTime, nullable=True)

    # Relationships
    messages = relationship("TicketMessage", back_populates="ticket", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Ticket {self.ticket_number} - {self.status.value}>"


class TicketMessage(Base):
    __tablename__ = "ticket_messages"

    id = Column(Integer, primary_key=True, index=True)
    ticket_id = Column(Integer, ForeignKey("tickets.id"), nullable=False)

    # Message direction: "inbound" (from customer) or "outbound" (from operator)
    direction = Column(String(20), nullable=False)

    # Telegram message references
    chat_id = Column(BigInteger, nullable=False)
    message_id = Column(BigInteger, nullable=False)

    # Content
    content_text = Column(Text, nullable=True)
    content_type = Column(String(50), default="text")

    # Sender info
    sender_id = Column(BigInteger, nullable=False)
    sender_name = Column(String(255), nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationship
    ticket = relationship("Ticket", back_populates="messages")
