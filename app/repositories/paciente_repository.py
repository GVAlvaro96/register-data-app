from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.booking import Paciente
from app.repositories.base_repository import BaseRepository
from app.schemas.booking import PacienteCreate, PacienteUpdate


class PacienteRepository(BaseRepository[Paciente, PacienteCreate, PacienteUpdate]):
    def __init__(self):
        super().__init__(Paciente)

    async def get_by_telefono(self, db: AsyncSession, telefono: str) -> Paciente | None:
        result = await db.execute(select(Paciente).where(Paciente.telefono == telefono))
        return result.scalars().first()


paciente_repository = PacienteRepository()

