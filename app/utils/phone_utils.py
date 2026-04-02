from __future__ import annotations

import re


def normalize_phone_number(value: str | None) -> str:
    """
    Normaliza números de WhatsApp:
    - elimina '+' y cualquier prefijo/no-dígito
    - devuelve sólo dígitos
    """
    if not value:
        return ""
    digits = re.sub(r"[^0-9]", "", value)
    return digits

