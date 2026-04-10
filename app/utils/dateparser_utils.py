# app/utils/dateparser_utils.py

import os
import datetime
import pytz
import dateparser # <-- IMPORTANTE: Añadimos la librería
from google import genai
from dotenv import load_dotenv
from typing import Optional
import logging
from app.core.config import get_settings

settings = get_settings()

# 1. Forzar la lectura del archivo .env
load_dotenv()

# Configuración de Logging
logger = logging.getLogger(__name__)

# 2. Inicializamos el cliente moderno de Gemini. 
api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
client = genai.Client(api_key=api_key)

def extract_date_with_dateparser(user_input: str, timezone_str: str = "Europe/Madrid") -> Optional[datetime.datetime]:
    """
    Salvavidas local usando dateparser si Gemini falla.
    """
    logger.info(f"🔄 Activando salvavidas local (dateparser) para: '{user_input}'")
    try:
        # Configuramos para español y forzamos a que busque en el futuro
        parsed_date = dateparser.parse(
            user_input,
            languages=['es'],
            settings={
                'TIMEZONE': timezone_str,
                'RETURN_AS_TIMEZONE_AWARE': True,
                'PREFER_DATES_FROM': 'future'
            }
        )
        return parsed_date
    except Exception as e:
        logger.error(f"❌ Error en el salvavidas dateparser: {e}")
        return None

async def extract_date_with_gemini(
    user_input: str, 
    reference_date: datetime.datetime, 
    timezone_str: str = "Europe/Madrid"
) -> Optional[datetime.datetime]:
    """
    Intenta extraer la fecha con Gemini 2.5 Flash y usa dateparser como respaldo si falla.
    """
    # Preparación de la zona horaria
    try:
        tz = pytz.timezone(timezone_str)
        ref_date_localized = reference_date.astimezone(tz)
    except Exception as e:
        logger.error(f"Error configurando timezone {timezone_str}: {e}")
        tz = pytz.timezone("UTC")
        ref_date_localized = reference_date.astimezone(tz)

    # Prompt de Sistema Estricto
    prompt = f"""
    Eres un extractor de fechas experto. Tu única tarea es convertir lenguaje natural en una fecha ISO 8601.
    
    CONTEXTO:
    - Fecha y hora actual: {ref_date_localized.strftime('%Y-%m-%d %H:%M:%S %Z')}
    - Zona horaria: {timezone_str}
    
    INSTRUCCIONES:
    1. Analiza el texto del usuario: "{user_input}"
    2. Si el usuario menciona una hora, asume el día futuro más cercano basado en la fecha actual.
    3. Devuelve ÚNICAMENTE la fecha en formato ISO 8601 (YYYY-MM-DDTHH:MM:SS) o la palabra 'INVALID' si no es posible determinar una fecha clara.
    4. No incluyas explicaciones, ni texto adicional, ni markdown.
    
    RESPUESTA (SOLO ISO 8601 O 'INVALID'):
    """

    try:
        # Ejecución asíncrona nativa de la API de Google
        response = await client.aio.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
        )
        
        result_text = response.text.strip()

        if "INVALID" in result_text.upper():
            logger.warning(f"⚠️ Gemini no pudo parsear la fecha: '{user_input}'. Lanzando al salvavidas.")
            # Si Gemini se rinde con un formato raro, probamos con Dateparser
            return extract_date_with_dateparser(user_input, timezone_str)

        # Limpieza básica de posibles markdown
        clean_date_str = result_text.replace("```", "").replace("python", "").strip()
        
        # Parseo de la fecha resultante
        parsed_date = datetime.datetime.fromisoformat(clean_date_str)
        
        # Aseguramos que la fecha tenga la zona horaria correcta
        if parsed_date.tzinfo is None:
            parsed_date = tz.localize(parsed_date)
        else:
            parsed_date = parsed_date.astimezone(tz)
            
        return parsed_date

    except Exception as e:
        # AQUÍ ESTÁ LA MAGIA: Si hay error 503, timeout, o cualquier fallo de Google
        logger.error(f"🔥 Error en API de Gemini: {str(e)}. Activando fallback...")
        return extract_date_with_dateparser(user_input, timezone_str)