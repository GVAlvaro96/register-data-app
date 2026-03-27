from fastapi import APIRouter, Depends, HTTPException, Request, Query
from sqlalchemy.orm import Session
from sqlalchemy import text
from src.db.database import get_db
from src.schemas import ServicioCreate, ServicioResponse
from src.db import crud
from src.services.whatsapp import enviar_mensaje_texto

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
                
                # 2. RESPUESTA AUTOMÁTICA DEL BOT (Outbound)
                respuesta = f"¡Hola {paciente.nombre}! Soy GEMA, tu asistente virtual 🤖. He recibido tu mensaje: '{texto_mensaje}'. ¿Quieres reservar una cita para hoy?"
                
                await enviar_mensaje_texto(telefono_destino=telefono_paciente, texto=respuesta)

        return {"status": "success"}

    except Exception as e:
        print(f"🔴 Error procesando webhook: {e}")
        return {"status": "error_ignorado"}