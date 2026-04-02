from __future__ import annotations

from datetime import datetime
from typing import Any

import pytz
from fastapi import APIRouter, Request, Response

from app.core.database import AsyncSessionLocal
from app.core.whatsapp import send_text_message
from app.repositories.negocio_repository import negocio_repository
from app.services.state_machine import state_machine
from app.core.config import get_settings

router = APIRouter()
settings = get_settings()


def _extract_whatsapp_payload(payload: dict[str, Any]) -> tuple[str, str, str | None]:
    """
    Devuelve: (from_phone, display_phone_number, message_text)
    """
    entry = payload.get("entry") or []
    if not entry:
        return "", "", None
    changes = (entry[0].get("changes") or [])
    if not changes:
        return "", "", None
    value = changes[0].get("value") or {}

    messages = value.get("messages") or []
    if not messages:
        return "", "", None

    msg0 = messages[0] or {}
    from_phone = msg0.get("from") or ""

    # Tenant ruteo por display_phone_number
    metadata = value.get("metadata") or {}
    display_phone_number = metadata.get("display_phone_number") or ""

    message_text = None
    if "text" in msg0:
        message_text = (msg0.get("text") or {}).get("body")

    return from_phone, display_phone_number, message_text


@router.post("/webhook")
async def whatsapp_webhook(request: Request) -> Response:
    payload = await request.json()

    from_phone, display_phone_number, message_text = _extract_whatsapp_payload(payload)
    if not from_phone or not display_phone_number:
        return Response(status_code=200)
    if not message_text:
        return Response(status_code=200)

    db = AsyncSessionLocal()
    try:
        negocio = await negocio_repository.get_by_display_phone_number(db, display_phone_number)
        if not negocio:
            return Response(status_code=200)

        # Nombre del paciente desde contacts[0].profile.name
        value = (payload.get("entry") or [])[0].get("changes")[0].get("value") or {}
        contacts = value.get("contacts") or []
        profile_name = "Paciente"
        if contacts:
            profile = (contacts[0] or {}).get("profile") or {}
            profile_name = profile.get("name") or "Paciente"

        now_utc = datetime.utcnow().replace(tzinfo=pytz.UTC)
        result = await state_machine.process_message(
            db,
            telefono_sender=from_phone,
            texto_mensaje=message_text,
            negocio_id=negocio.id,
            paciente_nombre=profile_name,
            now_utc=now_utc,
        )

        # Aseguramos persistencia: en webhooks no usamos Depends(get_db).
        await db.commit()

        try:
            send_text_message(
                to_phone=from_phone,
                from_phone_id=negocio.whatsapp_phone_id,
                text=result.get("reply_text") or "",
            )
        except Exception:
            # Para no encolar errores en Meta: respondemos 200 aunque falle el envío.
            return Response(status_code=200)

        return Response(status_code=200)
    except Exception:
        await db.rollback()
        return Response(status_code=200)
    finally:
        await db.close()


@router.get("/webhook")
async def whatsapp_webhook_verification(request: Request) -> Response:
    """
    Verificación requerida por Meta WhatsApp Cloud API.
    """
    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")

    if mode == "subscribe" and settings.WHATSAPP_VERIFY_TOKEN and token == settings.WHATSAPP_VERIFY_TOKEN:
        return Response(content=challenge or "", media_type="text/plain")

    return Response(status_code=403)

