from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.booking import Cita
from app.repositories.base_repository import BaseRepository
from app.schemas.booking import CitaCreate, CitaUpdate


class CitaRepository(BaseRepository[Cita, CitaCreate, CitaUpdate]):
    def __init__(self):
        super().__init__(Cita)

    async def list_by_negocio(self, db: AsyncSession, negocio_id):
        result = await db.execute(
            select(Cita).where(Cita.negocio_id == negocio_id).order_by(Cita.fecha_hora)
        )
        return result.scalars().all()

    async def list_actives_by_negocio(self, db: AsyncSession, negocio_id):
        result = await db.execute(
            select(Cita)
            .where(Cita.negocio_id == negocio_id)
            .where(Cita.estado != "CANCELADA")
            .order_by(Cita.fecha_hora)
        )
        return result.scalars().all()

    async def list_actives_by_paciente(self, db: AsyncSession, paciente_id):
        result = await db.execute(
            select(Cita).where(Cita.paciente_id == paciente_id).where(Cita.estado != "CANCELADA")
        )
        return result.scalars().all()

    async def cancelar_cita(self, db: AsyncSession, cita_id):
        # Importante: la cancelación es un cambio de estado (no un borrado),
        # porque la bot necesita historial/consistencia.
        await db.execute(
            update(Cita).where(Cita.id == cita_id).values(estado="CANCELADA")
        )
        await db.flush()


cita_repository = CitaRepository()

