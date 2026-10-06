import logging

from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


class ConfigurationError(ValueError):
    """Raised when a runtime configuration is unsafe or incomplete."""


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
    user_agent: str = "github-radar/1.0"
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
    max_request_bytes: int = 262_144

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
    webhook_allow_private_addresses: bool = False

    metrics_enabled: bool = True
    log_level: str = "INFO"
    log_format: str = "text"


def configuration_warnings(config: Settings | None = None) -> list[str]:
    active = config or settings
    warnings: list[str] = []
    if not active.api_auth_enabled:
        warnings.append("API authentication is disabled")
    if not active.api_key:
        warnings.append("read API key is not configured")
    if not active.admin_api_key:
        warnings.append("admin API key is not configured")
    if "*" in active.cors_origins:
        warnings.append("CORS allows every origin")
    if active.log_format.lower() not in {"text", "json"}:
        warnings.append("log format must be text or json")
    if active.webhook_max_attempts < 1:
        warnings.append("webhook max attempts must be at least 1")
    if active.environment.lower() in {"production", "prod"} and not active.github_token:
        warnings.append("GitHub token is not configured")
    if active.max_request_bytes < 1024:
        warnings.append("request size limit is unusually small")
    return warnings


def validate_runtime_configuration(config: Settings | None = None) -> None:
    active = config or settings
    if active.webhook_allow_private_addresses:
        logger.warning(
            "RADAR_WEBHOOK_ALLOW_PRIVATE_ADDRESSES is enabled: webhooks may target "
            "private or loopback addresses (cloud metadata endpoints stay blocked)"
        )
    if active.environment.lower() not in {"production", "prod"}:
        return

    problems = configuration_warnings(active)
    if problems:
        raise ConfigurationError("; ".join(problems))


settings = Settings()
