from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="RADAR_",
        extra="ignore",
    )

    github_token: str = ""
    api_base_url: str = "https://api.github.com"
    request_timeout: float = 30.0
    user_agent: str = "github-radar/0.4"
    max_retries: int = 3
    backoff_base: float = 1.0
    backoff_max: float = 60.0
    database_url: str = "sqlite+aiosqlite:///./radar.db"
    api_prefix: str = "/api/v1"
    cors_origins: list[str] = ["*"]


settings = Settings()
