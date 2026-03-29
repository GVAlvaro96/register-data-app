import dateparser
import pytz
import json
from datetime import timedelta, datetime
from google.oauth2 import service_account
from googleapiclient.discovery import build

SCOPES = ['https://www.googleapis.com/auth/calendar.events']
SERVICE_ACCOUNT_FILE = 'credentials.json' 

def limpiar_fecha(texto: str) -> str:
    texto = texto.lower()
    ruido = ["el ", "la ", "los ", "las ", "a las ", "a la ", "que viene", "próximo", "proximo", "de la tarde", "de la mañana", "horas"]
    for palabra in ruido:
        texto = texto.replace(palabra, " ")
    return " ".join(texto.split())

def formatear_fecha_amigable(fecha: datetime) -> str:
    zona_madrid = pytz.timezone('Europe/Madrid')
    ahora = datetime.now(zona_madrid)
    hora_str = fecha.strftime('%H:%M')
    
    if fecha.date() == ahora.date():
        return f"hoy a las {hora_str}"
    elif fecha.date() == (ahora + timedelta(days=1)).date():
        return f"mañana a las {hora_str}"
    else:
        dias = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
        return f"el {dias[fecha.weekday()]} a las {hora_str}"


def esta_en_horario(fecha_inicio: datetime, fecha_fin: datetime, config_horario) -> bool:
    """Verifica si la cita completa entra dentro de un bloque usando Fechas Exactas."""
    
    # Seguro defensivo: Si la BD lo devuelve como texto puro, lo convertimos a Diccionario
    if isinstance(config_horario, str):
        try:
            config_horario = json.loads(config_horario)
        except:
            config_horario = {}

    if not config_horario:
        # Horario por defecto: Lunes a Viernes de 9 a 19
        if fecha_inicio.weekday() > 4: return False
        dt_apertura = fecha_inicio.replace(hour=9, minute=0, second=0, microsecond=0)
        dt_cierre = fecha_inicio.replace(hour=19, minute=0, second=0, microsecond=0)
        return fecha_inicio >= dt_apertura and fecha_fin <= dt_cierre

    dia_semana = str(fecha_inicio.weekday()) # 0=Lunes, 6=Domingo
    bloques = config_horario.get(dia_semana, [])

    for bloque in bloques:
        # Extraemos las horas y minutos exactos del JSON
        h_ini, m_ini = map(int, bloque["inicio"].split(':'))
        h_fin, m_fin = map(int, bloque["fin"].split(':'))
        
        # Creamos la fecha exacta de apertura y cierre para ESE DÍA en concreto
        dt_apertura = fecha_inicio.replace(hour=h_ini, minute=m_ini, second=0, microsecond=0)
        dt_cierre = fecha_inicio.replace(hour=h_fin, minute=m_fin, second=0, microsecond=0)
        
        # ¡La magia! Comparamos fechas completas. Aquí ya es imposible que falle la medianoche.
        if fecha_inicio >= dt_apertura and fecha_fin <= dt_cierre:
            return True
            
    return False

def buscar_siguiente_hueco_libre(service, calendar_id, fecha_base, config_horario):
    zona_madrid = pytz.timezone('Europe/Madrid')
    
    if fecha_base.tzinfo is not None:
        fecha_actual_naive = fecha_base.astimezone(zona_madrid).replace(tzinfo=None)
    else:
        fecha_actual_naive = fecha_base
        
    fecha_actual_naive = fecha_actual_naive.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    
    # Buscamos en las siguientes 168 horas (1 semana entera)
    for _ in range(168): 
        fecha_fin_naive = fecha_actual_naive + timedelta(hours=1)
        
        # 1. PREGUNTAMOS AL GUARDIA (con la nueva lógica blindada)
        if esta_en_horario(fecha_actual_naive, fecha_fin_naive, config_horario):
            
            # 2. Si está abierto, miramos en Google Calendar
            try:
                fecha_actual_loc = zona_madrid.localize(fecha_actual_naive)
                fecha_fin_loc = zona_madrid.localize(fecha_fin_naive)
            except pytz.exceptions.AmbiguousTimeError:
                fecha_actual_loc = zona_madrid.localize(fecha_actual_naive, is_dst=False)
                fecha_fin_loc = zona_madrid.localize(fecha_fin_naive, is_dst=False)
                
            time_min = (fecha_actual_loc + timedelta(minutes=1)).isoformat()
            time_max = (fecha_fin_loc - timedelta(minutes=1)).isoformat()
            
            eventos = service.events().list(
                calendarId=calendar_id, timeMin=time_min,
                timeMax=time_max, singleEvents=True
            ).execute()
            
            if not eventos.get('items'):
                return fecha_actual_loc # ¡Hueco libre y en horario!
                
        fecha_actual_naive += timedelta(hours=1)
        
    return None

def obtener_primer_hueco_disponible(calendar_id: str, config_horario):
    try:
        if not calendar_id: return None
        creds = service_account.Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
        service = build('calendar', 'v3', credentials=creds)
        
        zona_madrid = pytz.timezone('Europe/Madrid')
        ahora = datetime.now(zona_madrid)
        
        hueco = buscar_siguiente_hueco_libre(service, calendar_id, ahora, config_horario)
        if hueco:
            return formatear_fecha_amigable(hueco)
        return None
    except Exception as e:
        print(f"❌ Error buscando primer hueco: {e}")
        return None

def crear_evento_calendario(nombre_paciente: str, nombre_servicio: str, fecha_texto: str, calendar_id: str, config_horario):
    try:
        if not calendar_id: return {"status": "ERROR_SISTEMA"}

        texto_limpio = limpiar_fecha(fecha_texto)
        zona_madrid = pytz.timezone('Europe/Madrid')
        ahora = datetime.now(zona_madrid)
        
        fecha_inicio = dateparser.parse(texto_limpio, languages=['es'], settings={'TIMEZONE': 'Europe/Madrid', 'RETURN_AS_TIMEZONE_AWARE': True, 'PREFER_DATES_FROM': 'future'})
        if not fecha_inicio: return {"status": "ERROR_FECHA"}

        if fecha_inicio.tzinfo is None:
            fecha_inicio = zona_madrid.localize(fecha_inicio)
        else:
            fecha_inicio = fecha_inicio.astimezone(zona_madrid)

        if fecha_inicio < ahora:
            fecha_inicio += timedelta(days=7)

        fecha_fin = fecha_inicio + timedelta(hours=1)
        
        creds = service_account.Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
        service = build('calendar', 'v3', credentials=creds)

        # 1. ¿Está el negocio abierto a la hora que pide el cliente?
        # Le quitamos la zona horaria momentáneamente para que el "guardia" haga cálculos más limpios
        fecha_inicio_naive = fecha_inicio.replace(tzinfo=None)
        fecha_fin_naive = fecha_fin.replace(tzinfo=None)
        
        if not esta_en_horario(fecha_inicio_naive, fecha_fin_naive, config_horario):
            print("⛔ Fuera de horario comercial. Buscando alternativa...")
            siguiente_libre = buscar_siguiente_hueco_libre(service, calendar_id, fecha_inicio_naive, config_horario)
            if siguiente_libre:
                return {"status": "FUERA_HORARIO_CON_ALTERNATIVA", "alternativa": formatear_fecha_amigable(siguiente_libre)}
            return {"status": "FUERA_HORARIO"}

        # 2. Si está abierto, miramos en Google Calendar
        time_min = (fecha_inicio + timedelta(minutes=1)).isoformat()
        time_max = (fecha_fin - timedelta(minutes=1)).isoformat()

        eventos_existentes = service.events().list(
            calendarId=calendar_id, timeMin=time_min, timeMax=time_max, singleEvents=True
        ).execute()

        if eventos_existentes.get('items'):
            print("⛔ Hueco ocupado. Buscando alternativa...")
            siguiente_libre = buscar_siguiente_hueco_libre(service, calendar_id, fecha_inicio_naive, config_horario)
            if siguiente_libre:
                return {"status": "OCUPADO_CON_ALTERNATIVA", "alternativa": formatear_fecha_amigable(siguiente_libre)}
            return {"status": "OCUPADO"}

        # 3. Todo perfecto, creamos la cita
        evento = {
            'summary': f'💆‍♂️ Cita: {nombre_servicio} - {nombre_paciente}',
            'start': {'dateTime': fecha_inicio.isoformat(), 'timeZone': 'Europe/Madrid'},
            'end': {'dateTime': fecha_fin.isoformat(), 'timeZone': 'Europe/Madrid'},
        }
        event = service.events().insert(calendarId=calendar_id, body=evento).execute()
        return {
            "status": "OK", 
            "enlace": event.get('htmlLink'), 
            "event_id": event.get('id'),      # <--- ID del evento
            "fecha_inicio": fecha_inicio      # <--- El objeto DateTime para la BD
        }
    except Exception as e:
        print(f"❌ Error en Calendar: {e}")
        return {"status": "ERROR_SISTEMA"}

def cancelar_evento_calendario(calendar_id: str, event_id: str):
    try:
        creds = service_account.Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
        service = build('calendar', 'v3', credentials=creds)
        service.events().delete(calendarId=calendar_id, eventId=event_id).execute()
        print(f"🗑️ Evento {event_id} eliminado de Google Calendar.")
        return True
    except Exception as e:
        print(f"❌ Error al cancelar en Calendar: {e}")
        return False