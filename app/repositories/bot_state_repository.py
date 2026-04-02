from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.bot_state import BotEstado


class BotEstadoRepository:
    async def get_by_telefono(self, db: AsyncSession, telefono: str) -> BotEstado | None:
        result = await db.execute(select(BotEstado).where(BotEstado.telefono == telefono))
        return result.scalars().first()

    async def upsert(
        self,
        db: AsyncSession,
        *,
        telefono: str,
        defaults: dict,
    ) -> BotEstado:
        existing = await self.get_by_telefono(db, telefono)
        if existing is None:
            estado = BotEstado(telefono=telefono, **defaults)
            db.add(estado)
            await db.flush()
            await db.refresh(estado)
            return estado

        for k, v in defaults.items():
            setattr(existing, k, v)
        await db.flush()
        await db.refresh(existing)
        return existing


bot_estado_repository = BotEstadoRepository()

