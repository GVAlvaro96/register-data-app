# app/services/state_machine.py
import pytz
from datetime import datetime
from typing import Any
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.negocio_repository import negocio_repository
from app.repositories.bot_state_repository import bot_estado_repository
from app.repositories.servicio_repository import servicio_repository
from app.repositories.cita_repository import cita_repository
from app.models.bot_state import BotEstado

# Importaciones de nuestro nuevo cerebro modular
from app.bot.intent_parser import normalize_text, detect_intent
from app.bot.admin_handlers import process_admin_message
from app.bot.user_handlers import (
    handle_esperando_servicio,
    handle_esperando_empleado,
    handle_esperando_fecha,
    handle_esperando_cancelacion,
    handle_esperando_clase_grupal 
)

class WhatsAppStateMachine:
    async def process_message(
        self, db: AsyncSession, *, telefono_sender: str, texto_mensaje: str,
        negocio_id: Any, paciente_nombre: str | None = None, now_utc: datetime | None = None,
    ) -> dict[str, Any]:
        
        negocio = await negocio_repository.get(db, negocio_id)
        if not negocio:
            return {"reply_text": "Negocio no configurado.", "next_estado": "None"}

        tz = pytz.timezone(negocio.zona_horaria or "Europe/Madrid")
        now_local = (now_utc or datetime.utcnow().replace(tzinfo=pytz.UTC)).astimezone(tz)

        # =================================
        # INTERCEPTOR: MODO ADMIN
        # =================================
        if getattr(negocio, 'telefono_admin', None) and telefono_sender == negocio.telefono_admin:
            state = await bot_estado_repository.get_by_telefono(db, telefono_sender) or BotEstado(estado="ADMIN_NONE")
            return await process_admin_message(db, telefono_sender, texto_mensaje, negocio, now_utc, tz, state, normalize_text(texto_mensaje))

        # =================================
        # CARGA DEL ESTADO (USUARIO NORMAL)
        # =================================
        state = await bot_estado_repository.get_by_telefono(db, telefono_sender)
        if not state:
            state = await bot_estado_repository.upsert(db, telefono=telefono_sender, defaults={"estado": "None"})
        
        t_norm = normalize_text(texto_mensaje)

        # =================================
        # ENRUTADOR PRINCIPAL (ROUTER)
        # =================================
        if state.estado == "None":
            intencion = detect_intent(t_norm)
            
            if intencion == "RESERVAR":
                servicios = await servicio_repository.list_by_negocio(db, negocio.id)
                if not servicios:
                    return {"reply_text": "No hay servicios disponibles ahora.", "next_estado": "None"}
                    
                await bot_estado_repository.upsert(db, telefono=telefono_sender, defaults={"estado": "ESPERANDO_SERVICIO", "cancelacion_citas_ids": None})
                menu = "\n".join([f"{i+1}️⃣ {s.nombre}" for i, s in enumerate(servicios)])
                return {"reply_text": f"¿Qué te vas a hacer hoy?\n(Responde solo con el número)\n\n{menu}", "next_estado": "ESPERANDO_SERVICIO"}
            
            elif intencion == "CANCELAR":
                citas_actives = await cita_repository.list_actives_by_negocio(db, negocio.id)
                citas_actives = [c for c in citas_actives if c.calendar_event_id]
                if not citas_actives:
                    return {"reply_text": "No tienes citas activas para cancelar en este momento.", "next_estado": "None"}

                citas_ids = [str(c.id) for c in citas_actives]
                await bot_estado_repository.upsert(
                    db, telefono=telefono_sender,
                    defaults={"estado": "ESPERANDO_CANCELACION", "cancelacion_citas_ids": citas_ids}
                )
                lista = "\n".join([f"{i+1}. {c.fecha_hora.astimezone(tz).strftime('%d/%m/%Y %H:%M')}" for i, c in enumerate(citas_actives)])
                return {"reply_text": f"Selecciona la cita a cancelar:\n{lista}\nResponde con el número.", "next_estado": "ESPERANDO_CANCELACION"}
            
            elif intencion == "SALUDAR":
                nombre = paciente_nombre or "amigo"
                mensaje = (f"¡Hola {nombre}! 👋 Bienvenido a {negocio.nombre_negocio}.\n\n"
                           f"¿En qué te puedo ayudar hoy?\n"
                           f"📅 Responde *Reservar* para coger una cita o apuntarte a una clase.\n"
                           f"❌ Responde *Cancelar* si necesitas anular tu reserva.")
                return {"reply_text": mensaje, "next_estado": "None"}
                
            else:
                return {"reply_text": "¡Uy, creo que no te he entendido bien! 😅\nDime si necesitas *coger cita* o *anular* la que ya tienes.", "next_estado": "None"}

        # Delegación a los manejadores de estado
        elif state.estado == "ESPERANDO_SERVICIO":
            return await handle_esperando_servicio(db, t_norm, texto_mensaje, negocio, state, telefono_sender)
            
        elif state.estado == "ESPERANDO_EMPLEADO":
            return await handle_esperando_empleado(db, t_norm, negocio, state, telefono_sender, now_local, tz)
            
        elif state.estado == "ESPERANDO_FECHA":
            return await handle_esperando_fecha(db, texto_mensaje, negocio, state, telefono_sender, paciente_nombre, now_local, tz)
            
        elif state.estado == "ESPERANDO_CANCELACION":
            return await handle_esperando_cancelacion(db, t_norm, negocio, state, telefono_sender)

        elif state.estado == "ESPERANDO_CLASE_GRUPAL":
            # Llamamos a la función real que guarda la cita
            return await handle_esperando_clase_grupal(db, t_norm, negocio, state, telefono_sender, paciente_nombre, tz)

        # Fallback de seguridad global
        return {"reply_text": "Ha ocurrido un error en la conversación. Escribe 'Reservar' o 'Cancelar' para empezar de nuevo.", "next_estado": "None"}

# Instancia global (Singleton)
state_machine = WhatsAppStateMachine()