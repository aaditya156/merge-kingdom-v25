from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    PROJECT_NAME: str = "Merge Kingdom 2.5 API"
    API_V1_STR: str = "/api/v1"
    ENVIRONMENT: str = "development"
    DEBUG: bool = True

    # Database
    DATABASE_URL: str = "sqlite+aiosqlite:///./merge_kingdom.db"

    # JWT Security
    SECRET_KEY: str = "development_secret_key_change_in_production_jwt_signing"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440

    # Game Economy Parameters
    CONVERSION_RATIO_COINS_TO_GEMS: float = 1.0
    FREE_GEM_BONUS: int = 0

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )


settings = Settings()
