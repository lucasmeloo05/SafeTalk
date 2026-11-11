
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


class ServerMember(Base):
    __tablename__ = "server_members"

    __table_args__ = (
        UniqueConstraint(
            "server_id",
            "user_id",
            name="uq_server_members_server_user"
        ),
        UniqueConstraint(
            "id",
            "server_id",
            name="uq_server_members_id_server"
        ),
        CheckConstraint(
            "status IN ('ACTIVE', 'LEFT')",
            name="ck_server_members_valid_status"
        ),
        CheckConstraint(
            "(status = 'ACTIVE' AND left_at IS NULL) OR "
            "(status = 'LEFT' AND left_at IS NOT NULL)",
            name="ck_server_members_status_left_at"
        ),
    )

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True
    )

    server_id: Mapped[int] = mapped_column(
        ForeignKey("servers.id"),
        nullable=False,
        index=True
    )

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"),
        nullable=False,
        index=True
    )

    status: Mapped[str] = mapped_column(
        String(20),
        default="ACTIVE",
        nullable=False
    )

    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False
    )

    left_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True
    )
