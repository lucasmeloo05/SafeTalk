
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Block(Base):
    __tablename__ = "blocks"

    __table_args__ = (
        UniqueConstraint(
            "blocker_id",
            "blocked_id",
            name="uq_blocks_blocker_blocked",
        ),
        CheckConstraint(
            "blocker_id <> blocked_id",
            name="ck_blocks_no_self_block",
        ),
    )

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
    )

    blocker_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"),
        nullable=False,
    )

    blocked_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"),
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
