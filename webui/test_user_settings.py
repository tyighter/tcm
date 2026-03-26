from pathlib import Path

import pytest

from webui import user_settings


def test_save_settings_raises_when_preferences_write_fails(tmp_path, monkeypatch) -> None:
    settings_file = tmp_path / "web-settings.json"
    preference_file = tmp_path / "preferences.yml"

    monkeypatch.setattr(user_settings, "SETTINGS_FILE", settings_file)

    def _raise_preferences_error(*_args, **_kwargs):
        raise user_settings.SettingsPersistenceError(
            "Unable to write preferences file",
            remediation="Fix permissions and retry.",
        )

    monkeypatch.setattr(user_settings, "_save_preferences", _raise_preferences_error)

    with pytest.raises(user_settings.SettingsPersistenceError) as exc_info:
        user_settings.save_settings({"preferences": {"webui": {"setup_complete": True}}}, preference_file)

    assert "preferences file" in str(exc_info.value)
    assert exc_info.value.remediation == "Fix permissions and retry."


def test_save_settings_raises_when_web_settings_write_fails(tmp_path, monkeypatch) -> None:
    unwritable_path = tmp_path / "web-settings.json"
    unwritable_path.mkdir()
    preference_file = tmp_path / "preferences.yml"

    monkeypatch.setattr(user_settings, "SETTINGS_FILE", unwritable_path)

    with pytest.raises(user_settings.SettingsPersistenceError) as exc_info:
        user_settings.save_settings({"series_sync_interval_seconds": 12}, preference_file)

    assert str(Path("/config")) not in str(exc_info.value)
    assert "Unable to write UI settings file" in str(exc_info.value)
    assert "writable" in exc_info.value.remediation
