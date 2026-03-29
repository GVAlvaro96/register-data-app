from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from src.db.models import Servicio, Paciente,Cita, Negocio
from src.schemas import ServicioCreate
from uuid import UUID
from datetime import datetime

def create_servicio(db: Session, servicio: ServicioCreate):
    """Inserta un nuevo servicio en la base de datos."""
    db_servicio = Servicio(
        negocio_id=servicio.negocio_id,
        nombre=servicio.nombre,
        duracion_minutos=servicio.duracion_minutos,
        precio=servicio.precio,
        activo=servicio.activo
    )
    db.add(db_servicio)
    db.commit()
    db.refresh(db_servicio) # Refrescamos para obtener el UUID autogenerado
    return db_servicio

def obtener_o_crear_paciente(db: Session, negocio_id: str | UUID, telefono: str, nombre: str = None):
    """
    Busca un paciente por su teléfono en un negocio específico. 
    Si no existe (es su primer mensaje), lo crea automáticamente.
    """
    paciente = db.query(Paciente).filter(
        Paciente.negocio_id == negocio_id,
        Paciente.telefono == telefono
    ).first()

    if not paciente:
        # El paciente es nuevo, lo preparamos para insertar
        paciente = Paciente(negocio_id=negocio_id, telefono=telefono, nombre=nombre)
        db.add(paciente)
        try:
            db.commit()
            db.refresh(paciente)
        except IntegrityError:
            db.rollback()
            # Manejo de concurrencia (Race condition)
            paciente = db.query(Paciente).filter_by(negocio_id=negocio_id, telefono=telefono).first()
    
    return paciente

def obtener_servicios_activos(db: Session, negocio_id: str | UUID):
    """Obtiene todos los servicios activos de un negocio."""
    return db.query(Servicio).filter(
        Servicio.negocio_id == negocio_id,
        Servicio.activo == True
    ).all()


def crear_cita(db: Session, paciente_id: str, negocio_id: str, servicio_id: str, fecha_hora: datetime, notas: str = None, google_event_id: str = None):
    nueva_cita = Cita(
        paciente_id=paciente_id, 
        negocio_id=negocio_id, 
        servicio_id=servicio_id, 
        fecha_hora=fecha_hora,        # <--- Guardamos la hora exacta
        notas=notas,                  # <--- Guardamos el texto (ej. "el viernes a las 11")
        google_event_id=google_event_id, # <--- Usamos el ID de Google
        estado="PENDIENTE"            # <--- Estado por defecto de tu modelo
    )
    db.add(nueva_cita)
    db.commit()
    db.refresh(nueva_cita)
    return nueva_cita

def obtener_citas_pendientes(db: Session, paciente_id: str, negocio_id: str):
    return db.query(Cita).filter(
        Cita.paciente_id == paciente_id,
        Cita.negocio_id == negocio_id,
        Cita.estado == 'PENDIENTE'   # <--- Buscamos solo las activas
    ).all()

def cancelar_cita(db: Session, cita_id: str):
    cita = db.query(Cita).filter(Cita.id == cita_id).first()
    if cita:
        cita.estado = 'CANCELADA'
        db.commit()
    return cita

def obtener_servicio_por_id(db: Session, servicio_id: str):
    return db.query(Servicio).filter(Servicio.id == servicio_id).first()

def obtener_negocio_por_telefono(db: Session, telefono_bot: str):
    """Busca a qué negocio pertenece el número de WhatsApp receptor."""
    return db.query(Negocio).filter(Negocio.telefono_bot == telefono_bot).first()