from __future__ import annotations

import uuid
from datetime import datetime, timedelta, time as dtime
from typing import Any

import pytz
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.core.google_calendar import get_google_calendar_client
from app.models.booking import Negocio, Cita
from app.models.empleado import Empleado

class SlotSuggestion(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    start_local: datetime
    end_local: datetime
    start_utc: datetime
    end_utc: datetime

class SlotFinder:
    USER_TIMEZONE = pytz.timezone("Europe/Madrid")

    def __init__(self):
        self._google = None

    def _get_google_client(self):
        if self._google is None:
            self._google = get_google_calendar_client()
        return self._google

    @staticmethod
    def _round_up_to_half_hour(dt_local: datetime) -> datetime:
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
        return str(dt_local.weekday())

    @staticmethod
    def _fits_in_config_horario(
        negocio: Negocio, candidate_start_local: datetime, candidate_end_local: datetime
    ) -> bool:
        tz = pytz.timezone(negocio.zona_horaria or "Europe/Madrid")
        weekday_key = SlotFinder._weekday_key(candidate_start_local)
        intervals: list[dict[str, Any]] = (negocio.config_horario or {}).get(weekday_key) or []
        fecha_solicitada = candidate_start_local.date()

        for interval in intervals:
            inicio = interval.get("inicio")
            fin = interval.get("fin")
            if not inicio or not fin:
                continue

            dt_apertura = SlotFinder._make_local_dt(fecha_solicitada, inicio, tz=tz)
            dt_cierre = SlotFinder._make_local_dt(fecha_solicitada, fin, tz=tz)

            if candidate_start_local >= dt_apertura and candidate_end_local <= dt_cierre:
                return True
        return False

    async def _is_free_in_google(
        self,
        negocio: Negocio,
        slot_start_utc: datetime,
        slot_end_utc: datetime,
        num_citas_db: int = 0
    ) -> bool:
        _ = self._get_google_client()
        time_min = slot_start_utc + timedelta(minutes=1)
        time_max = slot_end_utc - timedelta(minutes=1)

        events = await self._google.list_events_between(
            calendar_id=negocio.google_calendar_id,
            time_min=time_min,
            time_max=time_max,
        )
        
        # Si hay más eventos en Google que en nuestra DB, es un bloqueo manual del jefe
        if len(events) > num_citas_db:
            print(f"❌ [LOG] Bloqueo manual detectado en Google ({len(events)} eventos vs {num_citas_db} en DB).")
            return False
            
        return True

    async def _check_db_concurrency(
        self,
        db: AsyncSession,
        negocio: Negocio,
        candidate_utc: datetime,
        empleado_id: uuid.UUID | None
    ) -> tuple[bool, int]:
        # 1. Total peluqueros activos
        res_empleados = await db.execute(
            select(func.count()).where(Empleado.negocio_id == negocio.id, Empleado.activo == True)
        )
        total_peluqueros = res_empleados.scalar() or 1

        # 2. Buscar TODAS las citas confirmadas en ESA hora exacta
        res_citas = await db.execute(
            select(Cita).where(
                Cita.negocio_id == negocio.id,
                Cita.fecha_hora == candidate_utc,
                Cita.estado == "CONFIRMADA"
            )
        )
        citas_en_esa_hora = res_citas.scalars().all()
        num_citas_db = len(citas_en_esa_hora)

        # --- LÓGICA BLINDADA DE CONCURRENCIA ---
        
        # REGLA 1 (Aforo físico): Si ya hay tantas citas como peluqueros, el local está lleno.
        # ¡Esto aplica SIEMPRE, elija el cliente a quien elija!
        if num_citas_db >= total_peluqueros:
            print(f"❌ [LOG] Hueco ocupado: Las {total_peluqueros} sillas están ocupadas a las {candidate_utc.strftime('%H:%M')} UTC")
            return False, num_citas_db

        # REGLA 2 (Disponibilidad individual): Si el cliente quiere a un peluquero en concreto,
        # comprobamos que ese peluquero específico no tenga ya una cita asignada.
        if empleado_id:
            peluquero_ocupado = any(cita.empleado_id == empleado_id for cita in citas_en_esa_hora)
            if peluquero_ocupado:
                print(f"❌ [LOG] Hueco ocupado: El peluquero elegido ya tiene cita a las {candidate_utc.strftime('%H:%M')} UTC")
                return False, num_citas_db
                
        return True, num_citas_db

    async def find_next_available_slot(
        self,
        db: AsyncSession,
        negocio: Negocio,
        servicio_duracion_minutos: int,
        start_local_dt: datetime,
        empleado_id: uuid.UUID | None = None,
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

            day_end = tz.localize(datetime.combine(day, datetime.max.time()))

            while candidate <= day_end:
                candidate_end = candidate + timedelta(minutes=servicio_duracion_minutos)

                if self._fits_in_config_horario(negocio, candidate, candidate_end):
                    slot_start_utc = candidate.astimezone(pytz.UTC)
                    slot_end_utc = candidate_end.astimezone(pytz.UTC)

                    # 1º Comprobamos Base de Datos (Anti-Solapamientos)
                    is_free_in_db, num_citas_db = await self._check_db_concurrency(db, negocio, slot_start_utc, empleado_id)
                    
                    if is_free_in_db:
                        # 2º Comprobamos Google Calendar
                        if await self._is_free_in_google(
                            negocio, slot_start_utc=slot_start_utc, slot_end_utc=slot_end_utc, num_citas_db=num_citas_db
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
        db: AsyncSession,
        negocio: Negocio,
        servicio_duracion_minutos: int,
        candidate_start_local: datetime,
        empleado_id: uuid.UUID | None = None
    ) -> SlotSuggestion | None:
        tz = pytz.timezone(negocio.zona_horaria or "Europe/Madrid")
        candidate_start_local = candidate_start_local.astimezone(tz)

        # --- ESCUDO ANTI-VIAJES EN EL TIEMPO ---
        # Comparamos la hora que pide con la hora actual (en la zona horaria del negocio)
        now_local = datetime.utcnow().replace(tzinfo=pytz.UTC).astimezone(tz)
        if candidate_start_local < now_local:
            print(f"❌ [LOG] Hueco rechazado: La hora pedida ({candidate_start_local.strftime('%H:%M')}) ya ha pasado.")
            return None

        candidate_end_local = candidate_start_local + timedelta(minutes=servicio_duracion_minutos)

        if not self._fits_in_config_horario(negocio, candidate_start_local, candidate_end_local):
            return None

        slot_start_utc = candidate_start_local.astimezone(pytz.UTC)
        slot_end_utc = candidate_end_local.astimezone(pytz.UTC)

        # Comprobamos Base de Datos
        is_free_in_db, num_citas_db = await self._check_db_concurrency(db, negocio, slot_start_utc, empleado_id)
        if not is_free_in_db:
            return None

        if await self._is_free_in_google(
            negocio, slot_start_utc=slot_start_utc, slot_end_utc=slot_end_utc, num_citas_db=num_citas_db
        ):
            return SlotSuggestion(
                start_local=candidate_start_local,
                end_local=candidate_end_local,
                start_utc=slot_start_utc,
                end_utc=slot_end_utc,
            )

        print("❌ [LOG] Hueco bloqueado directamente en Google Calendar.")
        return None

    @staticmethod
    def to_user_local(dt: datetime) -> datetime:
        return dt.astimezone(SlotFinder.USER_TIMEZONE)