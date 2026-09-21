from __future__ import annotations

import pytest

from config import (
    ConfigurationError,
    Settings,
    configuration_warnings,
    validate_runtime_configuration,
)


def test_empty_optional_numeric_environment_values_use_defaults(monkeypatch):
    monkeypatch.setenv("RADAR_TRACKING_STALE_AFTER_HOURS", "")
    monkeypatch.setenv("RADAR_BACKFILL_MAX_PAGES", "")

    settings = Settings(_env_file=None)

    assert settings.tracking_stale_after_hours is None
    assert settings.backfill_max_pages is None


def test_production_validation_rejects_insecure_defaults():
    production = Settings(
        _env_file=None,
        environment="production",
        github_token="token",
        cors_origins=["*"],
    )

    warnings = configuration_warnings(production)
    assert "API authentication is disabled" in warnings
    assert "read API key is not configured" in warnings
    with pytest.raises(ConfigurationError):
        validate_runtime_configuration(production)


def test_production_validation_accepts_explicit_keys_and_origins():
    production = Settings(
        _env_file=None,
        environment="production",
        github_token="configured",
        api_auth_enabled=True,
        api_key="read-key",
        admin_api_key="admin-key",
        cors_origins=["https://radar.example.test"],
        log_format="json",
    )

    assert configuration_warnings(production) == []
    validate_runtime_configuration(production)
