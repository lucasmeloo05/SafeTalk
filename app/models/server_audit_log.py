from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    PrimaryKeyConstraint,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ServerAuditLog(Base):
    """Immutable moderation event; snapshots are historical only."""

    __tablename__ = "server_audit_logs"

    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_server_audit_logs"),
        CheckConstraint(
            "event_type IN "
            "('MEMBER_KICKED', 'MEMBER_BANNED', 'MEMBER_UNBANNED')",
            name="ck_server_audit_logs_valid_event_type",
        ),
        CheckConstraint(
            "actor_user_id <> target_user_id",
            name="ck_server_audit_logs_actor_differs_from_target",
        ),
        CheckConstraint(
            "(event_type = 'MEMBER_KICKED' AND ban_id IS NULL "
            "AND role_snapshot IS NOT NULL "
            "AND jsonb_typeof(role_snapshot) = 'array') OR "
            "(event_type = 'MEMBER_BANNED' AND ban_id IS NOT NULL "
            "AND role_snapshot IS NOT NULL "
            "AND jsonb_typeof(role_snapshot) = 'array') OR "
            "(event_type = 'MEMBER_UNBANNED' AND ban_id IS NOT NULL "
            "AND (role_snapshot IS NULL "
            "OR role_snapshot = 'null'::jsonb))",
            name="ck_server_audit_logs_event_ban_snapshot_consistency",
        ),
        ForeignKeyConstraint(
            ["ban_id", "server_id", "target_user_id"],
            ["server_bans.id", "server_bans.server_id", "server_bans.user_id"],
            name="fk_server_audit_logs_ban_server_target",
        ),
        Index(
            "ix_server_audit_logs_server_occurred_at",
            "server_id",
            "occurred_at",
        ),
        Index(
            "ix_server_audit_logs_server_target_occurred_at",
            "server_id",
            "target_user_id",
            "occurred_at",
        ),
        Index(
            "ix_server_audit_logs_server_actor_occurred_at",
            "server_id",
            "actor_user_id",
            "occurred_at",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    server_id: Mapped[int] = mapped_column(
        ForeignKey(
            "servers.id", name="fk_server_audit_logs_server_id_servers"
        ),
        nullable=False,
    )

    event_type: Mapped[str] = mapped_column(String(32), nullable=False)

    actor_user_id: Mapped[int] = mapped_column(
        ForeignKey(
            "users.id", name="fk_server_audit_logs_actor_user_id_users"
        ),
        nullable=False,
    )

    target_user_id: Mapped[int] = mapped_column(
        ForeignKey(
            "users.id", name="fk_server_audit_logs_target_user_id_users"
        ),
        nullable=False,
    )

    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    ban_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Kick/ban snapshots are JSON arrays of assignment and role values as
    # they existed before cleanup. They are never used to restore assignments.
    role_snapshot: Mapped[list | None] = mapped_column(
        JSONB(none_as_null=True), nullable=True
    )
