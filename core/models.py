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
    ticket_number = Column(
        String(50), unique=True, nullable=False, index=True
    )
    order_id = Column(String(100), nullable=True, index=True)

    source_chat_id = Column(BigInteger, nullable=False)
    source_message_id = Column(BigInteger, nullable=False)
    source_chat_title = Column(String(255), nullable=True)

    operator_chat_id = Column(BigInteger, nullable=True)
    operator_message_id = Column(BigInteger, nullable=True)

    reporter_id = Column(BigInteger, nullable=False)
    reporter_name = Column(String(255), nullable=False)
    reporter_username = Column(String(100), nullable=True)

    content_text = Column(Text, nullable=True)
    content_type = Column(String(50), default="text")

    status = Column(
        Enum(TicketStatus), default=TicketStatus.OPEN, nullable=False
    )
    priority = Column(
        Enum(TicketPriority), default=TicketPriority.MEDIUM, nullable=False
    )

    created_at = Column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow,
        nullable=False,
    )
    resolved_at = Column(DateTime, nullable=True)

    alert_count = Column(Integer, default=0)
    last_alert_at = Column(DateTime, nullable=True)

    messages = relationship(
        "TicketMessage",
        back_populates="ticket",
        cascade="all, delete-orphan",
    )

    def __repr__(self):
        return f"<Ticket {self.ticket_number} - {self.status.value}>"


class TicketMessage(Base):
    __tablename__ = "ticket_messages"

    id = Column(Integer, primary_key=True, index=True)
    ticket_id = Column(Integer, ForeignKey("tickets.id"), nullable=False)
    direction = Column(String(20), nullable=False)
    chat_id = Column(BigInteger, nullable=False)
    message_id = Column(BigInteger, nullable=False)
    content_text = Column(Text, nullable=True)
    content_type = Column(String(50), default="text")
    sender_id = Column(BigInteger, nullable=False)
    sender_name = Column(String(255), nullable=False)
    created_at = Column(
        DateTime, default=datetime.utcnow, nullable=False
    )

    ticket = relationship("Ticket", back_populates="messages")


class RegisteredGroup(Base):
    __tablename__ = "registered_groups"

    id = Column(Integer, primary_key=True, index=True)
    chat_id = Column(BigInteger, unique=True, nullable=False, index=True)
    chat_title = Column(String(255), nullable=True)
    registered_at = Column(DateTime, default=datetime.utcnow, nullable=False)
