import urllib.parse
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    DB_USER: str
    DB_PASSWORD: str
    DB_NAME: str
    DB_HOST: str
    DB_PORT: str

    # Nuevo: Token de seguridad para el Webhook de Meta
    WHATSAPP_VERIFY_TOKEN: str 
    WHATSAPP_PHONE_NUMBER_ID: str
    WHATSAPP_API_TOKEN: str
    
    GOOGLE_CALENDAR_ID: str

    @property
    def DATABASE_URL(self) -> str:
        # Codificamos la contraseña para que los caracteres especiales (@, #, etc.) no rompan la URL
        encoded_password = urllib.parse.quote_plus(self.DB_PASSWORD)
        return f"postgresql://{self.DB_USER}:{encoded_password}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}?sslmode=require"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

# Instanciamos la configuración para importarla en el resto de la app
settings = Settings()