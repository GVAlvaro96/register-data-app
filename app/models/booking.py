from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.core.database import Base


class Negocio(Base):
    __tablename__ = "negocios"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    nombre_negocio: Mapped[str] = mapped_column(String, nullable=False)
    telefono_bot: Mapped[str] = mapped_column(String, nullable=False)
    whatsapp_phone_id: Mapped[str] = mapped_column(String, nullable=False, server_default="")
    google_calendar_id: Mapped[str] = mapped_column(String, nullable=False)

    # JSONB MUY IMPORTANTE: formato {"0": [{"inicio": "09:00", "fin": "14:00"}]}
    config_horario: Mapped[dict] = mapped_column(JSONB, nullable=False)
    zona_horaria: Mapped[str] = mapped_column(
        String, nullable=False, default="Europe/Madrid", server_default="Europe/Madrid"
    )

    servicios: Mapped[list[Servicio]] = relationship("Servicio", back_populates="negocio", lazy="selectin")
    citas: Mapped[list[Cita]] = relationship("Cita", back_populates="negocio", lazy="selectin")


class Servicio(Base):
    __tablename__ = "servicios"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    negocio_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("negocios.id", ondelete="CASCADE"), nullable=False
    )
    nombre: Mapped[str] = mapped_column(String, nullable=False)
    duracion_minutos: Mapped[int] = mapped_column(Integer, nullable=False)

    negocio: Mapped[Negocio] = relationship("Negocio", back_populates="servicios", lazy="selectin")


class Paciente(Base):
    __tablename__ = "pacientes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    telefono: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    nombre: Mapped[str] = mapped_column(String, nullable=False)


class Cita(Base):
    __tablename__ = "citas"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    negocio_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("negocios.id", ondelete="CASCADE"), nullable=False
    )
    paciente_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pacientes.id", ondelete="CASCADE"), nullable=False
    )
    servicio_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("servicios.id", ondelete="CASCADE"), nullable=False
    )

    # timestamptz (UTC). Guardamos TODO en UTC (regla B).
    fecha_hora: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    estado: Mapped[str] = mapped_column(String, nullable=False, default="CONFIRMADA", server_default="CONFIRMADA")

    calendar_event_id: Mapped[str] = mapped_column(String, nullable=False, default="", server_default="")
    notas: Mapped[str | None] = mapped_column(Text, nullable=True)

    negocio: Mapped[Negocio] = relationship("Negocio", back_populates="citas", lazy="selectin")

    __table_args__ = (
        UniqueConstraint("negocio_id", "fecha_hora", name="uq_citas_negocio_fecha_hora"),
    )

