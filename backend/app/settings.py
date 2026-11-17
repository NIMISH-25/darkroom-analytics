from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    DATABASE_URL: str = "postgresql://darkroom:darkroom@localhost:5432/darkroom"
    # Plain comma-separated string on purpose (not a list type).
    CORS_ORIGINS: str = "http://localhost:3000,http://127.0.0.1:3000"
    AUTH_SECRET: str = "dev-only-secret-change-me-0123456789abcdef"
    AUTH_TOKEN_TTL_MINUTES: int = 480
    DEMO_USERNAME: str = "demo"
    DEMO_PASSWORD: str = "darkroom-demo"
    PORT: int = 8000

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
