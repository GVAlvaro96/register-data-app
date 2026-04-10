# app/bot/user_handlers.py
import re
import uuid
import pytz
import json 
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.models.booking import Negocio, Cita
from app.models.bot_state import BotEstado
from app.models.empleado import Empleado
from app.schemas.booking import CitaCreate, PacienteCreate

from app.repositories.servicio_repository import servicio_repository
from app.repositories.bot_state_repository import bot_estado_repository
from app.repositories.cita_repository import cita_repository
from app.repositories.paciente_repository import paciente_repository

from app.core.google_calendar import get_google_calendar_client
from app.services.availability_service import availability_service
from app.services.slot_finder import SlotFinder

from app.bot.intent_parser import try_parse_index, is_affirmative
from app.utils.dateparser_utils import extract_date_with_gemini

from app.schemas.booking import PacienteCreate, CitaCreate

# Instanciamos los servicios necesarios
slot_finder = SlotFinder()
google_client = get_google_calendar_client()

# ==========================================
# 1. ESTADO: ESPERANDO SERVICIO
# ==========================================
async def handle_esperando_servicio(
    db: AsyncSession, t_norm: str, texto_mensaje: str, negocio: Negocio, 
    state: BotEstado, telefono_sender: str
) -> dict:
    
    print("⏳ [LOG] El usuario está eligiendo servicio...")
    idx = try_parse_index(t_norm)
    servicios = await servicio_repository.list_by_negocio(db, negocio.id)

    if idx is None or idx <= 0 or idx > len(servicios):
        print(f"⚠️ [LOG] Selección de servicio inválida: {texto_mensaje}")
        return {"reply_text": "Por favor, elige un número de la lista.", "next_estado": "ESPERANDO_SERVICIO"}

    servicio = servicios[idx - 1]
    print(f"🎯 [LOG] Servicio seleccionado: {servicio.nombre}")
    
    # ========================================================
    # 🔥 BIFURCACIÓN 2.0: ¿Es Clase Grupal (1:N) o 1:1?
    # ========================================================
    if getattr(servicio, 'es_grupal', False):
        print(f"🧘‍♂️ [LOG] Clase grupal seleccionada: {servicio.nombre}. Buscando en Calendar...")
        
        # 1. Buscamos TODOS los eventos del calendario en los próximos 14 días
        tz_str = negocio.zona_horaria or "Europe/Madrid"
        tz = pytz.timezone(tz_str)
        now_utc = datetime.utcnow().replace(tzinfo=pytz.UTC)
        time_max = now_utc + timedelta(days=14) 
        
        eventos = await google_client.list_events_between(str(negocio.google_calendar_id), now_utc, time_max)
        
        # 2. Filtramos solo los eventos que se llamen EXACTAMENTE como el servicio (ej: "Pilates")
        nombre_servicio_norm = servicio.nombre.strip().lower()
        clases_encontradas = [e for e in eventos if e.get("summary", "").strip().lower() == nombre_servicio_norm]
        
        if not clases_encontradas:
            return {"reply_text": f"Lo siento, no hay clases de {servicio.nombre} programadas para los próximos días. El centro aún no las ha subido al calendario.", "next_estado": "None"}
            
        # 3. Comprobamos el aforo en Supabase y generamos el menú
        clases_disponibles = []
        opciones_almacenadas = []
        
        for clase in clases_encontradas:
            event_id = clase.get("id")
            
            # Contamos cuántas citas confirmadas existen para este event_id
            res_citas = await db.execute(select(func.count()).where(Cita.calendar_event_id == event_id, Cita.estado == "CONFIRMADA"))
            ocupadas = res_citas.scalar() or 0
            aforo = getattr(servicio, 'aforo_maximo', 1)
            plazas_libres = aforo - ocupadas
            
            if plazas_libres > 0:
                start_str = clase.get("start", {}).get("dateTime")
                end_str = clase.get("end", {}).get("dateTime")
                
                if start_str and end_str:
                    # Google devuelve ISO format. Parseamos a datetime.
                    dt_start = datetime.fromisoformat(start_str.replace('Z', '+00:00'))
                    dt_end = datetime.fromisoformat(end_str.replace('Z', '+00:00'))
                    hora_bonita = dt_start.astimezone(tz).strftime("%A %d/%m a las %H:%M")
                    
                    clases_disponibles.append(f"• {hora_bonita} (Quedan {plazas_libres} plazas)")
                    
                    # Guardamos un string JSON con la info vital para no tener que volver a llamar a Google
                    data_clase = {"event_id": event_id, "start_utc": dt_start.isoformat(), "end_utc": dt_end.isoformat()}
                    opciones_almacenadas.append(json.dumps(data_clase))
        
        if not clases_disponibles:
            return {"reply_text": f"¡Qué éxito! Todas las clases de {servicio.nombre} están llenas en los próximos días.", "next_estado": "None"}

        # 4. Guardamos las opciones en el estado del usuario (usamos cancelacion_citas_ids como almacén temporal de JSONs)
        await bot_estado_repository.upsert(
            db, telefono=telefono_sender, 
            defaults={"estado": "ESPERANDO_CLASE_GRUPAL", "servicio_id": servicio.id, "cancelacion_citas_ids": opciones_almacenadas}
        )
        
        menu = "\n".join([f"{i+1}️⃣ {texto}" for i, texto in enumerate(clases_disponibles)])
        mensaje = f"¡Genial! Tenemos clases de {servicio.nombre} en estos horarios:\n\n{menu}\n\nResponde con el número de la clase a la que quieres apuntarte."
        return {"reply_text": mensaje, "next_estado": "ESPERANDO_CLASE_GRUPAL"}

    # ========================================================
    # RUTINA NORMAL 1:1 (Masajes, Peluquería)
    # ========================================================
    empleados = await db.execute(
        select(Empleado).where(Empleado.negocio_id == negocio.id, Empleado.activo == True)
    )
    lista_empleados = empleados.scalars().all()

    if not lista_empleados:
        print("⚠️ [LOG] No hay empleados activos. Debería saltar a fecha, pero para evitar crash pedimos ayuda.")
        return {"reply_text": "No hay personal disponible para este servicio ahora mismo.", "next_estado": "None"}
    
    print(f"👥 [LOG] Mostrando lista de {len(lista_empleados)} empleados.")
    
    await bot_estado_repository.upsert(
        db, telefono=telefono_sender, 
        defaults={"estado": "ESPERANDO_EMPLEADO", "servicio_id": servicio.id}
    )

    menu_empleados = "\n".join([f"{i+1}️⃣ {emp.nombre}" for i, emp in enumerate(lista_empleados)])
    mensaje = (
        f"Perfecto, ¿con quién quieres el servicio?\n"
        f"*(Responde solo con el número)*\n\n"
        f"{menu_empleados}\n"
        f"{len(lista_empleados)+1}️⃣ Me da igual"
    )
    return {"reply_text": mensaje, "next_estado": "ESPERANDO_EMPLEADO"}


# ==========================================
# 2. ESTADO: ESPERANDO EMPLEADO
# ==========================================
async def handle_esperando_empleado(
    db: AsyncSession, t_norm: str, negocio: Negocio, state: BotEstado, 
    telefono_sender: str, now_local: datetime, tz: Any
) -> dict:
    
    print("⏳ [LOG] El usuario está eligiendo peluquero...")
    idx = try_parse_index(t_norm)
    
    res = await db.execute(select(Empleado).where(Empleado.negocio_id == negocio.id, Empleado.activo == True))
    empleados = res.scalars().all()

    empleado_id = None
    nombre_emp = "Cualquiera"

    if idx is not None and 1 <= idx <= len(empleados):
        empleado_id = empleados[idx-1].id
        nombre_emp = empleados[idx-1].nombre
        print(f"👤 [LOG] Peluquero seleccionado: {nombre_emp}")
    else:
        print("🎲 [LOG] El usuario eligió 'Me da igual' o puso una opción inválida.")

    servicio = await servicio_repository.get(db, state.servicio_id)
    print(f"📅 [LOG] Buscando hueco para {servicio.nombre} con {nombre_emp}...")

    sugerencia = await availability_service.sugerir_siguiente_hueco(
        db,
        negocio_id=negocio.id,
        servicio_id=servicio.id,
        empleado_id=empleado_id, 
        from_local_dt=now_local,
    )

    await bot_estado_repository.upsert(
        db,
        telefono=telefono_sender,
        defaults={
            "estado": "ESPERANDO_FECHA",
            "empleado_id": empleado_id,
            "sugerencia_start_utc": sugerencia.start_utc,
            "sugerencia_end_utc": sugerencia.end_utc
        }
    )

    start_local = sugerencia.start_utc.astimezone(tz)
    return {
        "reply_text": f"Genial. El próximo hueco con {nombre_emp} es el {start_local.strftime('%d/%m a las %H:%M')}. ¿Te va bien? (Responde 'Sí' o dime otra fecha)",
        "next_estado": "ESPERANDO_FECHA"
    }


# ==========================================
# 3. ESTADO: ESPERANDO FECHA
# ==========================================
async def handle_esperando_fecha(
    db: AsyncSession, texto_mensaje: str, negocio: Negocio, state: BotEstado, 
    telefono_sender: str, paciente_nombre: str | None, now_local: datetime, tz: Any
) -> dict:
    
    servicio_id = state.servicio_id
    if not servicio_id:
        print("❌ [LOG] Error: Se perdió el ID del servicio.")
        return {"reply_text": "Vuelve a empezar: escribe 'Reservar'.", "next_estado": "None"}

    servicio = await servicio_repository.get(db, servicio_id)

    # 1) CONFIRMACIÓN SÍ
    if is_affirmative(texto_mensaje):
        print(f"✅ [LOG] El usuario ha dicho SÍ. Iniciando confirmación...")
        if not state.sugerencia_start_utc or not state.sugerencia_end_utc:
            return {"reply_text": "No tengo un hueco sugerido activo. Escribe 'Reservar'.", "next_estado": "None"}

        # Paso 1: Paciente
        paciente_nombre_final = paciente_nombre or "Cliente"
        paciente = await paciente_repository.get_by_telefono(db, telefono_sender)
        if not paciente:
            print("➕ [LOG] Creando nuevo paciente...")
            paciente = await paciente_repository.create(
                db, PacienteCreate(telefono=telefono_sender, nombre=paciente_nombre_final)
            )

        # Paso 2: Google Calendar
        try:
            print("🌐 [LOG] Paso 2: Intentando crear evento en Google Calendar...")
            nombre_peluquero = "Cualquiera"
            color_elegido = "9" 

            if state.empleado_id:
                emp_res = await db.execute(select(Empleado).where(Empleado.id == state.empleado_id))
                emp_obj = emp_res.scalars().first()
                if emp_obj:
                    nombre_peluquero = emp_obj.nombre
                    if emp_obj.color_id:
                        color_elegido = str(emp_obj.color_id)
            
            nombre_cliente = paciente.nombre if paciente else paciente_nombre_final
            summary = f"{servicio.nombre} - {nombre_cliente} con {nombre_peluquero}"
            
            event_id = await google_client.create_event(
                str(negocio.google_calendar_id),
                start_utc=state.sugerencia_start_utc,
                end_utc=state.sugerencia_end_utc,
                summary=summary,
                description=f"Reservas WhatsApp SaaS. Tel: {telefono_sender}",
                color_id=color_elegido
            )
            print(f"✅ [LOG] Éxito Paso 2: Evento creado ID: {event_id}")
        except Exception as e:
            await db.rollback()
            return {"reply_text": "Ha ocurrido un error al crear el evento. Prueba de nuevo.", "next_estado": "ESPERANDO_FECHA"}

        # Paso 3: Supabase
        try:
            print("💾 [LOG] Paso 3: Guardando la cita en Supabase...")
            cita = await cita_repository.create(
                db,
                CitaCreate(
                    negocio_id=negocio.id,
                    paciente_id=paciente.id,
                    servicio_id=servicio.id,
                    empleado_id=state.empleado_id, 
                    fecha_hora=state.sugerencia_start_utc,
                    estado="CONFIRMADA",
                    calendar_event_id=event_id,
                    notas=None,
                ),
            )
            print("✅ [LOG] Éxito Paso 3: Cita guardada.")
        except Exception as e:
            await db.rollback()
            try:
                await google_client.delete_event(str(negocio.google_calendar_id), event_id)
            except:
                pass
            return {"reply_text": "Hubo un fallo interno al guardar la cita. Te propongo otro hueco.", "next_estado": "ESPERANDO_FECHA"}

        print("🎉 [LOG] Todo correcto. Limpiando estado.")
        await bot_estado_repository.upsert(
            db, telefono=telefono_sender,
            defaults={"estado": "None", "servicio_id": None, "sugerencia_start_utc": None, "sugerencia_end_utc": None}
        )

        madrid_tz = pytz.timezone("Europe/Madrid")
        start_local_madrid = cita.fecha_hora.astimezone(madrid_tz)
        end_local_madrid = (cita.fecha_hora + timedelta(minutes=servicio.duracion_minutos)).astimezone(madrid_tz)
        return {
            "reply_text": (
                f"Reserva confirmada para {start_local_madrid.strftime('%d/%m/%Y %H:%M')} "
                f"({start_local_madrid.strftime('%H:%M')}-{end_local_madrid.strftime('%H:%M')})."
            ),
            "next_estado": "None",
        }

    # 2) OTRA FECHA (Gemini / Dateparser)
    print(f"📅 [LOG] El usuario escribió una fecha personalizada. Intentando parsear...")
    texto_limpio = texto_mensaje.strip()
    texto_limpio = re.sub(r'^(el|la|los|las)\s+', '', texto_limpio, flags=re.IGNORECASE)
    texto_limpio = re.sub(r'(a\s+las|a\s+la|las|la)\s+(\d{1,2})\b(?!:\d{1,2})', r'\1 \2:00', texto_limpio, flags=re.IGNORECASE)
    texto_limpio = re.sub(r'(?:a\s+las|a\s+la|las|la)\s+(\d{1,2}:\d{2})', r'\1', texto_limpio, flags=re.IGNORECASE)
    
    dt_parsed = await extract_date_with_gemini(texto_limpio, reference_date=now_local, timezone_str=str(tz))
    
    if not dt_parsed:
        return {
            "reply_text": "No pude interpretar la fecha. Intenta con un formato un poco más directo como: 'martes a las 16:00'.", 
            "next_estado": "ESPERANDO_FECHA"
        }

    dt_parsed = slot_finder.round_up_to_half_hour(dt_parsed)
    sugerencia = await slot_finder.validate_slot_exact(
        db=db, negocio=negocio, servicio_duracion_minutos=servicio.duracion_minutos,
        candidate_start_local=dt_parsed, empleado_id=state.empleado_id
    )

    if not sugerencia:
        print("🔄 [LOG] Hora exacta ocupada. Buscando el SIGUIENTE hueco libre...")
        sugerencia = await availability_service.sugerir_siguiente_hueco(
            db, negocio_id=negocio.id, servicio_id=servicio.id, 
            empleado_id=state.empleado_id, from_local_dt=dt_parsed
        )
        if not sugerencia:
            return {"reply_text": "No encontré huecos disponibles después de esa fecha.", "next_estado": "ESPERANDO_FECHA"}

    await bot_estado_repository.upsert(
        db, telefono=telefono_sender,
        defaults={"estado": "ESPERANDO_FECHA", "sugerencia_start_utc": sugerencia.start_utc, "sugerencia_end_utc": sugerencia.end_utc},
    )

    start_local_madrid = sugerencia.start_utc.astimezone(pytz.timezone("Europe/Madrid"))
    
    nombre_emp = "Cualquiera"
    if state.empleado_id:
        res = await db.execute(select(Empleado).where(Empleado.id == state.empleado_id))
        emp_obj = res.scalars().first()
        if emp_obj: nombre_emp = emp_obj.nombre

    return {
        "reply_text": (
            f"He encontrado disponibilidad con {nombre_emp} el {start_local_madrid.strftime('%d/%m/%Y')} a las "
            f"{start_local_madrid.strftime('%H:%M')}. ¿Te va bien? (Responde 'Sí' o dime otra fecha)."
        ),
        "next_estado": "ESPERANDO_FECHA",
    }


# ==========================================
# 4. ESTADO: ESPERANDO CANCELACION
# ==========================================
async def handle_esperando_cancelacion(
    db: AsyncSession, t_norm: str, negocio: Negocio, state: BotEstado, telefono_sender: str
) -> dict:
    
    print("🗑️ [LOG] Procesando solicitud de cancelación...")
    idx = try_parse_index(t_norm)
    if idx is None:
        return {"reply_text": "Responde con el número de la cita que quieres cancelar.", "next_estado": "ESPERANDO_CANCELACION"}

    ids = state.cancelacion_citas_ids or []
    if idx <= 0 or idx > len(ids):
        return {"reply_text": "Número inválido. Selecciona de nuevo.", "next_estado": "ESPERANDO_CANCELACION"}

    cita_uuid = uuid.UUID(ids[idx - 1])
    cita = await cita_repository.get(db, cita_uuid)
    
    if not cita or cita.estado == "CANCELADA" or cita.negocio_id != negocio.id:
        return {"reply_text": "Esa cita no existe o ya está cancelada.", "next_estado": "None"}

    try:
        if cita.calendar_event_id:
            await google_client.delete_event(str(negocio.google_calendar_id), cita.calendar_event_id)
    except Exception as e:
        return {"reply_text": "No pude borrar el evento en Google Calendar. Intenta de nuevo.", "next_estado": "ESPERANDO_CANCELACION"}

    await cita_repository.cancelar_cita(db, cita_uuid)

    await bot_estado_repository.upsert(
        db, telefono=telefono_sender,
        defaults={"estado": "None", "cancelacion_citas_ids": None},
    )

    local_time = cita.fecha_hora.astimezone(pytz.timezone("Europe/Madrid")).strftime("%d/%m/%Y %H:%M")
    return {"reply_text": f"Cita cancelada: {local_time}.", "next_estado": "None"}

# ==========================================
# 5. ESTADO: ESPERANDO CLASE GRUPAL
# ==========================================
async def handle_esperando_clase_grupal(
    db: AsyncSession, t_norm: str, negocio: Negocio, state: BotEstado, 
    telefono_sender: str, paciente_nombre: str | None, tz: Any
) -> dict:
    
    print("🧘‍♂️ [LOG] Procesando selección de clase grupal...")
    idx = try_parse_index(t_norm)
    if idx is None:
        return {"reply_text": "Responde con el número de la clase a la que quieres apuntarte.", "next_estado": "ESPERANDO_CLASE_GRUPAL"}

    opciones_str = state.cancelacion_citas_ids or []
    if idx <= 0 or idx > len(opciones_str):
        return {"reply_text": "Número inválido. Selecciona una clase de la lista.", "next_estado": "ESPERANDO_CLASE_GRUPAL"}

    # Extraemos la información de la clase elegida de la memoria
    selected_data_str = opciones_str[idx - 1]
    data_clase = json.loads(selected_data_str)
    
    selected_event_id = data_clase["event_id"]
    start_utc = datetime.fromisoformat(data_clase["start_utc"])

    servicio_id = state.servicio_id
    servicio = await servicio_repository.get(db, servicio_id)

    # 1. Volvemos a comprobar el aforo por si alguien se ha apuntado en el último segundo
    res_citas = await db.execute(select(func.count()).where(Cita.calendar_event_id == selected_event_id, Cita.estado == "CONFIRMADA"))
    ocupadas = res_citas.scalar() or 0
    
    if ocupadas >= getattr(servicio, 'aforo_maximo', 1):
         await bot_estado_repository.upsert(db, telefono=telefono_sender, defaults={"estado": "None", "cancelacion_citas_ids": None})
         return {"reply_text": "¡Uy! Alguien acaba de coger la última plaza para esta clase. Escribe 'Reservar' para ver otros horarios.", "next_estado": "None"}

    # 2. Gestionamos el Paciente
    paciente_nombre_final = paciente_nombre or "Cliente"
    paciente = await paciente_repository.get_by_telefono(db, telefono_sender)
    if not paciente:
        paciente = await paciente_repository.create(db, PacienteCreate(telefono=telefono_sender, nombre=paciente_nombre_final))

    # 3. Guardamos la reserva en Supabase (NO creamos evento en Calendar porque ya existe)
    try:
        cita = await cita_repository.create(
            db,
            CitaCreate(
                negocio_id=negocio.id,
                paciente_id=paciente.id,
                servicio_id=servicio.id,
                empleado_id=None,  # En grupales no asignamos empleado al paciente, el profesor es del evento
                fecha_hora=start_utc,
                estado="CONFIRMADA",
                calendar_event_id=selected_event_id,
                notas="Reserva Clase Grupal",
            ),
        )
    except Exception as e:
        await db.rollback()
        return {"reply_text": "Hubo un fallo interno al apuntarte. Inténtalo de nuevo.", "next_estado": "ESPERANDO_CLASE_GRUPAL"}

    # 4. Limpiamos estado y confirmamos
    await bot_estado_repository.upsert(db, telefono=telefono_sender, defaults={"estado": "None", "servicio_id": None, "cancelacion_citas_ids": None})

    start_local_madrid = start_utc.astimezone(tz)
    return {
        "reply_text": f"✅ ¡Plaza reservada!\nTe has apuntado a {servicio.nombre} el {start_local_madrid.strftime('%d/%m a las %H:%M')}. ¡Nos vemos en clase!",
        "next_estado": "None",
    }