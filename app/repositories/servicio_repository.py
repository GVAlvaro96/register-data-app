from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.booking import Servicio
from app.repositories.base_repository import BaseRepository
from app.schemas.booking import ServicioCreate, ServicioUpdate, Servicio as ServicioSchema


class ServicioRepository(BaseRepository[Servicio, ServicioCreate, ServicioUpdate]):
    def __init__(self):
        super().__init__(Servicio)

    async def list_by_negocio(self, db: AsyncSession, negocio_id):
        result = await db.execute(
            select(Servicio).where(Servicio.negocio_id == negocio_id).order_by(Servicio.nombre)
        )
        return result.scalars().all()


servicio_repository = ServicioRepository()

