from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    PrimaryKeyConstraint,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class MessageUpdateEvent(Base):
    __tablename__ = "message_update_events"

    __table_args__ = (
        PrimaryKeyConstraint("conversation_id", "revision", name="pk_message_update_events"),
        UniqueConstraint(
            "conversation_id",
            "revision",
            "message_id",
            name="uq_message_update_events_conversation_revision_message",
        ),
        CheckConstraint("revision >= 1", name="ck_message_update_events_revision_positive"),
        CheckConstraint("event_type IN ('UPDATED', 'DELETED', 'CREATED')", name="ck_message_update_events_type"),
        ForeignKeyConstraint(
            ["message_id", "conversation_id"],
            ["messages.id", "messages.conversation_id"],
            name="fk_message_update_events_message_conversation",
            ondelete="CASCADE",
        ),
    )

    conversation_id: Mapped[int] = mapped_column(
        ForeignKey(
            "conversations.id", name="fk_message_update_events_conversation", ondelete="CASCADE"
        ), nullable=False
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    message_id: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
