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
    "preferences": {},
}


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
    except OSError:
        return merged

    return merged


def load_settings(preference_file: Path | None = None) -> dict[str, Any]:
    """Load persisted UI settings and preferences."""

    settings = _load_web_settings()
    settings["preferences"] = _load_preferences(preference_file)
    return settings


def save_settings(payload: Dict[str, Any], preference_file: Path | None = None) -> dict[str, Any]:
    """Persist the provided settings payload to disk."""

    settings = _load_web_settings()

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

    try:
        SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        SETTINGS_FILE.write_text(json.dumps(settings, indent=2, sort_keys=True))
    except OSError:
        # If the settings cannot be saved, return the in-memory representation
        # so the caller can at least continue using the updated values.
        return settings

    return settings
