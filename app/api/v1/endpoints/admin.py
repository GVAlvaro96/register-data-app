from __future__ import annotations

from datetime import datetime
from typing import Any

import pytz
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.whatsapp import send_text_message
from app.repositories.cita_repository import cita_repository
from app.repositories.negocio_repository import negocio_repository
from app.repositories.paciente_repository import paciente_repository
from app.core.google_calendar import get_google_calendar_client

router = APIRouter()


@router.post("/admin/cancelar-cita/{cita_id}")
async def admin_cancelar_cita(
    cita_id: str,
    db: AsyncSession = Depends(get_db),
):
    try:
        cita_uuid = __import__("uuid").UUID(cita_id)
    except Exception:
        raise HTTPException(status_code=400, detail="cita_id inválido")

    cita = await cita_repository.get(db, cita_uuid)
    if not cita:
        raise HTTPException(status_code=404, detail="Cita no encontrada")
    if cita.estado == "CANCELADA":
        return {"ok": True, "message": "Ya estaba cancelada"}

    negocio = await negocio_repository.get(db, cita.negocio_id)
    if not negocio:
        raise HTTPException(status_code=404, detail="Negocio no encontrado")

    paciente = await paciente_repository.get(db, cita.paciente_id)
    if not paciente:
        raise HTTPException(status_code=404, detail="Paciente no encontrado")

    google = get_google_calendar_client()

    # Golden Rule E:
    # 1) Borrar evento de Google Calendar
    try:
        if cita.calendar_event_id:
            await google.delete_event(str(negocio.google_calendar_id), cita.calendar_event_id)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Fallo borrando evento Google: {e}")

    # 2) Actualizar DB a "CANCELADA"
    await cita_repository.cancelar_cita(db, cita_uuid)

    # 3) Mensaje proactivo WhatsApp
    # Regla B: para mensajes WhatsApp usa Europe/Madrid.
    local_tz = pytz.timezone("Europe/Madrid")
    local_time = cita.fecha_hora.astimezone(local_tz).strftime("%d/%m/%Y %H:%M")
    text = (
        f"Hola {paciente.nombre}. Cancelamos tu cita del {local_time} por un imprevisto. "
        "Gracias por tu comprensión."
    )

    try:
        send_text_message(
            to_phone=paciente.telefono,
            from_phone_id=negocio.whatsapp_phone_id,
            text=text,
        )
    except Exception as e:
        # Mantenemos consistente la regla: si WhatsApp falla, aun así devolvemos éxito parcial.
        return {"ok": True, "message": "Cita cancelada, pero falló el envío WhatsApp", "error": str(e)}

    return {"ok": True}

