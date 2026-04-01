from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict

from yaml import safe_dump, safe_load

SETTINGS_FILE = Path("/config/web-settings.json")

_DEFAULT_SETTINGS = {
    "tautulli": {
        "url": "",
        "api_key": "",
        "verify_ssl": True,
        "user_id": "",
    },
    "series_sync_interval_seconds": 45,
    "entry_visibility_default_mode": "basic",
    "preview_cache_sweep_interval_seconds": 900,
    "prewarm_previews": True,
    "onboarding": {
        "dismissed": False,
        "completed_steps": {
            "set_preferences": False,
            "add_first_series": False,
            "preview_card": False,
            "save_config": False,
            "run_build": False,
        },
    },
    "preferences": {},
}


class SettingsPersistenceError(RuntimeError):
    """Raised when UI settings could not be persisted to disk."""

    def __init__(self, message: str, *, remediation: str) -> None:
        super().__init__(message)
        self.remediation = remediation


def _merged_settings(data: dict[str, Any] | None) -> dict[str, Any]:
    merged = deepcopy(_DEFAULT_SETTINGS)
    if not isinstance(data, dict):
        return merged

    tautulli = data.get("tautulli", {})
    if isinstance(tautulli, dict):
        merged["tautulli"].update(
            {
                key: tautulli.get(key, merged["tautulli"][key])
                for key in ("url", "api_key", "verify_ssl", "user_id")
            }
        )

    interval = data.get("series_sync_interval_seconds")
    if isinstance(interval, (int, float)):
        merged["series_sync_interval_seconds"] = max(0, int(interval))

    sweep_interval = data.get("preview_cache_sweep_interval_seconds")
    if isinstance(sweep_interval, (int, float)):
        merged["preview_cache_sweep_interval_seconds"] = max(0, int(sweep_interval))

    prewarm_previews = data.get("prewarm_previews")
    if isinstance(prewarm_previews, bool):
        merged["prewarm_previews"] = prewarm_previews

    visibility_mode = data.get("entry_visibility_default_mode")
    if visibility_mode in {"basic", "advanced"}:
        merged["entry_visibility_default_mode"] = visibility_mode

    onboarding = data.get("onboarding")
    if isinstance(onboarding, dict):
        merged["onboarding"]["dismissed"] = bool(
            onboarding.get("dismissed", merged["onboarding"]["dismissed"])
        )
        completed_steps = onboarding.get("completed_steps")
        if isinstance(completed_steps, dict):
            for step in merged["onboarding"]["completed_steps"]:
                merged["onboarding"]["completed_steps"][step] = bool(
                    completed_steps.get(
                        step,
                        merged["onboarding"]["completed_steps"][step],
                    )
                )

    return merged


def _load_web_settings() -> dict[str, Any]:
    if not SETTINGS_FILE.exists():
        return deepcopy(_DEFAULT_SETTINGS)

    try:
        data = json.loads(SETTINGS_FILE.read_text())
    except (OSError, ValueError):
        return deepcopy(_DEFAULT_SETTINGS)

    return _merged_settings(data)


def _load_preferences(preference_file: Path | None) -> dict[str, Any]:
    if not preference_file or not preference_file.exists():
        return {}

    try:
        loaded = safe_load(preference_file.read_text()) or {}
    except (OSError, ValueError):
        return {}

    return loaded if isinstance(loaded, dict) else {}


def _coerce_value(new_value: Any, current_value: Any) -> Any:
    if isinstance(current_value, bool):
        return bool(new_value)

    if isinstance(current_value, int) and not isinstance(current_value, bool):
        try:
            return int(str(new_value).strip())
        except (TypeError, ValueError):
            return current_value

    if isinstance(current_value, float):
        try:
            return float(str(new_value).strip())
        except (TypeError, ValueError):
            return current_value

    if isinstance(current_value, list):
        if isinstance(new_value, list):
            return new_value
        if isinstance(new_value, str):
            return [item.strip() for item in new_value.split(",") if item.strip()]
        return []

    return new_value


def _merge_preferences(existing: dict[str, Any], updates: dict[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = deepcopy(existing)

    for key, value in updates.items():
        if isinstance(value, dict):
            base_value = merged.get(key) if isinstance(merged.get(key), dict) else {}
            merged[key] = _merge_preferences(base_value, value)
            continue

        merged[key] = _coerce_value(value, merged.get(key))

    return merged


def _save_preferences(preference_file: Path, updates: dict[str, Any]) -> dict[str, Any]:
    current_preferences = _load_preferences(preference_file)
    merged = _merge_preferences(current_preferences, updates)

    try:
        preference_file.parent.mkdir(parents=True, exist_ok=True)
        preference_file.write_text(safe_dump(merged, sort_keys=False))
    except OSError as exc:
        raise SettingsPersistenceError(
            f"Unable to write preferences file at {preference_file}: {exc}",
            remediation=(
                "Check that the preferences path exists and is writable, then retry saving settings."
            ),
        ) from exc

    return merged


def load_settings(preference_file: Path | None = None) -> dict[str, Any]:
    """Load persisted UI settings and preferences."""

    settings = _load_web_settings()
    settings["preferences"] = _load_preferences(preference_file)
    return settings


def save_settings(payload: Dict[str, Any], preference_file: Path | None = None) -> dict[str, Any]:
    """Persist the provided settings payload to disk."""

    settings = _load_web_settings()

    interval = payload.get("series_sync_interval_seconds", settings["series_sync_interval_seconds"])
    try:
        settings["series_sync_interval_seconds"] = max(
            0, int(str(interval).strip())
        )
    except (TypeError, ValueError):
        settings["series_sync_interval_seconds"] = _DEFAULT_SETTINGS["series_sync_interval_seconds"]

    sweep_interval = payload.get(
        "preview_cache_sweep_interval_seconds",
        settings["preview_cache_sweep_interval_seconds"],
    )
    try:
        settings["preview_cache_sweep_interval_seconds"] = max(0, int(str(sweep_interval).strip()))
    except (TypeError, ValueError):
        settings["preview_cache_sweep_interval_seconds"] = _DEFAULT_SETTINGS[
            "preview_cache_sweep_interval_seconds"
        ]

    settings["prewarm_previews"] = bool(
        payload.get("prewarm_previews", settings.get("prewarm_previews", True))
    )

    visibility_mode = payload.get(
        "entry_visibility_default_mode",
        settings["entry_visibility_default_mode"],
    )
    settings["entry_visibility_default_mode"] = (
        visibility_mode if visibility_mode in {"basic", "advanced"} else "basic"
    )

    tautulli = payload.get("tautulli")
    if isinstance(tautulli, dict):
        settings["tautulli"].update(
            {
                "url": str(tautulli.get("url", settings["tautulli"]["url"])).strip(),
                "api_key": str(tautulli.get("api_key", settings["tautulli"]["api_key"])).strip(),
                "verify_ssl": bool(tautulli.get("verify_ssl", settings["tautulli"]["verify_ssl"])),
                "user_id": str(tautulli.get("user_id", settings["tautulli"]["user_id"])).strip(),
            }
        )

    preferences_payload = payload.get("preferences")
    preferences: dict[str, Any] = {}
    if isinstance(preferences_payload, dict) and preference_file:
        preferences = _save_preferences(preference_file, preferences_payload)
    elif preference_file:
        preferences = _load_preferences(preference_file)

    settings["preferences"] = preferences

    onboarding_payload = payload.get("onboarding")
    if isinstance(onboarding_payload, dict):
        settings["onboarding"]["dismissed"] = bool(
            onboarding_payload.get("dismissed", settings["onboarding"]["dismissed"])
        )

        completed_steps_payload = onboarding_payload.get("completed_steps")
        if isinstance(completed_steps_payload, dict):
            for step in settings["onboarding"]["completed_steps"]:
                settings["onboarding"]["completed_steps"][step] = bool(
                    completed_steps_payload.get(
                        step,
                        settings["onboarding"]["completed_steps"][step],
                    )
                )

    try:
        SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        SETTINGS_FILE.write_text(json.dumps(settings, indent=2, sort_keys=True))
    except OSError as exc:
        raise SettingsPersistenceError(
            f"Unable to write UI settings file at {SETTINGS_FILE}: {exc}",
            remediation="Ensure /config is writable and has free space, then retry.",
        ) from exc

    return {**settings, "_persisted": True}
