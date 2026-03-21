from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
from src.db.database import get_db

router = APIRouter()

@router.get("/")
def read_root():
    return {"mensaje": "Bienvenido a Register Data App API"}

@router.get("/health")
def health_check():
    """Endpoint vital para que el servidor Cloud sepa que la app no se ha caído."""
    return {"status": "ok", "version": "1.0.0"}

@router.get("/test-db")
def test_database(db: Session = Depends(get_db)):
    """Endpoint temporal para probar que SQLAlchemy llega a PostgreSQL."""
    try:
        # Ejecutamos un simple "SELECT 1" para comprobar la conexión
        resultado = db.execute(text("SELECT 1")).scalar()
        if resultado == 1:
            return {"status": "ok", "message": "¡Conexión a PostgreSQL 100% operativa!"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error conectando a la BD: {str(e)}")
        