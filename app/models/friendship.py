
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Friendship(Base):
    __tablename__ = "friendships"

    __table_args__ = (
        UniqueConstraint(
            "user_a_id",
            "user_b_id",
            name="uq_friendships_user_pair",
        ),
        CheckConstraint(
            "user_a_id < user_b_id",
            name="ck_friendships_user_order",
        ),
        CheckConstraint(
            "requested_by_id IN (user_a_id, user_b_id)",
            name="ck_friendships_requester_in_pair",
        ),
        CheckConstraint(
            "status IN ('PENDING', 'ACCEPTED', 'REJECTED', 'CANCELLED', 'REMOVED')",
            name="ck_friendships_valid_status",
        ),
    )

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
    )

    user_a_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"),
        nullable=False,
    )

    user_b_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"),
        nullable=False,
    )

    requested_by_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"),
        nullable=False,
    )

    status: Mapped[str] = mapped_column(
        String(20),
        default="PENDING",
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    responded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
