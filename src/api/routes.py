from fastapi import APIRouter, Depends, HTTPException, Request, Query
from sqlalchemy.orm import Session
from sqlalchemy import text
from src.db.database import get_db
from src.schemas import ServicioCreate, ServicioResponse
from src.db import crud
from src.services.whatsapp import enviar_mensaje_texto
from src.services.whatsapp import enviar_mensaje_texto
from src.services.nlp import analizar_intencion, generar_respuesta_base
from src.services.state import (
    obtener_estado, 
    actualizar_estado, 
    limpiar_estado, 
    guardar_dato_reserva, 
    obtener_dato_reserva
)
from src.services.calendar import crear_evento_calendario

router = APIRouter()

@router.get("/")
def read_root():
    return {"mensaje": "Bienvenido a Register Data App API"}

@router.get("/health")
def health_check():
    return {"status": "ok", "version": "1.0.0"}

@router.get("/test-db")
def test_database(db: Session = Depends(get_db)):
    try:
        resultado = db.execute(text("SELECT 1")).scalar()
        if resultado == 1:
            return {"status": "ok", "message": "¡Conexión a PostgreSQL 100% operativa!"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error conectando a la BD: {str(e)}")

@router.post("/servicios/", response_model=ServicioResponse, status_code=201)
def crear_servicio(servicio: ServicioCreate, db: Session = Depends(get_db)):
    try:
        return crud.create_servicio(db=db, servicio=servicio)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error creando servicio: {str(e)}")

@router.get("/webhook")
def verificar_webhook(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_challenge: str = Query(None, alias="hub.challenge"),
    hub_verify_token: str = Query(None, alias="hub.verify_token")
):
    from src.core.config import settings
    if hub_mode == "subscribe" and hub_verify_token == settings.WHATSAPP_VERIFY_TOKEN:
        return int(hub_challenge)
    raise HTTPException(status_code=403, detail="Token de verificación inválido")

@router.post("/webhook")
async def recibir_mensaje(request: Request, db: Session = Depends(get_db)):
    """
    Endpoint que recibe los mensajes de WhatsApp, registra al paciente y responde.
    """
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
                
                NEGOCIO_ID_TEST = "c656d4c9-c2de-41cc-88f1-c8053809d84f"
                
                # 1. Registramos o recuperamos al paciente en PostgreSQL
                paciente = crud.obtener_o_crear_paciente(
                    db=db, 
                    negocio_id=NEGOCIO_ID_TEST, 
                    telefono=telefono_paciente,
                    nombre=nombre_perfil
                )
                
                print(f"🟢 IN: PACIENTE {paciente.nombre} DICE: {texto_mensaje}")
                
                # 2. COMPROBAMOS LA MEMORIA DEL PACIENTE
                estado_actual = obtener_estado(telefono_paciente)
                print(f"🗂️ ESTADO ACTUAL: {estado_actual}")
                
                # 3. MÁQUINA DE ESTADOS (FLUJO DE CONVERSACIÓN)
                if estado_actual == "ESPERANDO_SERVICIO":
                    servicios = crud.obtener_servicios_activos(db, NEGOCIO_ID_TEST)
                    if servicios:
                        servicio_elegido = servicios[0] 
                        guardar_dato_reserva(telefono_paciente, "servicio_id", servicio_elegido.id)
                        
                        respuesta = f"¡Anotado, {paciente.nombre}! 📝 Has elegido '*{servicio_elegido.nombre}*'.\n\n¿Qué día y hora te viene bien? (Ej: Mañana a las 18:00)"
                        actualizar_estado(telefono_paciente, "ESPERANDO_FECHA")
                    
                elif estado_actual == "ESPERANDO_FECHA":
                    servicio_id = obtener_dato_reserva(telefono_paciente, "servicio_id")
                    
                    # Guardamos en Supabase
                    nueva_cita = crud.crear_cita(
                        db=db, paciente_id=paciente.id, negocio_id=NEGOCIO_ID_TEST,
                        servicio_id=servicio_id, notas_fecha=texto_mensaje 
                    )
                    
                    # Guardamos en Google Calendar
                    enlace = crear_evento_calendario(paciente.nombre, "Servicio Reservado", texto_mensaje)
                    
                    respuesta = f"¡Hecho! 🎉 He guardado tu cita formalmente para: *{texto_mensaje}*."
                    if enlace:
                        respuesta += f"\nRevisa tu calendario."
                    
                    # IMPORTANTE: Esto solo se ejecuta al terminar la reserva
                    limpiar_estado(telefono_paciente)
                    
                else:
                    # ESTADO 'INICIO'
                    intencion = analizar_intencion(texto_mensaje)
                    
                    if intencion == "RESERVAR":
                        servicios = crud.obtener_servicios_activos(db, NEGOCIO_ID_TEST)
                        if servicios:
                            respuesta = f"¡Perfecto {paciente.nombre}! Aquí tienes nuestros servicios:\n\n"
                            for i, s in enumerate(servicios, 1):
                                respuesta += f"*{i}. {s.nombre}* - {s.precio}€\n"
                            respuesta += "\n¿Cuál te gustaría reservar? (Dime el número)"
                            
                            actualizar_estado(telefono_paciente, "ESPERANDO_SERVICIO")
                        else:
                            respuesta = "No hay servicios disponibles."
                            
                    elif intencion == "CANCELAR":
                        respuesta = generar_respuesta_base(intencion, paciente.nombre)
                        limpiar_estado(telefono_paciente)
                    else:
                        respuesta = generar_respuesta_base(intencion, paciente.nombre)
                
                # 4. ENVIAR AL MÓVIL
                await enviar_mensaje_texto(telefono_destino=telefono_paciente, texto=respuesta)

        return {"status": "success"}

    except Exception as e:
        print(f"🔴 Error procesando webhook: {e}")
        return {"status": "error_ignorado"}