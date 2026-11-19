from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    Index,
    PrimaryKeyConstraint,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class MessageEditHistory(Base):
    """Internal, append-only record of effective message edits."""

    __tablename__ = "message_edit_history"

    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_message_edit_history"),
        CheckConstraint(
            "message_state_revision >= 1",
            name="ck_message_edit_history_revision_positive",
        ),
        CheckConstraint(
            "previous_content <> new_content",
            name="ck_message_edit_history_content_changed",
        ),
        UniqueConstraint(
            "message_id",
            "message_state_revision",
            name="uq_message_edit_history_message_revision",
        ),
        ForeignKeyConstraint(
            ["message_id", "conversation_id"],
            ["messages.id", "messages.conversation_id"],
            name="fk_message_edit_history_message_conversation",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["conversation_id", "message_state_revision", "message_id"],
            [
                "message_update_events.conversation_id",
                "message_update_events.revision",
                "message_update_events.message_id",
            ],
            name="fk_message_edit_history_update_event_message",
            ondelete="RESTRICT",
            deferrable=True,
            initially="DEFERRED",
        ),
        Index(
            "ix_message_edit_history_event_revision",
            "conversation_id",
            "message_state_revision",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    message_id: Mapped[int] = mapped_column(Integer, nullable=False)
    conversation_id: Mapped[int] = mapped_column(Integer, nullable=False)
    previous_content: Mapped[str] = mapped_column(Text, nullable=False)
    new_content: Mapped[str] = mapped_column(Text, nullable=False)
    edited_by_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", name="fk_message_edit_history_editor_users", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    edited_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    message_state_revision: Mapped[int] = mapped_column(Integer, nullable=False)
