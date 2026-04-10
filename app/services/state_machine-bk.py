from __future__ import annotations

import uuid
import pytz
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.empleado import Empleado

from app.core.google_calendar import get_google_calendar_client
from app.models.bot_state import BotEstado
from app.models.booking import Cita, Negocio, Servicio
from app.repositories.bot_state_repository import bot_estado_repository
from app.repositories.cita_repository import cita_repository
from app.repositories.negocio_repository import negocio_repository
from app.repositories.paciente_repository import paciente_repository
from app.repositories.servicio_repository import servicio_repository
from app.services.availability_service import availability_service
from app.services.slot_finder import SlotFinder, SlotSuggestion
from app.utils.dateparser_utils import extract_date_with_gemini


class WhatsAppStateMachine:
    def __init__(self):
        self._google = get_google_calendar_client()
        self._slot_finder = SlotFinder()

    @staticmethod
    def _norm(text: str) -> str:
        return " ".join((text or "").strip().lower().split())

    @staticmethod
    def _is_affirmative(text: str) -> bool:
        t = WhatsAppStateMachine._norm(text)
        return t in {"si", "sí", "confirmar", "confirmo", "ok", "vale", "confirmado"}

    @staticmethod
    def _try_parse_index(text: str) -> int | None:
        t = WhatsAppStateMachine._norm(text)
        try:
            return int(t)
        except ValueError:
            return None

    async def _get_or_create_state(self, db: AsyncSession, telefono_sender: str) -> BotEstado:
        existing = await bot_estado_repository.get_by_telefono(db, telefono_sender)
        if existing:
            return existing

        # Estado por defecto.
        return await bot_estado_repository.upsert(
            db, telefono=telefono_sender, defaults={"estado": "None"}
        )

    async def _load_negocio(self, db: AsyncSession, negocio_id: str) -> Negocio | None:
        return await negocio_repository.get(db, negocio_id)

    async def process_user_message(state, user_input, context):
        """
        Esta es la función principal que recorre los estados.
        """
        
        # ESTADO: El usuario está en el paso de 'Elegir Fecha'
        if state == "AWAITING_DATE":
            
            # PASO 1: Delegar la interpretación compleja a Gemini
            # No usamos regex. Le pasamos el texto crudo.
            target_date = await extract_date_with_gemini(
                user_input=user_input,
                reference_date=datetime.datetime.now(),
                timezone_str=context.business_timezone
            )

            # PASO 2: Validación de resultado
            if target_date is None:
                # Si Gemini no pudo entenderlo (devuelve None), 
                # el estado sigue siendo AWAITING_DATE y pedimos aclaración.
                return await send_whatsapp_message(
                    "No entendí la fecha. ¿Podrías decirme el día y la hora? (Ej: Mañana a las 15:00)"
                )

            # PASO 3: Acción con el dato validado
            # Si llegamos aquí, target_date es un objeto datetime real y válido.
            return await handle_valid_date_selection(target_date, context)


    async def process_message(
        self,
        db: AsyncSession,
        *,
        telefono_sender: str,
        texto_mensaje: str,
        negocio_id: uuid.UUID,
        paciente_nombre: str | None = None,
        now_utc: datetime | None = None,
    ) -> dict[str, Any]:
        
        print("\n" + "="*50)
        print(f"📥 [LOG INICIO] Mensaje recibido de {telefono_sender}: '{texto_mensaje}'")

        negocio = await self._load_negocio(db, negocio_id)
        if not negocio:
            print("❌ [LOG FATAL] Negocio no configurado o no encontrado.")
            return {"reply_text": "Negocio no configurado.", "next_estado": "None"}

        tz = pytz.timezone(negocio.zona_horaria or "Europe/Madrid")
        now_utc = now_utc or datetime.utcnow().replace(tzinfo=pytz.UTC)
        now_local = now_utc.astimezone(tz)

        # ====== INTERCEPTOR MODO ADMIN ======
        if getattr(negocio, 'telefono_admin', None) and telefono_sender == negocio.telefono_admin:
            print(f"👑 [LOG ADMIN] ¡Es el jefe! Derivando al panel de control secreto.")
            return await self._process_admin_message(db, telefono_sender, texto_mensaje, negocio, now_utc, tz)
        # ===========================================

        state = await self._get_or_create_state(db, telefono_sender)
        estado_actual = state.estado
        t_norm = self._norm(texto_mensaje)
        print(f"🔍 [LOG ESTADO] El usuario está en el estado: {estado_actual}")

        # ==========================================
        # ESTADO: NONE (Menú Principal)
        # ==========================================
        if estado_actual == "None":
            # 1. Definimos las raíces de palabras clave (flexibilidad total)
            claves_reservar = ["reserva","reservar","reserv", "cita", "apuntar", "coger", "hueco", "vez"]
            claves_cancelar = ["cancelacion","cancelar","cancel", "anul", "borrar", "quitar", "no puedo", "imposible"]
            claves_saludo = ["hola", "buen", "hey", "holi", "buenas", "q tal", "que tal"]

            # 2. Comprobamos la intención: ¿RESERVAR?
            if any(clave in t_norm for clave in claves_reservar):
                print("🛒 [LOG ACCIÓN] Intención detectada: RESERVAR. Cargando servicios...")
                servicios = await servicio_repository.list_by_negocio(db, negocio.id)
                if not servicios:
                    print("⚠️ [LOG] No hay servicios en la base de datos.")
                    return {"reply_text": "No hay servicios disponibles ahora.", "next_estado": "None"}

                await bot_estado_repository.upsert(
                    db,
                    telefono=telefono_sender,
                    defaults={
                        "estado": "ESPERANDO_SERVICIO",
                        "negocio_id": negocio.id,
                        "servicio_id": None,
                        "sugerencia_start_utc": None,
                        "sugerencia_end_utc": None,
                        "cancelacion_citas_ids": None,
                    },
                )
                print("✅ [LOG] Menú de servicios enviado. Pasando a ESPERANDO_SERVICIO.")
                
                # Menú limpio: Solo número y nombre del servicio
                menu = "\n".join([f"{i+1}️⃣ {s.nombre}" for i, s in enumerate(servicios)])
                
                mensaje = (
                    f"¿Qué te vas a hacer hoy?\n"
                    f"(Responde solo con el número del servicio)\n\n"
                    f"{menu}"
                )
                
                return {"reply_text": mensaje, "next_estado": "ESPERANDO_SERVICIO"}

            # 3. Comprobamos la intención: ¿CANCELAR?
            elif any(clave in t_norm for clave in claves_cancelar):
                print("🗑️ [LOG ACCIÓN] Intención detectada: CANCELAR. Buscando citas activas...")
                citas_actives = await cita_repository.list_actives_by_negocio(db, negocio.id)
                citas_actives = [c for c in citas_actives if c.calendar_event_id]
                if not citas_actives:
                    print("ℹ️ [LOG] El usuario no tiene citas activas para cancelar.")
                    await bot_estado_repository.upsert(
                        db,
                        telefono=telefono_sender,
                        defaults={"estado": "None", "cancelacion_citas_ids": None},
                    )
                    return {"reply_text": "No tienes citas activas para cancelar en este momento.", "next_estado": "None"}

                citas_ids = [str(c.id) for c in citas_actives]
                await bot_estado_repository.upsert(
                    db,
                    telefono=telefono_sender,
                    defaults={
                        "estado": "ESPERANDO_CANCELACION",
                        "negocio_id": negocio.id,
                        "servicio_id": None,
                        "cancelacion_citas_ids": citas_ids,
                    },
                )
                print(f"✅ [LOG] Mostrando {len(citas_actives)} citas para cancelar. Pasando a ESPERANDO_CANCELACION.")
                madrid_tz = pytz.timezone("Europe/Madrid")
                lista = "\n".join(
                    [
                        f"{i+1}. {c.fecha_hora.astimezone(madrid_tz).strftime('%d/%m/%Y %H:%M')}"
                        for i, c in enumerate(citas_actives)
                    ]
                )
                return {"reply_text": f"Selecciona la cita a cancelar:\n{lista}\nResponde con el número.", "next_estado": "ESPERANDO_CANCELACION"}

            # 4. Comprobamos la intención: ¿SALUDO?
            elif any(clave in t_norm for clave in claves_saludo):
                print("👋 [LOG] Saludo detectado. Mostrando bienvenida personalizada.")
                nombre = paciente_nombre or "amigo"
                mensaje = (
                    f"¡Hola {nombre}! 👋 Bienvenido a {negocio.nombre_negocio}.\n\n"
                    f"¿En qué te puedo ayudar hoy?\n"
                    f"✂️ Responde *Reservar* para coger una cita.\n"
                    f"❌ Responde *Cancelar* si necesitas anular la que ya tienes."
                )
                return {"reply_text": mensaje, "next_estado": "None"}
            
            # 5. FALLBACK (No ha entendido la intención)
            else:
                print(f"❓ [LOG] Mensaje no reconocido en estado None: {t_norm}")
                mensaje_error = (
                    "¡Uy, creo que no te he entendido bien! 😅\n\n"
                    "Dime simplemente si necesitas **coger cita** o si quieres **anular** la que ya tienes."
                )
                return {"reply_text": mensaje_error, "next_estado": "None"}

        # ==========================================
        # ESTADO: ESPERANDO SERVICIO
        # ==========================================
        if estado_actual == "ESPERANDO_SERVICIO":
            print("⏳ [LOG] El usuario está eligiendo servicio...")
            idx = self._try_parse_index(t_norm)
            servicios = await servicio_repository.list_by_negocio(db, negocio.id)

            if idx is None or idx <= 0 or idx > len(servicios):
                print(f"⚠️ [LOG] Selección de servicio inválida: {texto_mensaje}")
                return {"reply_text": "Por favor, elige un número de la lista.", "next_estado": "ESPERANDO_SERVICIO"}

            servicio = servicios[idx - 1]
            print(f"🎯 [LOG] Servicio seleccionado: {servicio.nombre}")

            # NUEVO: En lugar de buscar fecha, buscamos EMPLEADOS
            empleados = await db.execute(
                select(Empleado).where(Empleado.negocio_id == negocio.id, Empleado.activo == True)
            )
            lista_empleados = empleados.scalars().all()

            if not lista_empleados:
                print("⚠️ [LOG] No hay empleados activos. Saltando directamente a fecha (modo antiguo).")
                # (Aquí iría la lógica antigua de buscar fecha directamente si no hay empleados)
            
            print(f"👥 [LOG] Mostrando lista de {len(lista_empleados)} empleados.")
            
            # Guardamos el servicio en el estado y pasamos a esperar el empleado
            await bot_estado_repository.upsert(
                db, 
                telefono=telefono_sender, 
                defaults={"estado": "ESPERANDO_EMPLEADO", "servicio_id": servicio.id}
            )

            # Generamos el menú con Emojis (1️⃣, 2️⃣...)
            menu_empleados = "\n".join([f"{i+1}️⃣ {emp.nombre}" for i, emp in enumerate(lista_empleados)])
            
            mensaje = (
                f"Perfecto, ¿con quién quieres el servicio?\n"
                f"*(Responde solo con el número)*\n\n"
                f"{menu_empleados}\n"
                f"{len(lista_empleados)+1}️⃣ Me da igual"
            )
            
            return {
                "reply_text": mensaje,
                "next_estado": "ESPERANDO_EMPLEADO"
            }

        # ==========================================
        # NUEVO ESTADO: ESPERANDO EMPLEADO
        # ==========================================
        if estado_actual == "ESPERANDO_EMPLEADO":
            print("⏳ [LOG] El usuario está eligiendo peluquero...")
            idx = self._try_parse_index(t_norm)
            
            # Cargamos empleados para validar
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

            # Ahora que tenemos Servicio y Peluquero, buscamos la FECHA
            servicio = await servicio_repository.get(db, state.servicio_id)
            print(f"📅 [LOG] Buscando hueco para {servicio.nombre} con {nombre_emp}...")

            sugerencia = await availability_service.sugerir_siguiente_hueco(
                db,
                negocio_id=negocio.id,
                servicio_id=servicio.id,
                empleado_id=empleado_id, # IMPORTANTE: Pasar el ID
                from_local_dt=now_local,
            )

            await bot_estado_repository.upsert(
                db,
                telefono=telefono_sender,
                defaults={
                    "estado": "ESPERANDO_FECHA",
                    "empleado_id": empleado_id, # Guardamos quién lo va a atender
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
        # ESTADO: ESPERANDO FECHA
        # ==========================================
        if estado_actual == "ESPERANDO_FECHA":
            sugerencia: SlotSuggestion | None = None
            servicio_id = state.servicio_id
            if not servicio_id:
                print("❌ [LOG] Error: Se perdió el ID del servicio en el estado.")
                return {"reply_text": "Vuelve a empezar: escribe 'Reservar'.", "next_estado": "None"}

            servicio = await servicio_repository.get(db, servicio_id)
            if not servicio:
                return {"reply_text": "Servicio no encontrado. Vuelve a empezar: escribe 'Reservar'.", "next_estado": "None"}

            # 1) Confirmación ("Sí")
            if self._is_affirmative(texto_mensaje):
                print(f"✅ [LOG] El usuario ha dicho SÍ. Iniciando confirmación...")
                if not state.sugerencia_start_utc or not state.sugerencia_end_utc:
                    print("❌ [LOG] Fallo: No hay sugerencia activa en el estado.")
                    return {"reply_text": "No tengo un hueco sugerido activo. Escribe otra vez 'Reservar'.", "next_estado": "None"}

                # --- NUEVO PASO 1: PACIENTE ---
                print("👤 [LOG] Paso 1: Buscando o creando paciente en Base de Datos...")
                paciente_nombre_final = paciente_nombre or "Cliente"
                paciente = await paciente_repository.get_by_telefono(db, telefono_sender)
                if not paciente:
                    from app.schemas.booking import PacienteCreate
                    try:
                        print("➕ [LOG] Creando nuevo paciente...")
                        paciente = await paciente_repository.create(
                            db, PacienteCreate(telefono=telefono_sender, nombre=paciente_nombre_final)
                        )
                    except Exception as e:
                        import traceback
                        print("\n" + "🔥"*10 + " ERROR AL CREAR PACIENTE " + "🔥"*10)
                        traceback.print_exc()
                        await db.rollback()
                        paciente = await paciente_repository.get_by_telefono(db, telefono_sender)

                # --- NUEVO PASO 2: GOOGLE CALENDAR ---
                try:
                    print("🌐 [LOG] Paso 2: Intentando crear evento en Google Calendar...")
                    
                    # Magia: Sacar el nombre y el color dinámico del peluquero
                    nombre_peluquero = "Cualquiera"
                    color_elegido = "9" # Azul oscuro por defecto para reservas sin preferencia

                    if state.empleado_id:
                        emp_res = await db.execute(select(Empleado).where(Empleado.id == state.empleado_id))
                        emp_obj = emp_res.scalars().first()
                        if emp_obj:
                            nombre_peluquero = emp_obj.nombre
                            # Leemos el color directamente de la base de datos (dinámico y escalable)
                            if emp_obj.color_id:
                                color_elegido = str(emp_obj.color_id)
                    
                    # Magia: Crear el súper-título
                    nombre_cliente = paciente.nombre if paciente else paciente_nombre_final
                    summary = f"{servicio.nombre} - {nombre_cliente} con {nombre_peluquero}"
                    
                    event_id = await self._google.create_event(
                        str(negocio.google_calendar_id),
                        start_utc=state.sugerencia_start_utc,
                        end_utc=state.sugerencia_end_utc,
                        summary=summary,
                        description=f"Reservas WhatsApp SaaS. Tel: {telefono_sender}",
                        color_id=color_elegido # 👈 Google usará el color de la BD
                    )
                    print(f"✅ [LOG] Éxito Paso 2: Evento creado ID: {event_id}")
                except Exception as e:
                    import traceback
                    print("\n" + "🔥"*10 + " ERROR EN GOOGLE CALENDAR " + "🔥"*10)
                    traceback.print_exc()
                    await db.rollback()
                    return {"reply_text": "Ha ocurrido un error al crear el evento en el calendario. Prueba de nuevo.", "next_estado": "ESPERANDO_FECHA"}

                # Supabase Citas
                from app.schemas.booking import CitaCreate
                try:
                    print("💾 [LOG] Paso 3: Guardando la cita en Supabase...")
                    cita = await cita_repository.create(
                        db,
                        CitaCreate(
                            negocio_id=negocio.id,
                            paciente_id=paciente.id,
                            servicio_id=servicio.id,
                            empleado_id=state.empleado_id,  # 👈 ¡EL CULPABLE! Faltaba esta línea
                            fecha_hora=state.sugerencia_start_utc,
                            estado="CONFIRMADA",
                            calendar_event_id=event_id,
                            notas=None,
                        ),
                    )
                    print("✅ [LOG] Éxito Paso 3: Cita guardada.")
                except Exception as e:
                    import traceback
                    print("\n" + "🔥"*10 + " ERROR AL GUARDAR CITA " + "🔥"*10)
                    traceback.print_exc()
                    await db.rollback()
                    try:
                        print("⚠️ [LOG] Intentando borrar evento de Google para evitar inconsistencia...")
                        await self._google.delete_event(str(negocio.google_calendar_id), event_id)
                    except Exception:
                        pass
                    return {"reply_text": "Ha habido un fallo interno al cruzar la cita. Te propongo otro hueco.", "next_estado": "ESPERANDO_FECHA"}

                print("🎉 [LOG] Todo correcto. Limpiando estado.")
                await bot_estado_repository.upsert(
                    db,
                    telefono=telefono_sender,
                    defaults={"estado": "None", "servicio_id": None, "sugerencia_start_utc": None, "sugerencia_end_utc": None, "cancelacion_citas_ids": None},
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

            # 2) Interpretar como otra fecha (Ej: "El martes a las 5")
            import re
            print(f"📅 [LOG] El usuario escribió una fecha personalizada: '{texto_mensaje}'. Intentando parsear...")
            
            ## --- MAGIA: LIMPIAR TEXTO PARA LA IA ---
            texto_limpio = texto_mensaje.strip()
            
            # 1. Quitamos artículos iniciales ("El", "La", "Los")
            texto_limpio = re.sub(r'^(el|la|los|las)\s+', '', texto_limpio, flags=re.IGNORECASE)
            
            # 2. Arreglamos horas sin ceros. Usamos \b para que no rompa números como "12:00"
            texto_limpio = re.sub(r'(a\s+las|a\s+la|las|la)\s+(\d{1,2})\b(?!:\d{1,2})', r'\1 \2:00', texto_limpio, flags=re.IGNORECASE)
            
            # 3. Limpiamos el "a las" si ya venía con minutos (Ej: "a las 11:30" -> "11:30")
            texto_limpio = re.sub(r'(?:a\s+las|a\s+la|las|la)\s+(\d{1,2}:\d{2})', r'\1', texto_limpio, flags=re.IGNORECASE)
            
            print(f"🚀 [LOG] Original: '{texto_mensaje}' -> Masticado para IA: '{texto_limpio}'")
            
            dt_parsed = await extract_date_with_gemini(texto_limpio, reference_date=now_local, timezone_str=str(tz))
            
            if not dt_parsed:
                print("⚠️ [LOG] Fallo al entender la fecha escrita por el usuario.")
                return {
                    "reply_text": "No pude interpretar la fecha. Intenta con un formato un poco más directo como: 'martes a las 16:00' o 'mañana a las 10'.", 
                    "next_estado": "ESPERANDO_FECHA"
                }

            print(f"📅 [LOG] Fecha interpretada: {dt_parsed}. Validando disponibilidad...")
            dt_parsed = self._slot_finder.round_up_to_half_hour(dt_parsed)

            sugerencia = await self._slot_finder.validate_slot_exact(
                db=db,
                negocio=negocio,
                servicio_duracion_minutos=servicio.duracion_minutos,
                candidate_start_local=dt_parsed,
                empleado_id=state.empleado_id
            )

            if not sugerencia:
                print("🔄 [LOG] La hora exacta estaba ocupada. Buscando el SIGUIENTE hueco libre desde esa hora...")
                sugerencia = await availability_service.sugerir_siguiente_hueco(
                    db, 
                    negocio_id=negocio.id, 
                    servicio_id=servicio.id, 
                    empleado_id=state.empleado_id,
                    from_local_dt=dt_parsed
                )
                if not sugerencia:
                    return {"reply_text": "No encontré huecos disponibles después de esa fecha.", "next_estado": "ESPERANDO_FECHA"}

            print("✅ [LOG] Hueco propuesto correctamente. Guardando en estado.")
            await bot_estado_repository.upsert(
                db,
                telefono=telefono_sender,
                defaults={"estado": "ESPERANDO_FECHA", "sugerencia_start_utc": sugerencia.start_utc, "sugerencia_end_utc": sugerencia.end_utc},
            )

            madrid_tz = pytz.timezone("Europe/Madrid")
            start_local_madrid = sugerencia.start_utc.astimezone(madrid_tz)
            end_local_madrid = sugerencia.end_utc.astimezone(madrid_tz)
            
            # Formatear el nombre del peluquero para la respuesta
            nombre_emp = "Cualquiera"
            if state.empleado_id:
               
                res = await db.execute(select(Empleado).where(Empleado.id == state.empleado_id))
                emp_obj = res.scalars().first()
                if emp_obj:
                    nombre_emp = emp_obj.nombre

            return {
                "reply_text": (
                    f"He encontrado disponibilidad con {nombre_emp} el {start_local_madrid.strftime('%d/%m/%Y')} a las "
                    f"{start_local_madrid.strftime('%H:%M')}. "
                    "¿Te va bien? (Responde 'Sí' o dime otra fecha)."
                ),
                "next_estado": "ESPERANDO_FECHA",
            }

        # ==========================================
        # ESTADO: ESPERANDO CANCELACIÓN
        # ==========================================
        if estado_actual == "ESPERANDO_CANCELACION":
            print("🗑️ [LOG] Procesando solicitud de cancelación...")
            idx = self._try_parse_index(t_norm)
            if idx is None:
                return {"reply_text": "Responde con el número de la cita que quieres cancelar.", "next_estado": "ESPERANDO_CANCELACION"}

            ids = state.cancelacion_citas_ids or []
            if idx <= 0 or idx > len(ids):
                print(f"⚠️ [LOG] Índice inválido. IDs guardados: {len(ids)}")
                return {"reply_text": "Número inválido. Selecciona de nuevo.", "next_estado": "ESPERANDO_CANCELACION"}

            import uuid
            cita_uuid = uuid.UUID(ids[idx - 1])
            cita = await cita_repository.get(db, cita_uuid)
            
            if not cita or cita.estado == "CANCELADA" or cita.negocio_id != negocio.id:
                print("❌ [LOG] Cita no encontrada o ya cancelada en base de datos.")
                return {"reply_text": "Esa cita no existe o ya está cancelada.", "next_estado": "None"}

            try:
                print("🌐 [LOG] Borrando evento en Google Calendar...")
                if cita.calendar_event_id:
                    await self._google.delete_event(str(negocio.google_calendar_id), cita.calendar_event_id)
                print("✅ [LOG] Evento borrado en Google Calendar.")
            except Exception as e:
                import traceback
                print("\n" + "🔥"*10 + " ERROR BORRANDO EN GOOGLE " + "🔥"*10)
                traceback.print_exc()
                return {"reply_text": "No pude borrar el evento en Google Calendar. Intenta de nuevo.", "next_estado": "ESPERANDO_CANCELACION"}

            print("💾 [LOG] Marcando cita como cancelada en Supabase...")
            await cita_repository.cancelar_cita(db, cita_uuid)

            await bot_estado_repository.upsert(
                db,
                telefono=telefono_sender,
                defaults={"estado": "None", "servicio_id": None, "sugerencia_start_utc": None, "sugerencia_end_utc": None, "cancelacion_citas_ids": None},
            )

            print("🎉 [LOG] Cancelación completada.")
            madrid_tz = pytz.timezone("Europe/Madrid")
            local_time = cita.fecha_hora.astimezone(madrid_tz).strftime("%d/%m/%Y %H:%M")
            return {"reply_text": f"Cita cancelada: {local_time}.", "next_estado": "None"}

        # Fallback de seguridad
        print("❓ [LOG] Fallback: No se entendió el mensaje o el estado es inválido.")
        return {"reply_text": "No entendí tu mensaje. Escribe 'Reservar' o 'Cancelar'.", "next_estado": "None"}

    async def _process_admin_message(
        self,
        db: AsyncSession,
        telefono_sender: str,
        texto_mensaje: str,
        negocio: Negocio,
        now_utc: datetime,
        tz: Any
    ) -> dict[str, Any]:
        from app.core.whatsapp import send_text_message
        import traceback
        import uuid

        print("\n" + "="*50)
        print(f"👑 [LOG ADMIN INICIO] Interceptando mensaje del Jefe: '{texto_mensaje}'")

        state = await self._get_or_create_state(db, telefono_sender)
        estado_actual = state.estado
        t_norm = self._norm(texto_mensaje)
        now_local = now_utc.astimezone(tz)

        print(f"👑 [LOG ADMIN ESTADO] Estado actual en base de datos: {estado_actual}")

        # ==========================================
        # ESTADO: ESPERANDO CANCELACIÓN DEL ADMIN
        # ==========================================
        if estado_actual == "ADMIN_ESPERANDO_CANCELACION":
            print("🗑️ [LOG ADMIN] Procesando el número de cita a cancelar...")
            idx = self._try_parse_index(t_norm)
            
            if idx is None:
                if "salir" in t_norm or "menu" in t_norm:
                    print("🔙 [LOG ADMIN] El jefe ha escrito 'salir'. Volviendo al menú principal.")
                    await bot_estado_repository.upsert(db, telefono=telefono_sender, defaults={"estado": "ADMIN_NONE", "cancelacion_citas_ids": None})
                    return {"reply_text": "Saliendo al menú principal.", "next_estado": "ADMIN_NONE"}
                
                print("⚠️ [LOG ADMIN] El jefe no ha escrito un número válido.")
                return {"reply_text": "Escribe el número de la cita o 'salir'.", "next_estado": "ADMIN_ESPERANDO_CANCELACION"}

            ids = state.cancelacion_citas_ids or []
            if idx <= 0 or idx > len(ids):
                print(f"⚠️ [LOG ADMIN] Número fuera de rango. Introdujo: {idx}, Disponibles: {len(ids)}")
                return {"reply_text": "Número inválido. Prueba otra vez.", "next_estado": "ADMIN_ESPERANDO_CANCELACION"}

            cita_uuid = uuid.UUID(ids[idx - 1])
            print(f"🔍 [LOG ADMIN] Buscando cita UUID: {cita_uuid} en la base de datos...")
            cita = await cita_repository.get(db, cita_uuid)

            if not cita or cita.estado == "CANCELADA":
                print("❌ [LOG ADMIN] Cita no encontrada o ya estaba cancelada.")
                return {"reply_text": "Esa cita no existe o ya estaba cancelada.", "next_estado": "ADMIN_NONE"}

            # Proceso destructor en Google Calendar
            try:
                print("🌐 [LOG ADMIN] Paso 1: Borrando el evento en Google Calendar...")
                if cita.calendar_event_id:
                    await self._google.delete_event(str(negocio.google_calendar_id), cita.calendar_event_id)
                print("✅ [LOG ADMIN] Éxito Paso 1: Evento borrado en Calendar.")
            except Exception as e:
                print("\n" + "🔥"*10 + " ERROR AL BORRAR EN GOOGLE CALENDAR (ADMIN) " + "🔥"*10)
                traceback.print_exc()
                return {"reply_text": f"Error interno borrando en Google Calendar. Avisa a soporte técnico.", "next_estado": "ADMIN_ESPERANDO_CANCELACION"}

            # Proceso destructor en Base de Datos
            try:
                print("💾 [LOG ADMIN] Paso 2: Marcando la cita como CANCELADA en Supabase...")
                await cita_repository.cancelar_cita(db, cita_uuid)
                print("✅ [LOG ADMIN] Éxito Paso 2: Cita cancelada en base de datos.")
            except Exception as e:
                print("\n" + "🔥"*10 + " ERROR AL CANCELAR EN SUPABASE (ADMIN) " + "🔥"*10)
                traceback.print_exc()
                return {"reply_text": "Error de base de datos al cancelar la cita.", "next_estado": "ADMIN_ESPERANDO_CANCELACION"}

            # Notificar proactivamente al paciente
            print("👤 [LOG ADMIN] Paso 3: Buscando paciente para avisarle por WhatsApp...")
            paciente = await paciente_repository.get(db, cita.paciente_id)
            local_time = cita.fecha_hora.astimezone(tz).strftime("%d/%m/%Y a las %H:%M")
            aviso = ""
            
            if paciente:
                msg_paciente = f"Hola {paciente.nombre}. Lamentablemente tu cita del {local_time} ha sido cancelada por la barbería debido a un imprevisto. Disculpa las molestias."
                try:
                    print(f"📱 [LOG ADMIN] Enviando WhatsApp automático a {paciente.telefono}...")
                    send_text_message(to_phone=paciente.telefono, from_phone_id=negocio.whatsapp_phone_id, text=msg_paciente)
                    aviso = "\n\n(El paciente ha recibido un WhatsApp avisándole)."
                    print("✅ [LOG ADMIN] Éxito Paso 3: WhatsApp enviado al paciente correctamente.")
                except Exception as e:
                    print("\n" + "🔥"*10 + " ERROR AL ENVIAR WHATSAPP AL PACIENTE " + "🔥"*10)
                    traceback.print_exc()
                    aviso = "\n\n(⚠️ Falló el envío automático de WhatsApp al paciente)."
            else:
                print("⚠️ [LOG ADMIN] No se encontró al paciente en la base de datos.")

            print("🎉 [LOG ADMIN] Proceso de cancelación del jefe completado con éxito. Limpiando estado...")
            await bot_estado_repository.upsert(db, telefono=telefono_sender, defaults={"estado": "ADMIN_NONE", "cancelacion_citas_ids": None})
            return {"reply_text": f"✅ Cita cancelada correctamente.{aviso}", "next_estado": "ADMIN_NONE"}

        # ==========================================
        # ESTADO ADMIN: ELIGIENDO PELUQUERO PARA BLOQUEO
        # ==========================================
        if estado_actual == "ADMIN_ESPERANDO_EMPLEADO_BLOQUEO":
            if "salir" in t_norm or "menu" in t_norm:
                await bot_estado_repository.upsert(db, telefono=telefono_sender, defaults={"estado": "ADMIN_NONE"})
                return {"reply_text": "Saliendo al menú principal.", "next_estado": "ADMIN_NONE"}

            idx = self._try_parse_index(t_norm)
            res = await db.execute(select(Empleado).where(Empleado.negocio_id == negocio.id, Empleado.activo == True))
            empleados = res.scalars().all()

            if idx is None or idx <= 0 or idx > len(empleados):
                return {"reply_text": "Número inválido. Prueba otra vez o escribe 'salir'.", "next_estado": "ADMIN_ESPERANDO_EMPLEADO_BLOQUEO"}

            empleado_elegido = empleados[idx - 1]
            await bot_estado_repository.upsert(
                db, 
                telefono=telefono_sender, 
                defaults={"estado": "ADMIN_ESPERANDO_FECHA_BLOQUEO", "empleado_id": empleado_elegido.id}
            )
            return {"reply_text": f"Has elegido a {empleado_elegido.nombre}.\n\n¿Qué día y rango de horas quieres bloquear?\n(Ej: 'Mañana de 16:00 a 18:00' o 'el viernes de 10 a 12')", "next_estado": "ADMIN_ESPERANDO_FECHA_BLOQUEO"}
        # ==========================================
        # ESTADO ADMIN: CREANDO EL EVENTO FALSO (BLOQUEO)
        # ==========================================
        if estado_actual == "ADMIN_ESPERANDO_FECHA_BLOQUEO":
            if "salir" in t_norm or "menu" in t_norm:
                await bot_estado_repository.upsert(db, telefono=telefono_sender, defaults={"estado": "ADMIN_NONE", "empleado_id": None})
                return {"reply_text": "Saliendo al menú principal.", "next_estado": "ADMIN_NONE"}

            from app.utils.dateparser_utils import parse_user_datetime
            from datetime import timedelta
            import re
            
            # --- MAGIA: DETECTAR RANGOS Y LIMPIAR TEXTO ---
            # Quitamos palabras que confunden a la IA como "El" o "Los" al principio
            texto_limpio = re.sub(r'^(el|los)\s+', '', texto_mensaje.strip(), flags=re.IGNORECASE)
            
            patron = r'(?:de|desde)\s+(?:las\s+)?(\d{1,2}(?::\d{2})?)\s*(?:a|hasta)\s*(?:las\s+)?(\d{1,2}(?::\d{2})?)'
            rango_match = re.search(patron, texto_limpio, re.IGNORECASE)
            
            hora_fin_str = None
            
            if rango_match:
                hora_inicio_str = rango_match.group(1)
                hora_fin_str = rango_match.group(2)
                
                # Extraemos el día (ej: "martes")
                dia_str = texto_limpio[:rango_match.start()].strip()
                if not dia_str:
                    dia_str = "hoy"
                    
                # Formato infalible para el parser: "martes 12:00"
                texto_para_parser = f"{dia_str} {hora_inicio_str}"
            else:
                texto_para_parser = texto_limpio

            print(f"🧠 [LOG ADMIN] Original: '{texto_mensaje}' -> Masticado para IA: '{texto_para_parser}'")

            # Parseamos la fecha y hora de INICIO
            dt_parsed = parse_user_datetime(texto_para_parser, tz=tz, now_local=now_local)
            
            if not dt_parsed:
                return {
                    "reply_text": "No pude entender la fecha. Intenta con un formato claro como:\n- 'mañana de 12:00 a 14:00'\n- 'martes de 10 a 12:30'\n\nO escribe 'salir' para cancelar.", 
                    "next_estado": "ADMIN_ESPERANDO_FECHA_BLOQUEO"
                }

            dt_parsed = self._slot_finder.round_up_to_half_hour(dt_parsed)
            start_utc = dt_parsed.astimezone(pytz.UTC)
            
            # --- CALCULAR LA HORA DE FIN ---
            if hora_fin_str:
                # Convertimos "14" o "14:30" a horas y minutos reales
                partes_fin = hora_fin_str.split(":")
                h_fin = int(partes_fin[0])
                m_fin = int(partes_fin[1]) if len(partes_fin) > 1 else 0
                
                # Aplicamos esa hora de fin al mismo día que calculó el parser
                end_local = dt_parsed.replace(hour=h_fin, minute=m_fin, second=0)
                end_utc = end_local.astimezone(pytz.UTC)
                
                # Anti-errores: Si pone una hora de fin menor a la de inicio
                if end_utc <= start_utc:
                    end_utc = start_utc + timedelta(hours=2)
            else:
                # Si no pone rango (ej: "mañana a las 10"), bloqueamos 2 horas por defecto
                end_utc = start_utc + timedelta(hours=2)


            res = await db.execute(select(Empleado).where(Empleado.id == state.empleado_id))
            emp_obj = res.scalars().first()
            nombre_peluquero = emp_obj.nombre if emp_obj else "Peluquero"
            
            # El 11 es color Rojo en Google Calendar (Peligro/Bloqueado)
            color_bloqueo = "11" 
            summary = f"⛔ BLOQUEO - {nombre_peluquero}"
            
            try:
                print(f"🌐 [LOG ADMIN] Creando evento FALSO en Google Calendar (Bloqueo) para {nombre_peluquero}...")
                await self._google.create_event(
                    str(negocio.google_calendar_id),
                    start_utc=start_utc,
                    end_utc=end_utc,
                    summary=summary,
                    description="Bloqueo manual por imprevisto desde WhatsApp (Modo Jefe).",
                    color_id=color_bloqueo
                )
            except Exception as e:
                import traceback
                print("\n" + "🔥"*10 + " ERROR CREANDO BLOQUEO EN CALENDAR " + "🔥"*10)
                traceback.print_exc()
                return {"reply_text": "Fallo al crear el bloqueo en Google Calendar.", "next_estado": "ADMIN_NONE"}

            await bot_estado_repository.upsert(db, telefono=telefono_sender, defaults={"estado": "ADMIN_NONE", "empleado_id": None})
            
            # Formatear las horas para decírselo al jefe
            inicio_str = dt_parsed.strftime("%d/%m/%Y")
            hora_in_str = dt_parsed.strftime("%H:%M")
            hora_out_str = end_utc.astimezone(tz).strftime("%H:%M")
            
            return {
                "reply_text": f"✅ Agenda bloqueada con éxito.\n\nHe cerrado el calendario de {nombre_peluquero} el {inicio_str} desde las {hora_in_str} hasta las {hora_out_str}.", 
                "next_estado": "ADMIN_NONE"
            }
       # ==========================================
        # OPCIÓN 1: VER CITAS DE HOY
        # ==========================================
        if "ver" in t_norm or "1" in t_norm:
            print("📅 [LOG ADMIN] El jefe quiere VER LA AGENDA de hoy.")
            citas_actives = await cita_repository.list_actives_by_negocio(db, negocio.id)
            
            citas_hoy = [
                c for c in citas_actives 
                if c.calendar_event_id and c.fecha_hora.astimezone(tz).date() == now_local.date()
            ]

            if not citas_hoy:
                print("ℹ️ [LOG ADMIN] La agenda de hoy está vacía.")
                return {"reply_text": "Jefe, tienes la agenda libre hoy. No hay citas agendadas.", "next_estado": "ADMIN_NONE"}

            print(f"✅ [LOG ADMIN] Encontradas {len(citas_hoy)} citas para hoy. Generando lista...")
            citas_hoy.sort(key=lambda x: x.fecha_hora)
            lista = []
            
            for c in citas_hoy:
                p = await paciente_repository.get(db, c.paciente_id)
                n = p.nombre if p else "Paciente"
                
                # Magia: Buscar el nombre del peluquero asignado
                nombre_peluquero = ""
                if c.empleado_id:
                    res_emp = await db.execute(select(Empleado).where(Empleado.id == c.empleado_id))
                    emp_obj = res_emp.scalars().first()
                    if emp_obj:
                        nombre_peluquero = f" (con {emp_obj.nombre})"
                        
                hora = c.fecha_hora.astimezone(tz).strftime('%H:%M')
                lista.append(f"• {hora} - {n}{nombre_peluquero}")

            texto_lista = "\n".join(lista)
            return {"reply_text": f"📅 Citas para HOY:\n\n{texto_lista}", "next_estado": "ADMIN_NONE"}

        # ==========================================
        # OPCIÓN 2: CANCELAR UNA CITA
        # ==========================================
        if "cancelar" in t_norm or "2" in t_norm:
            print("🗑️ [LOG ADMIN] El jefe quiere CANCELAR UNA CITA. Buscando citas futuras...")
            citas_actives = await cita_repository.list_actives_by_negocio(db, negocio.id)
            citas_futures = [c for c in citas_actives if c.calendar_event_id and c.fecha_hora > now_utc]

            if not citas_futures:
                print("ℹ️ [LOG ADMIN] No hay citas futuras para cancelar.")
                return {"reply_text": "Jefe, no tienes citas futuras para cancelar.", "next_estado": "ADMIN_NONE"}

            print(f"✅ [LOG ADMIN] Encontradas {len(citas_futures)} citas futuras. Generando lista para el menú...")
            citas_futures.sort(key=lambda x: x.fecha_hora)
            citas_ids = [str(c.id) for c in citas_futures]

            await bot_estado_repository.upsert(
                db, telefono=telefono_sender, defaults={"estado": "ADMIN_ESPERANDO_CANCELACION", "cancelacion_citas_ids": citas_ids}
            )

            lista = []
            for i, c in enumerate(citas_futures):
                p = await paciente_repository.get(db, c.paciente_id)
                n = p.nombre if p else "Paciente"
                
                # Magia: Buscar el nombre del peluquero asignado
                nombre_peluquero = ""
                if c.empleado_id:
                    res_emp = await db.execute(select(Empleado).where(Empleado.id == c.empleado_id))
                    emp_obj = res_emp.scalars().first()
                    if emp_obj:
                        nombre_peluquero = f" (con {emp_obj.nombre})"
                        
                hora = c.fecha_hora.astimezone(tz).strftime('%d/%m %H:%M')
                lista.append(f"{i+1}. {n}{nombre_peluquero} - {hora}")

            texto_lista = "\n".join(lista)
            print("✅ [LOG ADMIN] Pasando el jefe al estado ADMIN_ESPERANDO_CANCELACION.")
            return {"reply_text": f"¿Qué cita quieres destruir?\n\n{texto_lista}\n\n(Escribe el número o 'salir'):", "next_estado": "ADMIN_ESPERANDO_CANCELACION"}
        
        # ==========================================
        # OPCIÓN 3: BLOQUEAR AGENDA
        # ==========================================
        if "bloquear" in t_norm or "3" in t_norm:
            print("🔒 [LOG ADMIN] El jefe quiere BLOQUEAR LA AGENDA. Buscando empleados...")

            res = await db.execute(select(Empleado).where(Empleado.negocio_id == negocio.id, Empleado.activo == True))
            empleados = res.scalars().all()

            if not empleados:
                return {"reply_text": "No tienes peluqueros configurados en la base de datos.", "next_estado": "ADMIN_NONE"}

            menu_emp = "\n".join([f"{i+1}. {e.nombre}" for i, e in enumerate(empleados)])
            await bot_estado_repository.upsert(db, telefono=telefono_sender, defaults={"estado": "ADMIN_ESPERANDO_EMPLEADO_BLOQUEO"})
            return {"reply_text": f"¿A qué peluquero le quieres bloquear la agenda?\n\n{menu_emp}\n\n(Escribe el número o 'salir'):", "next_estado": "ADMIN_ESPERANDO_EMPLEADO_BLOQUEO"}
        # ==========================================
        # FALLBACK: MENÚ PRINCIPAL
        # ==========================================
        print("❓ [LOG ADMIN] Mostrando menú principal por defecto.")
        return {
            "reply_text": "¡Hola Jefe! 💼 Menú de Control:\n\n1️⃣ Ver citas de hoy\n2️⃣ Cancelar una cita\n3️⃣ Bloquear agenda (Imprevistos)\n\nResponde 1, 2 o 3 para empezar.",
            "next_estado": "ADMIN_NONE"
        }


state_machine = WhatsAppStateMachine()

