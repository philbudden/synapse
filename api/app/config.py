from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    postgres_host: str = "postgres"
    postgres_port: int = 5432
    postgres_db: str = "synapse"
    postgres_user: str = "synapse"
    postgres_password: str = "synapse"

    ollama_host: str = "host.docker.internal"
    ollama_port: int = 11434
    embed_model: str = "nomic-embed-text"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def postgres_dsn(self) -> str:
        user = self.postgres_user
        pw = self.postgres_password
        host = self.postgres_host
        port = self.postgres_port
        db = self.postgres_db
        return f"postgresql://{user}:{pw}@{host}:{port}/{db}"

    @property
    def ollama_base_url(self) -> str:
        return f"http://{self.ollama_host}:{self.ollama_port}"


settings = Settings()
