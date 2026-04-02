from __future__ import annotations

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.booking import Negocio
from app.repositories.base_repository import BaseRepository
from app.schemas.booking import NegocioCreate, NegocioUpdate
from app.utils.phone_utils import normalize_phone_number


class NegocioRepository(BaseRepository[Negocio, NegocioCreate, NegocioUpdate]):
    def __init__(self):
        super().__init__(Negocio)

    async def get_by_google_calendar_id(
        self, db: AsyncSession, google_calendar_id: str
    ) -> Negocio | None:
        result = await db.execute(
            select(Negocio).where(Negocio.google_calendar_id == google_calendar_id)
        )
        return result.scalars().first()

    async def get_by_telefono_bot(self, db: AsyncSession, telefono_bot: str) -> Negocio | None:
        normalized = normalize_phone_number(telefono_bot)
        result = await db.execute(
            select(Negocio).where(
                func.regexp_replace(Negocio.telefono_bot, r"[^0-9]", "", "g")
                == normalized
            )
        )
        return result.scalars().first()

    async def get_by_display_phone_number(
        self, db: AsyncSession, display_phone_number: str
    ) -> Negocio | None:
        # WEBHOOK ruteo por display_phone_number (tenant dinámico).
        return await self.get_by_telefono_bot(db, display_phone_number)


negocio_repository = NegocioRepository()

