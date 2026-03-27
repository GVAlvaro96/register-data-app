from pydantic import BaseModel, ConfigDict
from typing import Optional
from uuid import UUID

class ServicioCreate(BaseModel):
    negocio_id: UUID
    nombre: str
    duracion_minutos: int = 60
    precio: Optional[float] = None
    activo: bool = True

class ServicioResponse(ServicioCreate):
    id: UUID

    # Permite a Pydantic leer los datos directamente de los modelos de SQLAlchemy
    model_config = ConfigDict(from_attributes=True)