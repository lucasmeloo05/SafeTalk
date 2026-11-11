
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ServerInvite(Base):
    __tablename__ = "server_invites"

    __table_args__ = (
        CheckConstraint(
            "uses_count >= 0",
            name="ck_server_invites_non_negative_uses"
        ),
        CheckConstraint(
            "max_uses IS NULL OR max_uses > 0",
            name="ck_server_invites_positive_max_uses"
        ),
        CheckConstraint(
            "max_uses IS NULL OR uses_count <= max_uses",
            name="ck_server_invites_uses_within_limit"
        ),
        CheckConstraint(
            "expires_at IS NULL OR expires_at > created_at",
            name="ck_server_invites_valid_expiration"
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

    created_by: Mapped[int] = mapped_column(
        ForeignKey("users.id"),
        nullable=False
    )

    token_hash: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        nullable=False
    )

    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True
    )

    max_uses: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True
    )

    uses_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False
    )

    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False
    )
