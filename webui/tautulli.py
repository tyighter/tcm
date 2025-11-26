from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urljoin

import requests
import re

from .config import AppContext
from .tv_data import TvYamlManager, _to_builtin
from .user_settings import load_settings

TAUTULLI_LOG_FILE = Path("/config/tautulli.log")


def _configure_logger() -> logging.Logger:
    logger = logging.getLogger("tcm.tautulli")
    if getattr(logger, "_configured", False):
        return logger

    logger.setLevel(logging.INFO)
    logger.propagate = False

    try:
        TAUTULLI_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass

    try:
        handler = logging.FileHandler(TAUTULLI_LOG_FILE, mode="w")
    except OSError as exc:  # pragma: no cover - filesystem errors are environment specific
        logger.addHandler(logging.NullHandler())
        logger.warning("Unable to write Tautulli log to %s: %s", TAUTULLI_LOG_FILE, exc)
        return logger

    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logger.addHandler(handler)

    logger._configured = True  # type: ignore[attr-defined]
    logger.info("Tautulli log initialised at %s", TAUTULLI_LOG_FILE)
    return logger


tautulli_logger = _configure_logger()

_TRAILING_YEAR_PATTERNS = (
    re.compile(r"\s*\(\d{4}\)\s*$"),
    re.compile(r"\s+\d{4}\s*$"),
)


@dataclass
class TautulliSettings:
    url: str
    api_key: str
    verify_ssl: bool = True
    user_id: str | None = None

    @classmethod
    def from_settings(cls) -> "TautulliSettings | None":
        data = load_settings().get("tautulli", {})
        if not isinstance(data, dict):
            return None

        url = str(data.get("url", "")).strip()
        api_key = str(data.get("api_key", "")).strip()
        verify_ssl = bool(data.get("verify_ssl", True))
        user_id_raw = str(data.get("user_id", "")).strip()
        user_id = user_id_raw or None

        if not url or not api_key:
            return None

        return cls(url=url, api_key=api_key, verify_ssl=verify_ssl, user_id=user_id)

    def request(self, command: str, **params: Any) -> dict[str, Any]:
        base_params = {"cmd": command, "apikey": self.api_key}
        base_params.update(params)
        url = urljoin(self.url.rstrip("/") + "/", "api/v2")
        response = requests.get(url, params=base_params, verify=self.verify_ssl, timeout=15)
        response.raise_for_status()
        payload = response.json()
        if payload.get("response", {}).get("result") != "success":
            raise RuntimeError(f"Tautulli request for {command} failed: {payload}")
        return payload.get("response", {}).get("data", {})


def _normalize_timestamp(value: Any) -> int | None:
    try:
        numeric = int(value)
    except (TypeError, ValueError):
        return None

    # Convert seconds to milliseconds for consistency with JS Date()
    if numeric < 1e12:
        numeric *= 1000
    return numeric


def _series_aliases(title: str) -> list[str]:
    aliases: list[str] = []
    try:
        normalized = str(title)
    except Exception:
        return aliases

    normalized = normalized.strip()
    if not normalized:
        return aliases

    aliases.append(normalized.casefold())
    stripped = normalized
    for pattern in _TRAILING_YEAR_PATTERNS:
        stripped = pattern.sub("", stripped)
    stripped = stripped.strip()
    if stripped and stripped.casefold() not in aliases:
        aliases.append(stripped.casefold())

    return aliases


def fetch_users(settings: TautulliSettings) -> list[dict[str, str]]:
    data = settings.request("get_users")

    raw_entries: list[dict[str, Any]] = []
    if isinstance(data, list):
        raw_entries = [entry for entry in data if isinstance(entry, dict)]
    elif isinstance(data, dict):
        for key in ("users", "rows", "data"):
            value = data.get(key)
            if isinstance(value, list):
                raw_entries = [entry for entry in value if isinstance(entry, dict)]
                break

    users: list[dict[str, str]] = []
    for entry in raw_entries:
        user_id = entry.get("user_id") or entry.get("id") or entry.get("row_id")
        name = (
            entry.get("friendly_name")
            or entry.get("username")
            or entry.get("email")
            or entry.get("user")
        )
        if user_id is None or name is None:
            continue
        users.append({"id": str(user_id), "name": str(name)})

    users.sort(key=lambda entry: entry["name"].casefold())
    return users


def _series_lookup(tv_manager: TvYamlManager) -> list[dict[str, Any]]:
    tv_data = tv_manager.load()
    entries = []
    for name, raw_config in tv_data.get("series", {}).items():
        config = _to_builtin(raw_config)
        rating_key = config.get("rating_key")
        try:
            rating_key = int(rating_key)
        except (TypeError, ValueError):
            rating_key = str(rating_key) if rating_key is not None else None
        entries.append(
            {
                "name": name,
                "rating_key": rating_key,
                "library": config.get("library"),
                "aliases": _series_aliases(name),
            }
        )
    return entries


def _match_series(lookup: list[dict[str, Any]], *, title: str | None, rating_key: Any) -> dict[str, Any] | None:
    normalized_title = str(title or "").strip().casefold()
    try:
        normalized_key = int(rating_key)
    except (TypeError, ValueError):
        normalized_key = str(rating_key) if rating_key else None

    for entry in lookup:
        if entry.get("rating_key") is not None and normalized_key is not None:
            if str(entry["rating_key"]) == str(normalized_key):
                return entry

    if normalized_title:
        for entry in lookup:
            if normalized_title in entry.get("aliases", []):
                return entry

    return None


def _filter_recent(
    entries: Iterable[dict[str, Any]], *, days: int = 7, timestamp_field: str = "timestamp"
) -> list[dict[str, Any]]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    filtered: list[dict[str, Any]] = []
    for entry in entries:
        ts = _normalize_timestamp(entry.get(timestamp_field))
        if ts is None:
            continue
        dt = datetime.fromtimestamp(ts / 1000, tz=timezone.utc)
        if dt >= cutoff:
            filtered.append({**entry, timestamp_field: ts})
    return filtered


def _activity_entry(
    *,
    series_name: str,
    episode_title: str | None,
    season_label: str | None,
    timestamp: Any,
    show_rating_key: Any,
    episode_rating_key: Any,
) -> dict[str, Any]:
    return {
        "series": series_name,
        "episode": episode_title or "",
        "season": season_label or "",
        "timestamp": _normalize_timestamp(timestamp),
        "showRatingKey": show_rating_key,
        "episodeRatingKey": episode_rating_key,
    }


def _season_label(season_index: Any) -> str | None:
    if season_index is None:
        return None
    try:
        numeric = int(season_index)
        return f"Season {numeric}"
    except (TypeError, ValueError):
        return str(season_index)


def fetch_recent_watches(settings: TautulliSettings, lookup: list[dict[str, Any]]) -> list[dict[str, Any]]:
    request_params: dict[str, Any] = {
        "length": 200,
        "include_activity": 0,
        "grouping": 0,
    }
    if settings.user_id:
        request_params["user_id"] = settings.user_id

    history = settings.request("get_history", **request_params).get("data", [])

    tautulli_logger.info("Raw watched entries: %s", json.dumps(history, ensure_ascii=False))

    recent: list[dict[str, Any]] = []
    for entry in history:
        if entry.get("media_type") != "episode":
            continue
        match = _match_series(
            lookup,
            title=entry.get("grandparent_title") or entry.get("series_name") or entry.get("title"),
            rating_key=entry.get("grandparent_rating_key"),
        )
        if not match:
            continue

        recent.append(
            _activity_entry(
                series_name=match["name"],
                episode_title=entry.get("title"),
                season_label=f"S{entry.get('parent_index')}E{entry.get('index')}" if entry.get("index") else _season_label(entry.get("parent_index")),
                timestamp=entry.get("date") or entry.get("started") or entry.get("last_seen"),
                show_rating_key=entry.get("grandparent_rating_key"),
                episode_rating_key=entry.get("rating_key"),
            )
        )

    filtered = _filter_recent(recent)
    tautulli_logger.info(
        "Filtered watched entries (%d): %s", len(filtered), json.dumps(filtered, ensure_ascii=False)
    )
    return filtered


def _expand_rating_key_to_episodes(
    context: AppContext,
    rating_key: Any,
    fallback_title: str | None,
) -> list[dict[str, Any]]:
    plex = context.get_plex_interface()
    expanded: list[dict[str, Any]] = []

    try:
        rating_key_int = int(rating_key)
    except (TypeError, ValueError):
        rating_key_int = rating_key

    for details in plex.expand_rating_key_to_episodes(rating_key_int):
        expanded.append(
            {
                "series": details.get("series") or (fallback_title or ""),
                "episode": details.get("title"),
                "season": details.get("season"),
                "episode_number": details.get("episode"),
                "show_rating_key": details.get("show_rating_key") or rating_key,
                "episode_rating_key": details.get("episode_rating_key"),
            }
        )

    return expanded


def fetch_recently_added(
    context: AppContext,
    settings: TautulliSettings,
    lookup: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    payload = settings.request("get_recently_added", count=200)
    records = payload.get("recently_added", payload.get("records", []))

    tautulli_logger.info(
        "Raw recently added entries: %s", json.dumps(records, ensure_ascii=False)
    )

    entries: list[dict[str, Any]] = []
    for record in records:
        section_type = record.get("section_type") or record.get("media_type")
        if section_type not in {"show", "episode", "season"}:
            continue

        timestamp = record.get("added_at") or record.get("added")
        base_title = record.get("grandparent_title") or record.get("title")
        show_rating_key = record.get("grandparent_rating_key") or record.get("rating_key")
        series_match = _match_series(lookup, title=base_title, rating_key=show_rating_key)
        if not series_match:
            continue

        if section_type == "episode":
            entries.append(
                _activity_entry(
                    series_name=series_match["name"],
                    episode_title=record.get("title"),
                    season_label=_season_label(record.get("parent_index")),
                    timestamp=timestamp,
                    show_rating_key=show_rating_key,
                    episode_rating_key=record.get("rating_key"),
                )
            )
            continue

        expanded = _expand_rating_key_to_episodes(
            context,
            record.get("rating_key") or show_rating_key,
            base_title,
        )

        for episode in expanded:
            if episode.get("series"):
                episode_show_rating_key = episode.get("show_rating_key") or show_rating_key
                series_match = _match_series(
                    lookup,
                    title=episode["series"],
                    rating_key=episode_show_rating_key,
                )
                if not series_match:
                    continue
                entries.append(
                    _activity_entry(
                        series_name=series_match["name"],
                        episode_title=episode.get("episode"),
                        season_label=_season_label(episode.get("season")),
                        timestamp=timestamp,
                        show_rating_key=episode_show_rating_key,
                        episode_rating_key=episode.get("episode_rating_key"),
                    )
                )

    filtered = _filter_recent(entries, timestamp_field="timestamp")
    tautulli_logger.info(
        "Filtered recently added entries (%d): %s",
        len(filtered),
        json.dumps(filtered, ensure_ascii=False),
    )
    return filtered


def fetch_recent_activity(context: AppContext, tv_manager: TvYamlManager) -> dict[str, Any]:
    settings = TautulliSettings.from_settings()
    if not settings:
        raise RuntimeError("Tautulli is not configured. Set the URL and API key in settings.")

    if not context.preference_parser.use_plex:
        raise RuntimeError("Plex must be enabled in preferences to use Tautulli activity.")

    lookup = _series_lookup(tv_manager)
    watched = fetch_recent_watches(settings, lookup)
    added = fetch_recently_added(context, settings, lookup)
    return {"watched": watched, "added": added, "generatedAt": int(datetime.now(tz=timezone.utc).timestamp() * 1000)}
