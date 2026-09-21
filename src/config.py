from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="RADAR_",
        extra="ignore",
        env_ignore_empty=True,
    )

    environment: str = "development"
    github_token: str = ""
    api_base_url: str = "https://api.github.com"
    request_timeout: float = 30.0
    user_agent: str = "github-radar/0.9"
    max_retries: int = 3
    backoff_base: float = 1.0
    backoff_max: float = 60.0
    github_rate_limit_warning_remaining: int = 100
    database_url: str = "sqlite+aiosqlite:///./radar.db"
    api_prefix: str = "/api/v1"
    cors_origins: list[str] = ["*"]
    api_auth_enabled: bool = False
    api_key: str = ""
    admin_api_key: str = ""

    analytics_rolling_window: int = 14
    analytics_burst_z: float = 2.5
    analytics_burst_min_delta: int = 5
    analytics_burst_min_days: int = 2
    analytics_history_days: int = 180

    scheduler_enabled: bool = False
    scheduler_interval_hours: int = 24
    tracking_stale_after_hours: float | None = None
    backfill_max_pages: int | None = None
    worker_lock_ttl_seconds: int = 900
    worker_retry_attempts: int = 3
    worker_retry_backoff_seconds: float = 5.0

    alerts_enabled: bool = True
    alert_webhook_url: str = ""
    alert_webhook_timeout_seconds: float = 10.0
    webhook_max_attempts: int = 5
    webhook_backoff_base_seconds: float = 1.0
    webhook_disable_after_failures: int = 5
    webhook_signing_secret: str = ""
    webhook_provider: str = "generic"

    metrics_enabled: bool = True
    log_level: str = "INFO"
    log_format: str = "text"


settings = Settings()
