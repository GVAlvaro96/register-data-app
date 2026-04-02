from __future__ import annotations

from datetime import datetime, timedelta, time as dtime
from typing import Any

import pytz
from pydantic import BaseModel, ConfigDict, Field

from app.core.google_calendar import get_google_calendar_client
from app.models.booking import Negocio


class SlotSuggestion(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    start_local: datetime
    end_local: datetime
    start_utc: datetime
    end_utc: datetime


class SlotFinder:
    USER_TIMEZONE = pytz.timezone("Europe/Madrid")

    def __init__(self):
        # Lazy: no creamos el cliente de Google aquí para no romper el arranque
        # si faltan variables (p.ej. en dev).
        self._google = None

    def _get_google_client(self):
        if self._google is None:
            self._google = get_google_calendar_client()
        return self._google
    @staticmethod
    def _round_up_to_half_hour(dt_local: datetime) -> datetime:
        # Normaliza segundos/microsegundos.
        dt_local = dt_local.replace(second=0, microsecond=0)
        minutes = dt_local.minute
        remainder = minutes % 30
        if remainder == 0:
            return dt_local
        add = 30 - remainder
        return dt_local + timedelta(minutes=add)

    @staticmethod
    def round_up_to_half_hour(dt_local: datetime) -> datetime:
        return SlotFinder._round_up_to_half_hour(dt_local)

    @staticmethod
    def _parse_hhmm(value: str) -> dtime:
        hh, mm = value.split(":")
        return dtime(hour=int(hh), minute=int(mm))

    @staticmethod
    def _make_local_dt(date_: datetime.date, hhmm: str, tz: pytz.BaseTzInfo) -> datetime:
        t = SlotFinder._parse_hhmm(hhmm)
        naive = datetime.combine(date_, t)
        return tz.localize(naive)

    @staticmethod
    def _weekday_key(dt_local: datetime) -> str:
        # lunes=0 ... domingo=6 (regla acordada contigo).
        return str(dt_local.weekday())

    @staticmethod
    def _fits_in_config_horario(
        negocio: Negocio, candidate_start_local: datetime, candidate_end_local: datetime
    ) -> bool:
        tz = pytz.timezone(negocio.zona_horaria or "Europe/Madrid")
        # Aseguramos que las comparaciones sean datetimes exactos (regla A).
        weekday_key = SlotFinder._weekday_key(candidate_start_local)
        intervals: list[dict[str, Any]] = (negocio.config_horario or {}).get(weekday_key) or []
        fecha_solicitada = candidate_start_local.date()

        for interval in intervals:
            inicio = interval.get("inicio")
            fin = interval.get("fin")
            if not inicio or not fin:
                continue

            dt_apertura = SlotFinder._make_local_dt(
                fecha_solicitada, inicio, tz=tz
            )
            dt_cierre = SlotFinder._make_local_dt(
                fecha_solicitada, fin, tz=tz
            )

            # Regla A: nunca comparar objetos `time`; comparar datetimes completos.
            if candidate_start_local >= dt_apertura and candidate_end_local <= dt_cierre:
                return True
        return False

    async def _is_free_in_google(
        self,
        negocio: Negocio,
        slot_start_utc: datetime,
        slot_end_utc: datetime,
    ) -> bool:
        _ = self._get_google_client()
        # Regla B: añade 1 minuto al inicio y resta 1 al final (timeMin/timeMax).
        time_min = slot_start_utc + timedelta(minutes=1)
        time_max = slot_end_utc - timedelta(minutes=1)

        events = await self._google.list_events_between(
            calendar_id=negocio.google_calendar_id,
            time_min=time_min,
            time_max=time_max,
        )
        # Asumimos que cualquier evento devuelto ocupa el bloque.
        return len(events) == 0

    async def find_next_available_slot(
        self,
        negocio: Negocio,
        servicio_duracion_minutos: int,
        start_local_dt: datetime,
        *,
        max_days: int = 30,
    ) -> SlotSuggestion | None:
        if servicio_duracion_minutos <= 0:
            return None

        tz = pytz.timezone(negocio.zona_horaria or "Europe/Madrid")
        start_local_dt = start_local_dt.astimezone(tz)
        current = self._round_up_to_half_hour(start_local_dt)

        for day_offset in range(0, max_days + 1):
            day = current.date() + timedelta(days=day_offset)
            if day_offset == 0:
                candidate = current
            else:
                candidate = tz.localize(datetime.combine(day, datetime.min.time()))
                candidate = self._round_up_to_half_hour(candidate)

            # Exploramos hasta el final del día local.
            day_end = tz.localize(datetime.combine(day, datetime.max.time()))

            while candidate <= day_end:
                candidate_end = candidate + timedelta(minutes=servicio_duracion_minutos)

                # Validación dentro de config_horario (regla A).
                if self._fits_in_config_horario(negocio, candidate, candidate_end):
                    slot_start_utc = candidate.astimezone(pytz.UTC)
                    slot_end_utc = candidate_end.astimezone(pytz.UTC)

                    # Google (regla B) para detectar colisiones.
                    if await self._is_free_in_google(
                        negocio, slot_start_utc=slot_start_utc, slot_end_utc=slot_end_utc
                    ):
                        return SlotSuggestion(
                            start_local=candidate,
                            end_local=candidate_end,
                            start_utc=slot_start_utc,
                            end_utc=slot_end_utc,
                        )

                candidate = candidate + timedelta(minutes=30)

        return None

    async def validate_slot_exact(
        self,
        *,
        negocio: Negocio,
        servicio_duracion_minutos: int,
        candidate_start_local: datetime,
    ) -> SlotSuggestion | None:
        """
        Valida estrictamente un bloque que empieza exactamente en `candidate_start_local`
        y dura `servicio_duracion_minutos`, sin buscar “el siguiente”.
        """
        tz = pytz.timezone(negocio.zona_horaria or "Europe/Madrid")
        candidate_start_local = candidate_start_local.astimezone(tz)
        candidate_end_local = candidate_start_local + timedelta(minutes=servicio_duracion_minutos)

        if not self._fits_in_config_horario(negocio, candidate_start_local, candidate_end_local):
            return None

        slot_start_utc = candidate_start_local.astimezone(pytz.UTC)
        slot_end_utc = candidate_end_local.astimezone(pytz.UTC)

        if await self._is_free_in_google(
            negocio, slot_start_utc=slot_start_utc, slot_end_utc=slot_end_utc
        ):
            return SlotSuggestion(
                start_local=candidate_start_local,
                end_local=candidate_end_local,
                start_utc=slot_start_utc,
                end_utc=slot_end_utc,
            )

        return None

    @staticmethod
    def to_user_local(dt: datetime) -> datetime:
        # Regla B: cuando se muestre al usuario, convertir a Europe/Madrid.
        return dt.astimezone(SlotFinder.USER_TIMEZONE)

