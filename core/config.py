from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    database_url: str = "postgresql+asyncpg://taskman:taskman@localhost:5432/taskman"
    runner_grpc_addr: str = "localhost:50051"
    cors_origins: list[str] = ["*"]
    host: str = "0.0.0.0"
    port: int = 5000


settings = Settings()
