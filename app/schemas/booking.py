from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class NegocioBase(BaseModel):
    nombre_negocio: str
    telefono_bot: str
    whatsapp_phone_id: str
    google_calendar_id: str
    config_horario: dict[str, list[dict[str, str]]]
    zona_horaria: str = "Europe/Madrid"


class NegocioCreate(NegocioBase):
    pass


class Negocio(NegocioBase):
    id: uuid.UUID

    model_config = ConfigDict(from_attributes=True)


class NegocioUpdate(BaseModel):
    nombre_negocio: str | None = None
    telefono_bot: str | None = None
    whatsapp_phone_id: str | None = None
    google_calendar_id: str | None = None
    config_horario: dict[str, list[dict[str, str]]] | None = None
    zona_horaria: str | None = None


class ServicioBase(BaseModel):
    negocio_id: uuid.UUID
    nombre: str
    duracion_minutos: int = Field(ge=1)


class ServicioCreate(ServicioBase):
    pass


class Servicio(ServicioBase):
    id: uuid.UUID

    model_config = ConfigDict(from_attributes=True)


class ServicioUpdate(BaseModel):
    nombre: str | None = None
    duracion_minutos: int | None = None


class PacienteBase(BaseModel):
    telefono: str
    nombre: str


class PacienteCreate(PacienteBase):
    pass


class Paciente(PacienteBase):
    id: uuid.UUID

    model_config = ConfigDict(from_attributes=True)


class PacienteUpdate(BaseModel):
    nombre: str | None = None


class CitaBase(BaseModel):
    negocio_id: uuid.UUID
    paciente_id: uuid.UUID
    servicio_id: uuid.UUID
    fecha_hora: datetime
    estado: str = "CONFIRMADA"
    calendar_event_id: str = ""
    notas: str | None = None


class CitaCreate(CitaBase):
    pass


class Cita(CitaBase):
    id: uuid.UUID

    model_config = ConfigDict(from_attributes=True)


class CitaUpdate(BaseModel):
    estado: str | None = None
    calendar_event_id: str | None = None
    notas: str | None = None


class HorarioIntervalo(BaseModel):
    inicio: str
    fin: str

