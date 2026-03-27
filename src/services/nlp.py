import re

def analizar_intencion(texto: str) -> str:
    """
    Analiza el texto del paciente y devuelve la intención principal.
    """
    texto_limpio = texto.lower()
    
    # 1. PRIORIDAD ALTA: Cancelar
    # Si detecta "cancelar" o "anular", gana siempre. Da igual si también dice "cita".
    if re.search(r'\b(cancelar|anular|no puedo ir|borrar|quitar)\b', texto_limpio):
        return "CANCELAR"
        
    # 2. PRIORIDAD MEDIA: Reservar
    elif re.search(r'\b(reservar|reserva|masaje|turno|hueco|agendar|cita)\b', texto_limpio):
        return "RESERVAR"
        
    # 3. PRIORIDAD BAJA: Saludos
    elif re.search(r'\b(hola|buenos dias|buenas|buenas tardes|hey)\b', texto_limpio):
        return "SALUDO"
        
    return "DESCONOCIDO"


def generar_respuesta_base(intencion: str, nombre_paciente: str) -> str:
    """
    Genera una respuesta rápida basada en la intención detectada.
    """
    if intencion == "RESERVAR":
        return f"¡Perfecto {nombre_paciente}! Veo que quieres reservar una cita 📅. (Pronto te mostraré los huecos disponibles)."
    elif intencion == "CANCELAR":
        return f"Entendido, {nombre_paciente}. Quieres cancelar una cita ❌. (Pronto buscaré tus citas activas)."
    elif intencion == "SALUDO":
        return f"¡Hola {nombre_paciente}! Soy GEMA 🤖. ¿En qué te puedo ayudar hoy? ¿Necesitas reservar o cancelar una cita?"
    else:
        return f"Perdona {nombre_paciente}, no te he entendido bien 😅. ¿Podrías decirme si quieres 'reservar' o 'cancelar' una cita?"