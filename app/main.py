from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.v1.router import api_router
from app.api.v1.endpoints.webhook import router as webhook_router
from app.api.v1.endpoints.admin import router as admin_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # En producción normalmente se usarían migraciones (Alembic).
    yield


app = FastAPI(
    title="WhatsApp Booking SaaS",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(api_router, prefix="/api/v1")
app.include_router(webhook_router)
app.include_router(admin_router)

