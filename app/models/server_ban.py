from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    PrimaryKeyConstraint,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ServerBan(Base):
    """A single, permanent-until-revoked ban cycle for a server member."""

    __tablename__ = "server_bans"

    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_server_bans"),
        CheckConstraint(
            "target_highest_role_position >= 0",
            name="ck_server_bans_non_negative_target_position",
        ),
        CheckConstraint(
            "(is_active AND revoked_at IS NULL AND revoked_by IS NULL) OR "
            "(NOT is_active AND revoked_at IS NOT NULL "
            "AND revoked_by IS NOT NULL)",
            name="ck_server_bans_revocation_consistency",
        ),
        CheckConstraint(
            "revoked_at IS NULL OR revoked_at >= banned_at",
            name="ck_server_bans_revoked_after_ban",
        ),
        CheckConstraint(
            "banned_by <> user_id",
            name="ck_server_bans_no_self_ban",
        ),
        UniqueConstraint(
            "id",
            "server_id",
            "user_id",
            name="uq_server_bans_id_server_user",
        ),
        ForeignKeyConstraint(
            ["server_id", "user_id"],
            ["server_members.server_id", "server_members.user_id"],
            name="fk_server_bans_member_server_user",
        ),
        Index(
            "uq_server_bans_one_active_per_user",
            "server_id",
            "user_id",
            unique=True,
            postgresql_where=text("is_active IS TRUE"),
        ),
        Index(
            "ix_server_bans_server_user_banned_at",
            "server_id",
            "user_id",
            "banned_at",
        ),
        Index(
            "ix_server_bans_server_active_banned_at",
            "server_id",
            "is_active",
            "banned_at",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    server_id: Mapped[int] = mapped_column(
        ForeignKey(
            "servers.id", name="fk_server_bans_server_id_servers"
        ),
        nullable=False,
    )

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", name="fk_server_bans_user_id_users"),
        nullable=False,
    )

    banned_by: Mapped[int] = mapped_column(
        ForeignKey("users.id", name="fk_server_bans_banned_by_users"),
        nullable=False,
    )

    banned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        server_default=text("true"),
        nullable=False,
    )

    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    revoked_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", name="fk_server_bans_revoked_by_users"),
        nullable=True,
    )

    target_highest_role_position: Mapped[int] = mapped_column(
        Integer, nullable=False
    )
