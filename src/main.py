from fastapi import FastAPI
from src.api import routes

# Inicializamos la aplicación FastAPI
app = FastAPI(
    title="Register Data App",
    description="API multi-tenant para gestión de citas por WhatsApp",
    version="1.0.0"
)

# Conectamos nuestro archivo de rutas (endpoints) al servidor principal
app.include_router(routes.router)