from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # DB (Supabase / PostgreSQL)
    DATABASE_URL: str

    # Contexto multi-tenant / default timezone
    DEFAULT_TIMEZONE: str = "Europe/Madrid"

    # Google Calendar
    GOOGLE_CALENDAR_SERVICE_ACCOUNT_FILE: str | None = None
    GOOGLE_CALENDAR_APPLICATION_NAME: str = "WhatsApp Booking SaaS"

    # WhatsApp Cloud API (Meta)
    WHATSAPP_ACCESS_TOKEN: str | None = None
    WHATSAPP_VERIFY_TOKEN: str | None = None
    WHATSAPP_PHONE_NUMBER_ID: str | None = None

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache()
def get_settings() -> Settings:
    return Settings()

