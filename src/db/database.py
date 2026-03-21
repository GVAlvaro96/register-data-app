from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from src.core.config import settings

# 1. Creamos el motor de conexión
engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True)

# 2. Creamos la fábrica de sesiones (las transacciones individuales)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# 3. Base para nuestros futuros modelos
Base = declarative_base()

# Dependencia para FastAPI: nos da una sesión de DB por cada petición web
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()