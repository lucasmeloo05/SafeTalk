
from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ServerMemberRole(Base):
    __tablename__ = "server_member_roles"

    __table_args__ = (
        UniqueConstraint(
            "member_id",
            "role_id",
            name="uq_server_member_roles_member_role"
        ),
        ForeignKeyConstraint(
            ["member_id", "server_id"],
            ["server_members.id", "server_members.server_id"],
            name="fk_member_role_member_server"
        ),
        ForeignKeyConstraint(
            ["role_id", "server_id"],
            ["server_roles.id", "server_roles.server_id"],
            name="fk_member_role_role_server"
        ),
    )

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True
    )

    member_id: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        index=True
    )

    role_id: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        index=True
    )

    server_id: Mapped[int] = mapped_column(
        Integer,
        nullable=False
    )

    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False
    )

    assigned_by: Mapped[int] = mapped_column(
        ForeignKey("users.id"),
        nullable=False
    )
