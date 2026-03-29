from fastapi import APIRouter, Request, Depends
from sqlalchemy.orm import Session
from src.db.database import get_db
from src.db import crud
from src.services.whatsapp import enviar_mensaje_texto
from src.services.nlp import analizar_intencion, generar_respuesta_base
from src.services.state import obtener_estado, actualizar_estado, limpiar_estado, guardar_dato_reserva, obtener_dato_reserva
from src.services.calendar import (
    crear_evento_calendario, 
    obtener_primer_hueco_disponible, 
    cancelar_evento_calendario
)

import pytz

router = APIRouter()

@router.post("/webhook")
async def recibir_mensaje(request: Request, db: Session = Depends(get_db)):
    try:
        body = await request.json()
        
        if body.get("object") == "whatsapp_business_account":
            entry = body.get("entry", [{}])[0]
            changes = entry.get("changes", [{}])[0]
            value = changes.get("value", {})
            
            if "messages" in value:
                mensaje = value["messages"][0]
                telefono_paciente = mensaje.get("from")
                texto_mensaje = mensaje.get("text", {}).get("body", "")
                nombre_perfil = value.get("contacts", [{}])[0].get("profile", {}).get("name", "Paciente")
                
                # --- 1. DETECTAR EL NEGOCIO (EL CEREBRO MULTI-TENANT) ---
                metadata = value.get("metadata", {})
                telefono_bot = metadata.get("display_phone_number")
                
                # Espiamos el formato exacto que envía Meta
                print(f"🕵️ FORMATO EXACTO DE META: '{telefono_bot}'")
                
                negocio = crud.obtener_negocio_por_telefono(db, telefono_bot)
                if not negocio:
                    print(f"⚠️ Mensaje ignorado. Número de bot no registrado en BD: {telefono_bot}")
                    return {"status": "error_negocio_no_encontrado"}
                
                NEGOCIO_ID = negocio.id 
                print(f"🏢 Atendiendo para el negocio: {negocio.nombre_negocio} (ID: {NEGOCIO_ID})")
                
                # --- 2. PACIENTE Y MEMORIA ---
                paciente = crud.obtener_o_crear_paciente(
                    db=db, 
                    negocio_id=NEGOCIO_ID, 
                    telefono=telefono_paciente,
                    nombre=nombre_perfil
                )
                
                print(f"🟢 IN: PACIENTE {paciente.nombre} DICE: {texto_mensaje}")
                estado_actual = obtener_estado(telefono_paciente)
                
                # --- 3. MÁQUINA DE ESTADOS ---
                if estado_actual == "ESPERANDO_SERVICIO":
                    servicios = crud.obtener_servicios_activos(db, NEGOCIO_ID) 
                    if servicios:
                        servicio_elegido = servicios[0] 
                        guardar_dato_reserva(telefono_paciente, "servicio_id", servicio_elegido.id)
                        
                        # Pasamos la configuración del horario
                        primer_hueco = obtener_primer_hueco_disponible(negocio.google_calendar_id, negocio.config_horario)
                        
                        if primer_hueco:
                            respuesta = f"¡Anotado, {paciente.nombre}! 📝 Has elegido '*{servicio_elegido.nombre}*'.\n\nEl hueco libre más cercano es **{primer_hueco}**. Si te viene bien escríbeme esa fecha, o si no por favor indícanos la fecha y hora que deseas."
                        else:
                            respuesta = f"¡Anotado, {paciente.nombre}! 📝 Has elegido '*{servicio_elegido.nombre}*'.\n\n¿Qué día y hora te viene bien? (Ej: El martes a las 18:00)"
                            
                        actualizar_estado(telefono_paciente, "ESPERANDO_FECHA")
                    
                elif estado_actual == "ESPERANDO_FECHA":
                    servicio_id = obtener_dato_reserva(telefono_paciente, "servicio_id")
                    
                    resultado_calendario = crear_evento_calendario(
                        nombre_paciente=paciente.nombre, 
                        nombre_servicio="Servicio Reservado", 
                        fecha_texto=texto_mensaje,
                        calendar_id=negocio.google_calendar_id,
                        config_horario=negocio.config_horario # <--- LO PASAMOS AQUÍ
                    )
                    
                    if resultado_calendario["status"] == "ERROR_FECHA":
                        respuesta = "Hmm, no he entendido bien la fecha y hora. 🤔 ¿Podrías decírmelo de otra forma? (Ej: El jueves a las 11:00)"
                        
                    elif resultado_calendario["status"] == "FUERA_HORARIO_CON_ALTERNATIVA":
                        alternativa = resultado_calendario["alternativa"]
                        respuesta = f"Lo siento, a esa hora estamos cerrados. 🌙 El siguiente hueco dentro de nuestro horario es **{alternativa}**. ¿Te apunto esa fecha u otra distinta?"
                        
                    elif resultado_calendario["status"] == "FUERA_HORARIO":
                        respuesta = "A esa hora estamos cerrados y no encuentro huecos cercanos. ¿Podrías indicarme otro día?"

                        
                    elif resultado_calendario["status"] == "OCUPADO_CON_ALTERNATIVA":
                        alternativa = resultado_calendario["alternativa"]
                        respuesta = f"Parece que ese hueco está ocupado. El siguiente hueco libre es **{alternativa}**. Si te viene bien escríbeme esa fecha, o si no por favor indica otra hora para la reserva."
                        
                    elif resultado_calendario["status"] == "OCUPADO":
                        respuesta = "¡Uy! 😅 Acabo de mirar la agenda y ese hueco ya está ocupado. ¿Te viene bien otro día?"
                        
                    elif resultado_calendario["status"] == "ERROR_SISTEMA":
                        respuesta = "Ha ocurrido un error técnico al mirar la agenda. Por favor, inténtalo más tarde."
                        limpiar_estado(telefono_paciente)
                        
                    elif resultado_calendario["status"] == "OK":
                        nueva_cita = crud.crear_cita(
                            db=db, 
                            paciente_id=paciente.id, 
                            negocio_id=NEGOCIO_ID,
                            servicio_id=servicio_id, 
                            fecha_hora=resultado_calendario["fecha_inicio"], # <--- Va directo a tu columna
                            notas=texto_mensaje,                             
                            google_event_id=resultado_calendario.get("event_id") 
                        )
                        respuesta = f"¡Hecho! 🎉 He guardado tu cita formalmente para: *{texto_mensaje}*.\nRevisa tu calendario."
                        limpiar_estado(telefono_paciente)
                elif estado_actual == "ESPERANDO_CANCELACION":
                    citas_pendientes = crud.obtener_citas_pendientes(db, str(paciente.id), str(NEGOCIO_ID))
                    
                    try:
                        indice = int(texto_mensaje.strip()) - 1
                        if 0 <= indice < len(citas_pendientes):
                            cita_a_cancelar = citas_pendientes[indice]
                            
                            servicio = crud.obtener_servicio_por_id(db, str(cita_a_cancelar.servicio_id))
                            nombre_servicio = servicio.nombre if servicio else "tu servicio"
                            
                            # 🔄 CONVERTIMOS LA HORA UTC A LA HORA LOCAL PARA EL MENSAJE
                            zona_local = pytz.timezone(negocio.zona_horaria or 'Europe/Madrid')
                            fecha_local = cita_a_cancelar.fecha_hora.astimezone(zona_local)
                            fecha_texto = fecha_local.strftime('%d/%m/%Y a las %H:%M')
                            
                            # 1. Borramos de Google Calendar
                            if cita_a_cancelar.google_event_id:
                                cancelar_evento_calendario(negocio.google_calendar_id, cita_a_cancelar.google_event_id)
                            
                            # 2. Borramos de nuestra BD
                            crud.cancelar_cita(db, str(cita_a_cancelar.id))
                            
                            respuesta = f"✅ ¡Hecho! He cancelado correctamente tu cita de *{nombre_servicio}* programada para el *{fecha_texto}*."
                            limpiar_estado(telefono_paciente)
                        else:
                            respuesta = "Número no válido. Dime el número de la lista que corresponde a la cita que quieres cancelar."
                    except ValueError:
                        respuesta = "Por favor, dime solo el número (ejemplo: 1)."
                    
                else:
                    intencion = analizar_intencion(texto_mensaje)
                    if intencion == "RESERVAR":
                        servicios = crud.obtener_servicios_activos(db, NEGOCIO_ID)
                        if servicios:
                            respuesta = f"¡Perfecto {paciente.nombre}! Aquí tienes nuestros servicios:\n\n"
                            for i, s in enumerate(servicios, 1):
                                respuesta += f"*{i}. {s.nombre}* - {s.precio}€\n"
                            respuesta += "\n¿Cuál te gustaría reservar? (Dime el número)"
                            actualizar_estado(telefono_paciente, "ESPERANDO_SERVICIO")
                        else:
                            respuesta = "No hay servicios disponibles en este momento."
                    elif intencion == "CANCELAR":
                        citas_pendientes = crud.obtener_citas_pendientes(db, str(paciente.id), str(NEGOCIO_ID))
                        
                        if not citas_pendientes:
                            respuesta = "He revisado la agenda y ahora mismo no tienes ninguna cita pendiente con nosotros. ¿Te puedo ayudar con algo más?"
                        else:
                            respuesta = "Tienes estas citas pendientes con nosotros:\n\n"
                            # Magia de zonas horarias (Leemos la del negocio, si no, Madrid por defecto)
                            zona_local = pytz.timezone(negocio.zona_horaria or 'Europe/Madrid')

                            for i, cita in enumerate(citas_pendientes, 1):
                                servicio = crud.obtener_servicio_por_id(db, str(cita.servicio_id))
                                nombre_serv = servicio.nombre if servicio else "Servicio"
                                # Usamos tu campo fecha_hora para que quede elegante
                                fecha_legible = cita.fecha_hora.astimezone(zona_local).strftime('%d/%m/%Y a las %H:%M')
                                respuesta += f"*{i}. {nombre_serv}* - el {fecha_legible}\n"
                            
                            respuesta += "\n¿Cuál deseas cancelar? (Dime el número)"
                            actualizar_estado(telefono_paciente, "ESPERANDO_CANCELACION")
                    else:
                        respuesta = generar_respuesta_base(intencion, paciente.nombre)
                
                # --- 4. ENVIAR RESPUESTA ---
                await enviar_mensaje_texto(telefono_destino=telefono_paciente, texto=respuesta)

        return {"status": "success"}

    except Exception as e:
        print(f"🔴 Error procesando webhook: {e}")
        return {"status": "error_ignorado"}