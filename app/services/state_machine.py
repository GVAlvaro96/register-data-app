from __future__ import annotations

import uuid
import pytz
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.google_calendar import get_google_calendar_client
from app.models.bot_state import BotEstado
from app.models.booking import Cita, Negocio, Servicio
from app.repositories.bot_state_repository import bot_estado_repository
from app.repositories.cita_repository import cita_repository
from app.repositories.negocio_repository import negocio_repository
from app.repositories.paciente_repository import paciente_repository
from app.repositories.servicio_repository import servicio_repository
from app.services.availability_service import availability_service
from app.services.slot_finder import SlotFinder, SlotSuggestion
from app.utils.dateparser_utils import parse_user_datetime


class WhatsAppStateMachine:
    def __init__(self):
        self._google = get_google_calendar_client()
        self._slot_finder = SlotFinder()

    @staticmethod
    def _norm(text: str) -> str:
        return " ".join((text or "").strip().lower().split())

    @staticmethod
    def _is_affirmative(text: str) -> bool:
        t = WhatsAppStateMachine._norm(text)
        return t in {"si", "sí", "confirmar", "confirmo", "ok", "vale", "confirmado"}

    @staticmethod
    def _try_parse_index(text: str) -> int | None:
        t = WhatsAppStateMachine._norm(text)
        try:
            return int(t)
        except ValueError:
            return None

    async def _get_or_create_state(self, db: AsyncSession, telefono_sender: str) -> BotEstado:
        existing = await bot_estado_repository.get_by_telefono(db, telefono_sender)
        if existing:
            return existing

        # Estado por defecto.
        return await bot_estado_repository.upsert(
            db, telefono=telefono_sender, defaults={"estado": "None"}
        )

    async def _load_negocio(self, db: AsyncSession, negocio_id: str) -> Negocio | None:
        return await negocio_repository.get(db, negocio_id)

    async def process_message(
        self,
        db: AsyncSession,
        *,
        telefono_sender: str,
        texto_mensaje: str,
        negocio_id: uuid.UUID,
        paciente_nombre: str | None = None,
        # Permite testear con una hora fija.
        now_utc: datetime | None = None,
    ) -> dict[str, Any]:
        """
        Devuelve { "reply_text": str, "next_estado": str }.
        La integración WhatsApp se hace en Fase 4.
        """
        negocio = await self._load_negocio(db, negocio_id)
        if not negocio:
            return {"reply_text": "Negocio no configurado.", "next_estado": "None"}

        tz = pytz.timezone(negocio.zona_horaria or "Europe/Madrid")
        now_utc = now_utc or datetime.utcnow().replace(tzinfo=pytz.UTC)
        now_local = now_utc.astimezone(tz)

        state = await self._get_or_create_state(db, telefono_sender)
        estado_actual = state.estado
        t_norm = self._norm(texto_mensaje)

        # Respuestas base (estado None).
        if estado_actual == "None":
            if "reservar" in t_norm:
                servicios = await servicio_repository.list_by_negocio(db, negocio.id)
                if not servicios:
                    return {"reply_text": "No hay servicios disponibles ahora.", "next_estado": "None"}

                await bot_estado_repository.upsert(
                    db,
                    telefono=telefono_sender,
                    defaults={
                        "estado": "ESPERANDO_SERVICIO",
                        "negocio_id": negocio.id,
                        "servicio_id": None,
                        "sugerencia_start_utc": None,
                        "sugerencia_end_utc": None,
                        "cancelacion_citas_ids": None,
                    },
                )

                menu = "\n".join([f"{i+1}. {s.nombre} ({s.duracion_minutos} min)" for i, s in enumerate(servicios)])
                return {"reply_text": f"¿Qué servicio deseas?\n{menu}", "next_estado": "ESPERANDO_SERVICIO"}

            if "cancelar" in t_norm:
                citas_actives = await cita_repository.list_actives_by_negocio(db, negocio.id)
                citas_actives = [c for c in citas_actives if c.calendar_event_id]
                if not citas_actives:
                    await bot_estado_repository.upsert(
                        db,
                        telefono=telefono_sender,
                        defaults={"estado": "None", "cancelacion_citas_ids": None},
                    )
                    return {"reply_text": "No tienes citas activas para cancelar.", "next_estado": "None"}

                # Guardamos el mapeo index -> cita_id.
                citas_ids = [str(c.id) for c in citas_actives]
                await bot_estado_repository.upsert(
                    db,
                    telefono=telefono_sender,
                    defaults={
                        "estado": "ESPERANDO_CANCELACION",
                        "negocio_id": negocio.id,
                        "servicio_id": None,
                        "cancelacion_citas_ids": citas_ids,
                    },
                )

                # Regla B: mostrar usando Europe/Madrid.
                madrid_tz = pytz.timezone("Europe/Madrid")
                lista = "\n".join(
                    [
                        f"{i+1}. {c.fecha_hora.astimezone(madrid_tz).strftime('%d/%m/%Y %H:%M')}"
                        for i, c in enumerate(citas_actives)
                    ]
                )
                return {"reply_text": f"Selecciona la cita a cancelar:\n{lista}\nResponde con el número.", "next_estado": "ESPERANDO_CANCELACION"}

            # Hola o fallback
            if "hola" in t_norm or "buen" in t_norm or "hey" in t_norm:
                return {f"reply_text": f"Hola {paciente_nombre}. Escribe 'Reservar' para agendar o 'Cancelar' para cancelar.", "next_estado": "None"}

            return {"reply_text": "Escribe 'Reservar' o 'Cancelar'.", "next_estado": "None"}

        # Estado: esperando servicio
        if estado_actual == "ESPERANDO_SERVICIO":
            idx = self._try_parse_index(t_norm)
            if idx is None or idx <= 0:
                return {"reply_text": "Selecciona un número de servicio (por ejemplo: 1).", "next_estado": "ESPERANDO_SERVICIO"}

            servicios = await servicio_repository.list_by_negocio(db, negocio.id)
            if idx > len(servicios):
                return {"reply_text": "Número de servicio inválido. Intenta de nuevo.", "next_estado": "ESPERANDO_SERVICIO"}

            servicio = servicios[idx - 1]
            # Entramos en ESPERANDO_FECHA y sugerimos automáticamente siguiente hueco libre.
            sugerencia = await availability_service.sugerir_siguiente_hueco(
                db,
                negocio_id=negocio.id,
                servicio_id=servicio.id,
                from_local_dt=now_local,
            )
            if not sugerencia:
                return {"reply_text": "No encontré huecos disponibles para este servicio en el futuro cercano.", "next_estado": "ESPERANDO_SERVICIO"}

            await bot_estado_repository.upsert(
                db,
                telefono=telefono_sender,
                defaults={
                    "estado": "ESPERANDO_FECHA",
                    "negocio_id": negocio.id,
                    "servicio_id": servicio.id,
                    "sugerencia_start_utc": sugerencia.start_utc,
                    "sugerencia_end_utc": sugerencia.end_utc,
                    "cancelacion_citas_ids": None,
                },
            )

            madrid_tz = pytz.timezone("Europe/Madrid")
            start_local_madrid = sugerencia.start_utc.astimezone(madrid_tz)
            end_local_madrid = sugerencia.end_utc.astimezone(madrid_tz)
            return {
                "reply_text": (
                    f"Te propongo este hueco: {start_local_madrid.strftime('%d/%m/%Y %H:%M')} "
                    f"({start_local_madrid.strftime('%H:%M')}-{end_local_madrid.strftime('%H:%M')}). "
                    "Responde 'Sí' para confirmar o escribe otra fecha (ej: 'el lunes a las 16:00')."
                ),
                "next_estado": "ESPERANDO_FECHA",
            }

        # Estado: esperando fecha (sugerencia o validación de otra)
        if estado_actual == "ESPERANDO_FECHA":
            sugerencia: SlotSuggestion | None = None
            servicio_id = state.servicio_id
            if not servicio_id:
                return {"reply_text": "Vuelve a empezar: escribe 'Reservar'.", "next_estado": "None"}

            servicio = await servicio_repository.get(db, servicio_id)
            if not servicio:
                return {"reply_text": "Servicio no encontrado. Vuelve a empezar: escribe 'Reservar'.", "next_estado": "None"}

            # 1) Confirmación
            if self._is_affirmative(texto_mensaje):
                if not state.sugerencia_start_utc or not state.sugerencia_end_utc:
                    return {"reply_text": "No tengo un hueco sugerido activo. Escribe otra vez 'Reservar'.", "next_estado": "None"}

                # Crear evento en Google + persistir Cita (Fase 3 ya integra el calendario en backend).
                try:
                    summary = f"Cita - {servicio.nombre}"
                    event_id = await self._google.create_event(
                        str(negocio.google_calendar_id),
                        start_utc=state.sugerencia_start_utc,
                        end_utc=state.sugerencia_end_utc,
                        summary=summary,
                        description=f"Reservas WhatsApp SaaS. Tel: {telefono_sender}",
                    )
                except Exception:
                    await db.rollback()
                    return {"reply_text": "Ha ocurrido un error al crear el evento. Prueba de nuevo.", "next_estado": "ESPERANDO_FECHA"}

                # Crear / obtener paciente
                paciente_nombre_final = paciente_nombre or "Paciente"
                paciente = await paciente_repository.get_by_telefono(db, telefono_sender)
                if not paciente:
                    # Reutilizamos BaseRepository.create vía create con esquema.
                    from app.schemas.booking import PacienteCreate

                    try:
                        paciente = await paciente_repository.create(
                            db,
                            PacienteCreate(
                                telefono=telefono_sender, nombre=paciente_nombre_final
                            ),
                        )
                    except Exception:
                        # Si el paciente ya existía por carrera concurrente,
                        # dejamos la sesión sana y reintentamos lectura.
                        await db.rollback()
                        paciente = await paciente_repository.get_by_telefono(db, telefono_sender)

                # Guardar cita
                from app.schemas.booking import CitaCreate

                try:
                    cita = await cita_repository.create(
                        db,
                        CitaCreate(
                            negocio_id=negocio.id,
                            paciente_id=paciente.id,
                            servicio_id=servicio.id,
                            fecha_hora=state.sugerencia_start_utc,
                            estado="CONFIRMADA",
                            calendar_event_id=event_id,
                            notas=None,
                        ),
                    )
                except Exception:
                    await db.rollback()
                    # Si falla por uniqueness, revertimos borrando el evento que ya creamos.
                    try:
                        await self._google.delete_event(str(negocio.google_calendar_id), event_id)
                    except Exception:
                        pass
                    return {"reply_text": "Ese hueco ya no está disponible. Te propongo otro.", "next_estado": "ESPERANDO_FECHA"}

                await bot_estado_repository.upsert(
                    db,
                    telefono=telefono_sender,
                    defaults={
                        "estado": "None",
                        "servicio_id": None,
                        "sugerencia_start_utc": None,
                        "sugerencia_end_utc": None,
                        "cancelacion_citas_ids": None,
                    },
                )

                madrid_tz = pytz.timezone("Europe/Madrid")
                start_local_madrid = cita.fecha_hora.astimezone(madrid_tz)
                end_local_madrid = (cita.fecha_hora + timedelta(minutes=servicio.duracion_minutos)).astimezone(madrid_tz)
                return {
                    "reply_text": (
                        f"Reserva confirmada para {start_local_madrid.strftime('%d/%m/%Y %H:%M')} "
                        f"({start_local_madrid.strftime('%H:%M')}-{end_local_madrid.strftime('%H:%M')})."
                    ),
                    "next_estado": "None",
                }

            # 2) Interpretar como otra fecha
            dt_parsed = parse_user_datetime(
                texto_mensaje,
                tz=tz,
                now_local=now_local,
            )
            if not dt_parsed:
                return {"reply_text": "No pude interpretar la fecha. Ejemplo: 'el lunes a las 16:00'.", "next_estado": "ESPERANDO_FECHA"}

            # Alineamos a bloque (30 min) para coherencia con slots.
            dt_parsed = self._slot_finder.round_up_to_half_hour(dt_parsed)

            # Validar exactitud (config_horario + Google)
            # Implementamos “validación exacta” reutilizando el buscador desde el candidato, pero sin aceptar el “siguiente”.
            # Para no duplicar lógica, pedimos validación exacta a SlotFinder.
            sugerencia = await self._slot_finder.validate_slot_exact(
                negocio=negocio,
                servicio_duracion_minutos=servicio.duracion_minutos,
                candidate_start_local=dt_parsed,
            )

            if not sugerencia:
                # Si no está libre exactamente, sugerimos el siguiente libre a partir de esa fecha.
                sugerencia = await availability_service.sugerir_siguiente_hueco(
                    db,
                    negocio_id=negocio.id,
                    servicio_id=servicio.id,
                    from_local_dt=dt_parsed,
                )
                if not sugerencia:
                    return {"reply_text": "No encontré huecos disponibles después de esa fecha.", "next_estado": "ESPERANDO_FECHA"}

            await bot_estado_repository.upsert(
                db,
                telefono=telefono_sender,
                defaults={
                    "estado": "ESPERANDO_FECHA",
                    "sugerencia_start_utc": sugerencia.start_utc,
                    "sugerencia_end_utc": sugerencia.end_utc,
                },
            )

            madrid_tz = pytz.timezone("Europe/Madrid")
            start_local_madrid = sugerencia.start_utc.astimezone(madrid_tz)
            end_local_madrid = sugerencia.end_utc.astimezone(madrid_tz)
            return {
                "reply_text": (
                    f"He encontrado disponibilidad: {start_local_madrid.strftime('%d/%m/%Y %H:%M')} "
                    f"({start_local_madrid.strftime('%H:%M')}-{end_local_madrid.strftime('%H:%M')}). "
                    "Responde 'Sí' para confirmar."
                ),
                "next_estado": "ESPERANDO_FECHA",
            }

        # Estado: esperando cancelación
        if estado_actual == "ESPERANDO_CANCELACION":
            idx = self._try_parse_index(t_norm)
            if idx is None:
                return {"reply_text": "Responde con el número de la cita que quieres cancelar.", "next_estado": "ESPERANDO_CANCELACION"}

            ids = state.cancelacion_citas_ids or []
            if idx <= 0 or idx > len(ids):
                return {"reply_text": "Número inválido. Selecciona de nuevo.", "next_estado": "ESPERANDO_CANCELACION"}

            import uuid

            cita_uuid = uuid.UUID(ids[idx - 1])
            cita = await cita_repository.get(db, cita_uuid)
            if not cita or cita.estado == "CANCELADA" or cita.negocio_id != negocio.id:
                return {"reply_text": "Esa cita no existe o ya está cancelada.", "next_estado": "None"}

            # Borrar en Google + cancelar en DB.
            try:
                if cita.calendar_event_id:
                    await self._google.delete_event(str(negocio.google_calendar_id), cita.calendar_event_id)
            except Exception:
                # Si Google falla, no tocamos DB para no dejar inconsistencia.
                return {"reply_text": "No pude borrar el evento en Google Calendar. Intenta de nuevo.", "next_estado": "ESPERANDO_CANCELACION"}

            await cita_repository.cancelar_cita(db, cita_uuid)

            await bot_estado_repository.upsert(
                db,
                telefono=telefono_sender,
                defaults={
                    "estado": "None",
                    "servicio_id": None,
                    "sugerencia_start_utc": None,
                    "sugerencia_end_utc": None,
                    "cancelacion_citas_ids": None,
                },
            )

            madrid_tz = pytz.timezone("Europe/Madrid")
            local_time = cita.fecha_hora.astimezone(madrid_tz).strftime("%d/%m/%Y %H:%M")
            return {"reply_text": f"Cita cancelada: {local_time}.", "next_estado": "None"}

        # Fallback: resetea
        return {"reply_text": "No entendí tu mensaje. Escribe 'Reservar' o 'Cancelar'.", "next_estado": "None"}


state_machine = WhatsAppStateMachine()

