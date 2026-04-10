from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# Ajusta la ruta de importación de tu base de datos si es diferente
from app.core.database import get_db

# Creamos el router específico para esta ruta
router = APIRouter(tags=["health"])

@router.get("/health")
async def health_check(db: AsyncSession = Depends(get_db)):
    try:
        await db.execute(text("SELECT 1"))
        db_status = "ok"
    except Exception as e:
        db_status = "error_conexion"
        print(f"Error en Health Check de DB: {e}")

    return {
        "status": "ok",
        "service": "Gema Bot",
        "database": db_status
    }