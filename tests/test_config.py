from __future__ import annotations

from config import Settings


def test_empty_optional_numeric_environment_values_use_defaults(monkeypatch):
    monkeypatch.setenv("RADAR_TRACKING_STALE_AFTER_HOURS", "")
    monkeypatch.setenv("RADAR_BACKFILL_MAX_PAGES", "")

    settings = Settings(_env_file=None)

    assert settings.tracking_stale_after_hours is None
    assert settings.backfill_max_pages is None
