from sqlalchemy.orm import Session, joinedload
from sqlalchemy.exc import IntegrityError
from src.db import models

# ==========================================
# GESTIÓN DE PACIENTES
# ==========================================
def obtener_o_crear_paciente(db: Session, negocio_id: str, telefono: str, nombre: str = None):
    """
    Busca un paciente por su teléfono. Si no existe, lo crea.
    """
    paciente = db.query(models.Paciente).filter(
        models.Paciente.negocio_id == negocio_id,
        models.Paciente.telefono == telefono
    ).first()

    if not paciente:
        # El paciente es nuevo, lo preparamos para insertar
        paciente = models.Paciente(negocio_id=negocio_id, telefono=telefono, nombre=nombre)
        db.add(paciente)
        try:
            db.commit()
            db.refresh(paciente) # Refrescamos para obtener el ID (UUID) autogenerado
        except IntegrityError:
            db.rollback()
            # Manejo de concurrencia: si otro hilo insertó este paciente en este 
            # exacto milisegundo, el UNIQUE constraint fallará. Hacemos rollback y lo buscamos.
            paciente = db.query(models.Paciente).filter_by(negocio_id=negocio_id, telefono=telefono).first()
    
    return paciente

# ==========================================
# GESTIÓN DE CITAS
# ==========================================
def obtener_citas_del_dia(db: Session, negocio_id: str, fecha_inicio, fecha_fin):
    """
    Obtiene todas las citas de un negocio en un rango de fechas.
    Implementa 'joinedload' para resolver el problema N+1.
    """
    return db.query(models.Cita).options(
        joinedload(models.Cita.paciente),
        joinedload(models.Cita.servicio)
    ).filter(
        models.Cita.negocio_id == negocio_id,
        models.Cita.fecha_hora >= fecha_inicio,
        models.Cita.fecha_hora <= fecha_fin
    ).all()