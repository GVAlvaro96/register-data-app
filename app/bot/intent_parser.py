# app/bot/intent_parser.py
import re

def normalize_text(text: str) -> str:
    return " ".join((text or "").strip().lower().split())

def is_affirmative(text: str) -> bool:
    t = normalize_text(text)
    return t in {"si", "sí", "confirmar", "confirmo", "ok", "vale", "confirmado"}

def try_parse_index(text: str) -> int | None:
    t = normalize_text(text)
    try:
        return int(t)
    except ValueError:
        return None

def detect_intent(t_norm: str) -> str:
    claves_reservar = ["reserva","reservar","reserv", "cita", "apuntar", "coger", "hueco", "vez", "clase"]
    claves_cancelar = ["cancelacion","cancelar","cancel", "anul", "borrar", "quitar", "no puedo", "imposible"]
    claves_saludo = ["hola", "buen", "hey", "holi", "buenas", "q tal", "que tal"]

    if any(clave in t_norm for clave in claves_reservar):
        return "RESERVAR"
    elif any(clave in t_norm for clave in claves_cancelar):
        return "CANCELAR"
    elif any(clave in t_norm for clave in claves_saludo):
        return "SALUDAR"
    return "DESCONOCIDO"

def clean_date_text(texto_mensaje: str) -> str:
    texto_limpio = texto_mensaje.strip()
    texto_limpio = re.sub(r'^(el|la|los|las)\s+', '', texto_limpio, flags=re.IGNORECASE)
    texto_limpio = re.sub(r'(a\s+las|a\s+la|las|la)\s+(\d{1,2})\b(?!:\d{1,2})', r'\1 \2:00', texto_limpio, flags=re.IGNORECASE)
    texto_limpio = re.sub(r'(?:a\s+las|a\s+la|las|la)\s+(\d{1,2}:\d{2})', r'\1', texto_limpio, flags=re.IGNORECASE)
    return texto_limpio