from __future__ import annotations

from datetime import datetime
import re
from typing import Optional

import dateparser
import pytz


def limpiar_fecha(text: str) -> str:
    """
    Limpieza previa de texto para dateparser.

    Regla C: NO elimines la frase "a las ".
    """
    s = text.strip()
    s = re.sub(r"\s+", " ", s)
    # No tocaremos explícitamente "a las " para no romper la diferenciación.
    return s


def parse_user_datetime(text: str, *, tz: pytz.BaseTzInfo, now_local: datetime) -> Optional[datetime]:
    """
    Parsea lenguaje natural usando dateparser y la RELATIVE_BASE congelada.

    Regla C.1: congelar reloj a minute=0, second=0, microsecond=0.
    """
    cleaned = limpiar_fecha(text)

    frozen = now_local.replace(minute=0, second=0, microsecond=0)
    settings = {
        "RELATIVE_BASE": frozen,
        "PREFER_DATES_FROM": "future",
    }

    dt = dateparser.parse(cleaned, settings=settings)
    if not dt:
        return None

    if dt.tzinfo is None:
        # Localizamos en la zona del negocio.
        dt = tz.localize(dt)
    else:
        dt = dt.astimezone(tz)

    return dt

