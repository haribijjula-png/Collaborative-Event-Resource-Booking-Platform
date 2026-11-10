from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    DATABASE_URL: str = "postgresql+psycopg://app:app@localhost:5432/eventdb"
    TEST_DATABASE_URL: str = "postgresql+psycopg://app:app@localhost:5432/eventdb_test"
    SECRET_KEY: str = "dev-secret-change-me-dev-secret-change-me"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    UPLOAD_DIR: str = "./uploads"
    MAX_UPLOAD_MB: int = 10
    CORS_ORIGINS: str = "http://localhost:5173"
    SUPERADMIN_EMAIL: str = "admin@example.com"
    SUPERADMIN_PASSWORD: str = "ChangeMe123!"
    SUPERADMIN_USERNAME: str = "superadmin"
    REMINDER_LEAD_MINUTES: int = 60
    ENABLE_SCHEDULER: bool = True
    BCRYPT_ROUNDS: int = 12


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
