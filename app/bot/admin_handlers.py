# app/bot/admin_handlers.py
from datetime import datetime, timedelta
import pytz
import re
import uuid
from typing import Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.booking import Negocio
from app.models.empleado import Empleado
from app.models.bot_state import BotEstado
from app.repositories.bot_state_repository import bot_estado_repository
from app.repositories.cita_repository import cita_repository
from app.repositories.paciente_repository import paciente_repository
from app.core.google_calendar import get_google_calendar_client
from app.services.slot_finder import SlotFinder
from app.bot.intent_parser import try_parse_index

async def process_admin_message(
    db: AsyncSession,
    telefono_sender: str,
    texto_mensaje: str,
    negocio: Negocio,
    now_utc: datetime,
    tz: Any,
    state: BotEstado,
    t_norm: str
) -> dict[str, Any]:
    
    estado_actual = state.estado
    google_client = get_google_calendar_client()
    
    # ==========================================
    # 1. ESTADO: ESPERANDO CANCELACIÓN DEL ADMIN
    # ==========================================
    if estado_actual == "ADMIN_ESPERANDO_CANCELACION":
        idx = try_parse_index(t_norm)
        if idx is None:
            if "salir" in t_norm or "menu" in t_norm:
                await bot_estado_repository.upsert(db, telefono=telefono_sender, defaults={"estado": "ADMIN_NONE", "cancelacion_citas_ids": None})
                return {"reply_text": "Saliendo al menú principal.", "next_estado": "ADMIN_NONE"}
            return {"reply_text": "Escribe el número de la cita o 'salir'.", "next_estado": "ADMIN_ESPERANDO_CANCELACION"}

        ids = state.cancelacion_citas_ids or []
        if idx <= 0 or idx > len(ids):
            return {"reply_text": "Número inválido. Prueba otra vez.", "next_estado": "ADMIN_ESPERANDO_CANCELACION"}

        cita_uuid = uuid.UUID(ids[idx - 1])
        cita = await cita_repository.get(db, cita_uuid)

        if not cita or cita.estado == "CANCELADA":
            return {"reply_text": "Esa cita no existe o ya estaba cancelada.", "next_estado": "ADMIN_NONE"}

        if cita.calendar_event_id:
            await google_client.delete_event(str(negocio.google_calendar_id), cita.calendar_event_id)
        
        await cita_repository.cancelar_cita(db, cita_uuid)
        
        # Enviar WhatsApp al paciente (Lógica simplificada para el handler)
        paciente = await paciente_repository.get(db, cita.paciente_id)
        local_time = cita.fecha_hora.astimezone(tz).strftime("%d/%m/%Y a las %H:%M")
        aviso = ""
        if paciente:
            from app.core.whatsapp import send_text_message
            msg_paciente = f"Hola {paciente.nombre}. Lamentablemente tu cita del {local_time} ha sido cancelada por un imprevisto."
            try:
                send_text_message(to_phone=paciente.telefono, from_phone_id=negocio.whatsapp_phone_id, text=msg_paciente)
                aviso = "\n\n(El paciente ha recibido un aviso)."
            except:
                aviso = "\n\n(⚠️ Falló el envío al paciente)."

        await bot_estado_repository.upsert(db, telefono=telefono_sender, defaults={"estado": "ADMIN_NONE", "cancelacion_citas_ids": None})
        return {"reply_text": f"✅ Cita cancelada.{aviso}", "next_estado": "ADMIN_NONE"}

    # ==========================================
    # 2. ELIGIENDO PELUQUERO PARA BLOQUEO
    # ==========================================
    if estado_actual == "ADMIN_ESPERANDO_EMPLEADO_BLOQUEO":
        if "salir" in t_norm:
            await bot_estado_repository.upsert(db, telefono=telefono_sender, defaults={"estado": "ADMIN_NONE"})
            return {"reply_text": "Saliendo al menú principal.", "next_estado": "ADMIN_NONE"}
        # ... (Tu código actual para elegir empleado) ...
        return {"reply_text": "Elige fecha (modo desarrollo - pendiente reconexión)", "next_estado": "ADMIN_ESPERANDO_FECHA_BLOQUEO"}

    # ==========================================
    # OPCIONES DE MENÚ PRINCIPAL
    # ==========================================
    if "ver" in t_norm or "1" in t_norm:
        # (Tu código actual para ver la agenda)
        return {"reply_text": "Jefe, tienes la agenda libre hoy. No hay citas agendadas.", "next_estado": "ADMIN_NONE"}
        
    if "cancelar" in t_norm or "2" in t_norm:
        # (Tu código actual para preparar cancelación)
        return {"reply_text": "Cargando citas...", "next_estado": "ADMIN_ESPERANDO_CANCELACION"}

    # Fallback
    return {
        "reply_text": "¡Hola Jefe! 💼 Menú de Control:\n\n1️⃣ Ver citas de hoy\n2️⃣ Cancelar una cita\n3️⃣ Bloquear agenda (Imprevistos)\n\nResponde 1, 2 o 3.",
        "next_estado": "ADMIN_NONE"
    }