import uuid
from sqlalchemy import (
    Column, 
    String, 
    Integer, 
    Boolean, 
    DateTime, 
    ForeignKey, 
    Text, 
    Numeric, 
    Uuid, 
    UniqueConstraint,
    Float,
    JSON
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from src.db.database import Base

# En src/db/models.py
class Negocio(Base):
    __tablename__ = "negocios"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    nombre_negocio = Column(String(100), nullable=False)
    telefono_bot = Column(String(20), unique=True, nullable=True) 
    google_calendar_id = Column(String(255), nullable=True)
    zona_horaria = Column(String(50), default="Europe/Madrid")
    config_horario = Column(JSON, nullable=True)
    google_refresh_token = Column(Text, nullable=True)
    plan_suscripcion = Column(String(20), default="FREE")
    creado_en = Column(DateTime(timezone=True), server_default=func.now())

    # Relaciones: Un negocio tiene muchos servicios, pacientes y citas
    servicios = relationship("Servicio", back_populates="negocio", cascade="all, delete-orphan")
    pacientes = relationship("Paciente", back_populates="negocio", cascade="all, delete-orphan")
    citas = relationship("Cita", back_populates="negocio", cascade="all, delete-orphan")


class Servicio(Base):
    __tablename__ = "servicios"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    negocio_id = Column(Uuid, ForeignKey("negocios.id", ondelete="CASCADE"), nullable=False)
    nombre = Column(String(100), nullable=False)
    duracion_minutos = Column(Integer, nullable=False, default=60)
    precio = Column(Numeric(10, 2), nullable=True)
    activo = Column(Boolean, default=True)

    negocio = relationship("Negocio", back_populates="servicios")
    citas = relationship("Cita", back_populates="servicio")


class Paciente(Base):
    __tablename__ = "pacientes"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    negocio_id = Column(Uuid, ForeignKey("negocios.id", ondelete="CASCADE"), nullable=False)
    telefono = Column(String(20), nullable=False)
    nombre = Column(String(100), nullable=True)

    __table_args__ = (UniqueConstraint('negocio_id', 'telefono', name='uix_negocio_telefono'),)

    negocio = relationship("Negocio", back_populates="pacientes")
    citas = relationship("Cita", back_populates="paciente", cascade="all, delete-orphan")


class Cita(Base):
    __tablename__ = "citas"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    negocio_id = Column(Uuid, ForeignKey("negocios.id", ondelete="CASCADE"), nullable=False)
    paciente_id = Column(Uuid, ForeignKey("pacientes.id", ondelete="CASCADE"), nullable=False)
    servicio_id = Column(Uuid, ForeignKey("servicios.id", ondelete="RESTRICT"), nullable=False)
    fecha_hora = Column(DateTime(timezone=True), nullable=False)
    google_event_id = Column(String(255), nullable=True)
    estado = Column(String(20), default="PENDIENTE")
    calendar_event_id = Column(String(255), nullable=True)
    notas = Column(Text, nullable=True)
    creado_en = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (UniqueConstraint('negocio_id', 'fecha_hora', name='uix_negocio_fechahora'),)

    negocio = relationship("Negocio", back_populates="citas")
    paciente = relationship("Paciente", back_populates="citas")
    servicio = relationship("Servicio", back_populates="citas")