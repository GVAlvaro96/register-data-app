import dateparser
from datetime import timedelta
from google.oauth2 import service_account
from googleapiclient.discovery import build
from src.core.config import settings

SCOPES = ['https://www.googleapis.com/auth/calendar.events']
SERVICE_ACCOUNT_FILE = 'credentials.json' 

def limpiar_fecha(texto: str) -> str:
    """Elimina el ruido humano para dejar solo día y hora."""
    texto = texto.lower()
    
    # Palabras de relleno que vamos a fulminar
    ruido = [
        "el ", "la ", "los ", "las ", 
        "a las ", "a la ", 
        "que viene", "próximo", "proximo", 
        "de la tarde", "de la mañana", "horas"
    ]
    
    for palabra in ruido:
        texto = texto.replace(palabra, " ")
        
    return " ".join(texto.split()) # Quita espacios dobles

def crear_evento_calendario(nombre_paciente: str, nombre_servicio: str, fecha_texto: str):
    try:
        # 1. PREPROCESAMIENTO
        texto_limpio = limpiar_fecha(fecha_texto)
        print(f"🔍 IA analizando: '{texto_limpio}'")
        
        # 2. IA: TRADUCIR TEXTO A FECHA
        fecha_inicio = dateparser.parse(
            texto_limpio, 
            languages=['es'], 
            settings={
                'TIMEZONE': 'Europe/Madrid', 
                'RETURN_AS_TIMEZONE_AWARE': True,
                'PREFER_DATES_FROM': 'future' # CRÍTICO: Siempre busca fechas futuras
            }
        )
        
        if not fecha_inicio:
            print(f"⚠️ La IA no pudo entender la fecha: {fecha_texto}")
            return None

        fecha_fin = fecha_inicio + timedelta(hours=1)

        # 3. AUTENTICACIÓN GOOGLE
        creds = service_account.Credentials.from_service_account_file(
            SERVICE_ACCOUNT_FILE, scopes=SCOPES)
        service = build('calendar', 'v3', credentials=creds)

        # 4. CREAR EVENTO
        evento = {
            'summary': f'💆‍♂️ Cita: {nombre_servicio} - {nombre_paciente}',
            'description': f'Reserva automática gestionada por GEMA.\nTexto original: {fecha_texto}',
            'start': {'dateTime': fecha_inicio.isoformat()},
            'end': {'dateTime': fecha_fin.isoformat()},
        }

        # 5. ENVIAR A GOOGLE CALENDAR
        event = service.events().insert(calendarId=settings.GOOGLE_CALENDAR_ID, body=evento).execute()
        enlace = event.get('htmlLink')
        print(f"📅 ¡Evento real creado el {fecha_inicio.strftime('%d/%m/%Y a las %H:%M')}: {enlace}")
        
        return enlace

    except Exception as e:
        print(f"❌ Error conectando con Google Calendar: {e}")
        return None