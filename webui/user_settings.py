from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict

SETTINGS_FILE = Path("/config/web-settings.json")

_DEFAULT_SETTINGS = {
    "tautulli": {
        "url": "",
        "api_key": "",
        "verify_ssl": True,
    }
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
                for key in ("url", "api_key", "verify_ssl")
            }
        )

    return merged


def load_settings() -> dict[str, Any]:
    """Load persisted UI settings from disk, falling back to defaults."""

    if not SETTINGS_FILE.exists():
        return deepcopy(_DEFAULT_SETTINGS)

    try:
        data = json.loads(SETTINGS_FILE.read_text())
    except (OSError, ValueError):
        return deepcopy(_DEFAULT_SETTINGS)

    return _merged_settings(data)


def save_settings(payload: Dict[str, Any]) -> dict[str, Any]:
    """Persist the provided settings payload to disk."""

    settings = _merged_settings(load_settings())

    tautulli = payload.get("tautulli")
    if isinstance(tautulli, dict):
        settings["tautulli"].update(
            {
                "url": str(tautulli.get("url", settings["tautulli"]["url"])).strip(),
                "api_key": str(tautulli.get("api_key", settings["tautulli"]["api_key"])).strip(),
                "verify_ssl": bool(tautulli.get("verify_ssl", settings["tautulli"]["verify_ssl"])),
            }
        )

    try:
        SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        SETTINGS_FILE.write_text(json.dumps(settings, indent=2, sort_keys=True))
    except OSError:
        # If the settings cannot be saved, return the in-memory representation
        # so the caller can at least continue using the updated values.
        return settings

    return settings
