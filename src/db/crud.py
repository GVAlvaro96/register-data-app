from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from src.db.models import Servicio, Paciente
from src.schemas import ServicioCreate
from uuid import UUID

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