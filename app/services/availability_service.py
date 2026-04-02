from __future__ import annotations

from datetime import datetime
import uuid

import pytz
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.booking import Negocio, Servicio
from app.repositories.negocio_repository import negocio_repository
from app.repositories.servicio_repository import servicio_repository
from app.services.slot_finder import SlotFinder, SlotSuggestion


class AvailabilityService:
    def __init__(self, slot_finder: SlotFinder | None = None):
        self._slot_finder = slot_finder or SlotFinder()

    async def sugerir_siguiente_hueco(
        self,
        db: AsyncSession,
        negocio_id: uuid.UUID,
        servicio_id: uuid.UUID,
        *,
        from_local_dt: datetime | None = None,
    ) -> SlotSuggestion | None:
        negocio: Negocio | None = await negocio_repository.get(db, negocio_id)
        if not negocio:
            return None

        servicio: Servicio | None = await servicio_repository.get(db, servicio_id)
        if not servicio or servicio.negocio_id != negocio.id:
            return None

        tz = pytz.timezone(negocio.zona_horaria or "Europe/Madrid")

        if from_local_dt is None:
            start_local_dt = datetime.now(tz)
        else:
            # Se asume que `from_local_dt` es timezone-aware.
            start_local_dt = from_local_dt.astimezone(tz)

        return await self._slot_finder.find_next_available_slot(
            negocio=negocio,
            servicio_duracion_minutos=servicio.duracion_minutos,
            start_local_dt=start_local_dt,
        )


availability_service = AvailabilityService()

