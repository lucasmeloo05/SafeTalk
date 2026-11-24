
from datetime import datetime

from sqlalchemy import (
    Boolean,
    ForeignKeyConstraint,
    false,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    Index,
    text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ServerChannel(Base):
    __tablename__ = "server_channels"

    __table_args__ = (
        UniqueConstraint("id", "server_id", name="uq_server_channels_id_server"),
        CheckConstraint(
            "channel_type IN ('TEXT', 'VOICE')",
            name="ck_server_channels_valid_type"
        ),
        Index("uq_server_channels_server_name", "server_id", "name", unique=True,
              postgresql_where=text("NOT is_archived")),
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

    is_read_only: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=false())
    is_archived: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=false())

    is_private: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=false())

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


class ServerChannelRole(Base):
    __tablename__ = "server_channel_roles"
    __table_args__ = (
        ForeignKeyConstraint(["channel_id", "server_id"], ["server_channels.id", "server_channels.server_id"]),
        ForeignKeyConstraint(["role_id", "server_id"], ["server_roles.id", "server_roles.server_id"],
                             name="fk_channel_access_role"),
    )

    channel_id: Mapped[int] = mapped_column(primary_key=True)
    role_id: Mapped[int] = mapped_column(primary_key=True)
    server_id: Mapped[int] = mapped_column(nullable=False)
