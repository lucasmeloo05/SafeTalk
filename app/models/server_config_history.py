
from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ServerConfigHistory(Base):
    __tablename__ = "server_config_history"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True
    )

    server_id: Mapped[int] = mapped_column(
        ForeignKey("servers.id"),
        nullable=False,
        index=True
    )

    changed_by: Mapped[int] = mapped_column(
        ForeignKey("users.id"),
        nullable=False
    )

    setting_name: Mapped[str] = mapped_column(
        String(100),
        nullable=False
    )

    old_value: Mapped[str | None] = mapped_column(
        Text,
        nullable=True
    )

    new_value: Mapped[str] = mapped_column(
        Text,
        nullable=False
    )

    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False
    )
