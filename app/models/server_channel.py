
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


class ServerChannel(Base):
    __tablename__ = "server_channels"

    __table_args__ = (
        CheckConstraint(
            "channel_type IN ('TEXT', 'VOICE')",
            name="ck_server_channels_valid_type"
        ),
        UniqueConstraint(
            "server_id",
            "name",
            name="uq_server_channels_server_name"
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

    name: Mapped[str] = mapped_column(
        String(100),
        nullable=False
    )

    description: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True
    )

    channel_type: Mapped[str] = mapped_column(
        String(10),
        default="TEXT",
        nullable=False
    )

    position: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False
    )
