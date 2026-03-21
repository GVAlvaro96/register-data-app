from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    DB_USER: str
    DB_PASSWORD: str
    DB_NAME: str
    # En local (Docker), la base de datos está en localhost.
    DB_HOST: str = "127.0.0.1" 
    DB_PORT: str = "5432"

    @property
    def DATABASE_URL(self) -> str:
        # Construye la URL de conexión que necesita SQLAlchemy
        return f"postgresql://{self.DB_USER}:{self.DB_PASSWORD}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

# Instanciamos la configuración para importarla en el resto de la app
settings = Settings()