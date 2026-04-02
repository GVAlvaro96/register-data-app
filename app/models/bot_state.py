from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from sqlalchemy import DateTime


class BotEstado(Base):
    __tablename__ = "bot_estados"

    telefono: Mapped[str] = mapped_column(String, primary_key=True)
    estado: Mapped[str] = mapped_column(String, nullable=False)

    negocio_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    servicio_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    # Sugerencia actual (para ESPERANDO_FECHA).
    sugerencia_start_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sugerencia_end_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Para ESPERANDO_CANCELACION: lista de ids de citas (en orden mostrado).
    cancelacion_citas_ids: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)

    # Timestamp de last update (útil para depurar).
    actualizado_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )

