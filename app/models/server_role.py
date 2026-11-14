
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ServerRole(Base):
    __tablename__ = "server_roles"

    __table_args__ = (
        CheckConstraint(
            "position >= 1",
            name="ck_server_roles_position_positive",
        ),
        UniqueConstraint(
            "server_id",
            "name",
            name="uq_server_roles_server_name"
        ),
        UniqueConstraint(
            "id",
            "server_id",
            name="uq_server_roles_id_server"
        ),
        Index(
            "uq_server_roles_one_default",
            "server_id",
            unique=True,
            postgresql_where=text("is_default = true")
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
        String(50),
        nullable=False
    )

    description: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True
    )

    permissions: Mapped[dict] = mapped_column(
        JSONB,
        default=dict,
        nullable=False
    )

    position: Mapped[int] = mapped_column(
        Integer,
        nullable=False
    )

    is_default: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False
    )

    is_system_role: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default=text("false"),
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False
    )
