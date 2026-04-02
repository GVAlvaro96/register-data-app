from __future__ import annotations

import requests

from app.core.config import get_settings
from app.utils.phone_utils import normalize_phone_number

settings = get_settings()


def send_text_message(*, to_phone: str, from_phone_id: str, text: str) -> None:
    """
    Envia un mensaje de texto por WhatsApp Cloud API.

    Nota: el envío es síncrono; si se necesitara async, se encapsularía en hilo.
    """
    if not settings.WHATSAPP_ACCESS_TOKEN:
        raise RuntimeError("Falta WHATSAPP_ACCESS_TOKEN en el .env")
    if not from_phone_id:
        from_phone_id = settings.WHATSAPP_PHONE_NUMBER_ID or ""

    if not from_phone_id:
        raise RuntimeError("Falta whatsapp_phone_id (Negocio) y WHATSAPP_PHONE_NUMBER_ID en el .env")

    url = f"https://graph.facebook.com/v17.0/{from_phone_id}/messages"
    headers = {"Authorization": f"Bearer {settings.WHATSAPP_ACCESS_TOKEN}"}
    payload = {
        "messaging_product": "whatsapp",
        "to": normalize_phone_number(to_phone),
        "type": "text",
        "text": {"body": text},
    }

    resp = requests.post(url, json=payload, headers=headers, timeout=30)
    if resp.status_code >= 400:
        try:
            err = resp.json()
        except Exception:
            err = resp.text
        raise RuntimeError(f"WhatsApp API error {resp.status_code}: {err}")

