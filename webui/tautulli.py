from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Event, Thread
from typing import Any, Iterable
from urllib.parse import urljoin

import requests
import re

from .config import AppContext
from .tv_data import TvYamlManager, _to_builtin
from .services import ActionInProgressError, run_builder_for_series
from .user_settings import load_settings

TAUTULLI_LOG_FILE = Path("/config/tautulli.log")
PLEX_WATCHED_LOG_FILE = Path("/config/plexwatched.log")


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


def _append_plex_watch_log(title: str, rating_key: Any, watched: bool) -> None:
    status = "watched" if watched else "unwatched"
    timestamp = datetime.now(tz=timezone.utc).isoformat()
    try:
        PLEX_WATCHED_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with PLEX_WATCHED_LOG_FILE.open("a", encoding="utf-8") as log_file:
            log_file.write(
                f"{timestamp} | {title or ''} | {rating_key or ''} | {status}\n"
            )
    except OSError as exc:  # pragma: no cover - filesystem errors are environment specific
        tautulli_logger.warning("Unable to write Plex watch log entry: %s", exc)

_recent_activity_cache: dict[str, dict[str, Any]] = {}
_monitor_stop_event = Event()
_monitor_thread: Thread | None = None
_plex_watch_state_cache: dict[str, dict[str, bool]] = {}

_DEFAULT_CACHE_KEY = "__all__"
_MIN_ACTIVITY_POLL_INTERVAL_SECONDS = 15

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


def _coerce_number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _is_marked_watched(entry: dict[str, Any]) -> bool:
    watched_status = entry.get("watched_status")

    if isinstance(watched_status, bool):
        return watched_status

    try:
        numeric_status = int(watched_status)
        if numeric_status == 1:
            return True
    except (TypeError, ValueError):
        pass

    if isinstance(watched_status, str):
        normalized = watched_status.strip().casefold()
        if normalized in {"watched", "played", "complete", "completed"}:
            return True

    return False


def _progress_fraction(entry: dict[str, Any]) -> float | None:
    for key in ("progress", "progress_percent", "percent_complete"):
        percent = _coerce_number(entry.get(key))
        if percent is None:
            continue

        # Normalize both ratio (0-1) and percent (0-100) formats
        return percent / 100 if percent > 1 else percent

    offset = _coerce_number(entry.get("view_offset"))
    duration = _coerce_number(entry.get("media_duration") or entry.get("duration"))
    if offset is None or duration in (None, 0):
        return None

    return max(0.0, offset) / duration


def _is_sufficiently_watched(entry: dict[str, Any]) -> bool:
    if _is_marked_watched(entry):
        return True

    progress = _progress_fraction(entry)
    return progress is not None and progress >= 0.5


def _activity_entry(
    *,
    series_name: str,
    episode_title: str | None,
    season_label: str | None,
    timestamp: Any,
    show_rating_key: Any,
    episode_rating_key: Any,
    unwatch: bool = False,
) -> dict[str, Any]:
    return {
        "series": series_name,
        "episode": episode_title or "",
        "season": season_label or "",
        "timestamp": _normalize_timestamp(timestamp),
        "showRatingKey": show_rating_key,
        "episodeRatingKey": episode_rating_key,
        "unwatch": unwatch,
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

        if not _is_sufficiently_watched(entry):
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


def _episode_label(episode: dict[str, Any]) -> str | None:
    try:
        season = int(episode.get("season"))
        number = int(episode.get("episode"))
    except (TypeError, ValueError):
        return None

    return f"S{season}E{number}"


def _backfill_episode_rating_keys(
    context: AppContext, tv_manager: TvYamlManager
) -> dict[str, int]:
    updated = 0
    processed = 0

    plex = context.get_plex_interface()
    tv_data = tv_manager.load()
    series_entries = tv_data.get("series", {})

    for series_name, raw_config in series_entries.items():
        processed += 1
        config = _to_builtin(raw_config)
        rating_key = config.get("rating_key")
        if rating_key is None:
            continue

        normalized_show_key = _normalize_rating_key(rating_key)

        try:
            episodes = plex.expand_rating_key_to_episodes(rating_key)
        except Exception as exc:  # pylint: disable=broad-except
            tautulli_logger.warning(
                "Unable to expand Plex rating key %s for %s: %s",
                rating_key,
                series_name,
                exc,
            )
            continue

        labels: dict[str, Any] = {}
        show_keys: set[str] = set()
        for episode in episodes:
            label = _episode_label(episode)
            episode_key = _normalize_rating_key(episode.get("episode_rating_key"))
            if label and episode_key:
                labels[label] = episode_key

            show_key = _normalize_rating_key(
                episode.get("show_rating_key") or rating_key
            )
            if show_key:
                show_keys.add(show_key)

        if not labels:
            continue

        if normalized_show_key:
            show_keys.add(normalized_show_key)

        changed = False
        for show_key in show_keys:
            if tv_manager.update_episode_rating_keys(series_name, show_key, labels):
                changed = True

        if changed:
            updated += 1

    return {"updated": updated, "total": processed}


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


def _cache_key(settings: TautulliSettings | None) -> str:
    if settings and settings.user_id:
        return settings.user_id
    return _DEFAULT_CACHE_KEY


def _normalize_rating_key(value: Any) -> str | None:
    try:
        return str(int(value))
    except (TypeError, ValueError):
        try:
            text = str(value).strip()
        except Exception:
            return None
        return text or None


def _reset_recent_activity_cache() -> None:
    _recent_activity_cache.clear()
    _reset_plex_watch_state_cache()


def _reset_plex_watch_state_cache() -> None:
    _plex_watch_state_cache.clear()


def fetch_recent_activity(
    context: AppContext, tv_manager: TvYamlManager, *, settings: TautulliSettings | None = None
) -> dict[str, Any]:
    settings = settings or TautulliSettings.from_settings()
    if not settings:
        raise RuntimeError("Tautulli is not configured. Set the URL and API key in settings.")

    if not context.preference_parser.use_plex:
        raise RuntimeError("Plex must be enabled in preferences to use Tautulli activity.")

    lookup = _series_lookup(tv_manager)
    watched = fetch_recent_watches(settings, lookup)
    watched = _merge_new_entries(watched, _plex_watched_changes(context, lookup))
    added = fetch_recently_added(context, settings, lookup)
    return {
        "watched": watched,
        "added": added,
        "generatedAt": int(datetime.now(tz=timezone.utc).timestamp() * 1000),
    }


def get_cached_recent_activity(cache_key: str | None) -> dict[str, Any] | None:
    if cache_key is None:
        return None
    return _recent_activity_cache.get(cache_key)


def get_or_fetch_recent_activity(context: AppContext, tv_manager: TvYamlManager) -> dict[str, Any]:
    settings = TautulliSettings.from_settings()
    if not settings:
        raise RuntimeError("Tautulli is not configured. Set the URL and API key in settings.")

    cache_key = _cache_key(settings)
    cached = get_cached_recent_activity(cache_key)
    if cached:
        return cached

    payload = fetch_recent_activity(context, tv_manager, settings=settings)
    _store_recent_activity(payload, cache_key)
    return payload


def _store_recent_activity(payload: dict[str, Any], cache_key: str) -> None:
    _recent_activity_cache[cache_key] = payload
    watched = len(payload.get("watched", []))
    added = len(payload.get("added", []))
    tautulli_logger.info(
        "Cached recent Tautulli activity for %s: %d watched, %d added",
        cache_key,
        watched,
        added,
    )


def _activity_identifier(entry: dict[str, Any] | None) -> tuple[str, str, str, str, str, str]:
    if not isinstance(entry, dict):
        return ("", "", "", "", "", "")

    show_identifier = str(entry.get("showRatingKey") or entry.get("series") or "").casefold()
    episode_identifier = entry.get("episodeRatingKey")
    if episode_identifier is not None:
        episode_identifier = str(episode_identifier).casefold()
    season_label = str(entry.get("season") or "").casefold()
    episode_label = str(entry.get("episode") or "").casefold()
    timestamp = _normalize_timestamp(entry.get("timestamp"))

    return (
        show_identifier,
        episode_identifier or "",
        season_label,
        episode_label,
        str(timestamp or ""),
        str(bool(entry.get("unwatch"))).lower(),
    )


def _merge_new_entries(
    existing: Iterable[dict[str, Any]], additions: Iterable[dict[str, Any]]
) -> list[dict[str, Any]]:
    merged = list(existing)
    existing_keys = {_activity_identifier(entry) for entry in merged}
    for entry in additions:
        identifier = _activity_identifier(entry)
        if identifier in existing_keys:
            continue
        merged.append(entry)
        existing_keys.add(identifier)
    return merged


def _new_entries(previous: Iterable[dict[str, Any]], current: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    previous_keys = {_activity_identifier(entry) for entry in previous}
    return [entry for entry in current if _activity_identifier(entry) not in previous_keys]


def _series_needing_build(
    entries: Iterable[dict[str, Any]],
    tv_manager: TvYamlManager,
    *,
    require_watch_styles: bool = False,
) -> set[str]:
    config = tv_manager.load().get("series", {})
    matches: set[str] = set()

    for entry in entries:
        series_name = entry.get("series") if isinstance(entry, dict) else None
        if not series_name or series_name not in config:
            continue

        if require_watch_styles:
            series_config = _to_builtin(config.get(series_name, {}))
            if not (series_config.get("watched_style") or series_config.get("unwatched_style")):
                continue

        matches.add(series_name)

    return matches


def _plex_watched_changes(
    context: AppContext, lookup: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    plex = context.get_plex_interface()
    now_ms = int(datetime.now(tz=timezone.utc).timestamp() * 1000)
    synthetic: list[dict[str, Any]] = []

    for entry in lookup:
        show_rating_key = _normalize_rating_key(entry.get("rating_key"))
        if not show_rating_key:
            continue

        previous_state = _plex_watch_state_cache.get(show_rating_key)
        try:
            episodes = plex.expand_rating_key_to_episodes(entry["rating_key"])
        except Exception as exc:  # pylint: disable=broad-except
            tautulli_logger.warning(
                "Unable to poll Plex watch state for %s (%s): %s",
                entry.get("name"),
                show_rating_key,
                exc,
            )
            continue

        current_state: dict[str, bool] = {}
        episode_details: dict[str, dict[str, Any]] = {}
        for episode in episodes:
            episode_rating_key = _normalize_rating_key(
                episode.get("episode_rating_key")
            )
            if not episode_rating_key:
                continue

            watched = bool(episode.get("watched"))
            current_state[episode_rating_key] = watched
            episode_details[episode_rating_key] = episode

        if previous_state is not None:
            for episode_rating_key, watched in current_state.items():
                previous_watched = previous_state.get(episode_rating_key, False)
                if watched == previous_watched:
                    continue

                details = episode_details.get(episode_rating_key) or {}
                episode_title = details.get("title") or entry.get("episode") or ""
                episode_rating_key = details.get("episode_rating_key")
                _append_plex_watch_log(episode_title, episode_rating_key, watched)
                synthetic.append(
                    _activity_entry(
                        series_name=entry.get("name", ""),
                        episode_title=episode_title,
                        season_label=_season_label(details.get("season")),
                        timestamp=now_ms,
                        show_rating_key=details.get("show_rating_key")
                        or entry.get("rating_key"),
                        episode_rating_key=episode_rating_key,
                        unwatch=not watched,
                    )
                )

        _plex_watch_state_cache[show_rating_key] = current_state

    return synthetic


def _trigger_builds_for_recent_changes(
    context: AppContext,
    tv_manager: TvYamlManager,
    previous_payload: dict[str, Any] | None,
    current_payload: dict[str, Any],
) -> None:
    if not previous_payload:
        return None

    previous_payload = previous_payload or {}
    previous_added = previous_payload.get("added", [])
    previous_watched = previous_payload.get("watched", [])

    new_added = _new_entries(previous_added, current_payload.get("added", []))
    new_watch_state_changes = _new_entries(
        previous_watched, current_payload.get("watched", [])
    )

    series_to_build = _series_needing_build(new_added, tv_manager)
    series_to_build.update(
        _series_needing_build(
            [entry for entry in new_watch_state_changes if not entry.get("unwatch")],
            tv_manager,
            require_watch_styles=True,
        )
    )
    series_to_build.update(
        _series_needing_build(
            [entry for entry in new_watch_state_changes if entry.get("unwatch")],
            tv_manager,
            require_watch_styles=True,
        )
    )

    for series_name in sorted(series_to_build):
        try:
            tautulli_logger.info(
                "Triggering background build for %s due to recent Plex activity",
                series_name,
            )
            run_builder_for_series(context, tv_manager, series_name)
        except ActionInProgressError:
            tautulli_logger.info(
                "Skipping background build for %s; another action is already running",
                series_name,
            )
        except Exception as exc:  # pylint: disable=broad-except
            tautulli_logger.warning(
                "Unable to build cards for %s after recent activity: %s",
                series_name,
                exc,
            )


def _monitor_recent_activity(
    context: AppContext, tv_manager: TvYamlManager, interval_seconds: int
) -> None:
    last_cache_key: str | None = None
    previous_payload: dict[str, Any] | None = None
    while not _monitor_stop_event.is_set():
        try:
            settings = TautulliSettings.from_settings()
            if not settings:
                raise RuntimeError(
                    "Tautulli is not configured. Set the URL and API key in settings."
                )

            cache_key = _cache_key(settings)

            if cache_key != last_cache_key:
                _reset_recent_activity_cache()
                if last_cache_key is None:
                    tautulli_logger.info(
                        "Initialised Tautulli activity cache for Plex user %s", cache_key
                    )
                else:
                    tautulli_logger.info(
                        "Reset cached Tautulli activity after Plex user change (%s)",
                        cache_key,
                    )
                last_cache_key = cache_key
                previous_payload = None

            payload = fetch_recent_activity(context, tv_manager, settings=settings)
        except Exception as exc:  # pylint: disable=broad-except
            tautulli_logger.warning("Unable to refresh Tautulli activity: %s", exc)
            continue

        try:
            _trigger_builds_for_recent_changes(
                context, tv_manager, previous_payload, payload
            )
        except Exception as exc:  # pylint: disable=broad-except
            tautulli_logger.warning(
                "Failed to trigger background build after recent changes: %s", exc
            )

        _store_recent_activity(payload, cache_key)
        previous_payload = payload

        if _monitor_stop_event.wait(interval_seconds):
            break


def start_recent_activity_monitor(
    context: AppContext, tv_manager: TvYamlManager, interval_seconds: int | None = None
) -> Thread | None:
    global _monitor_thread

    if _monitor_thread and _monitor_thread.is_alive():
        return _monitor_thread

    settings = TautulliSettings.from_settings()
    if not settings:
        tautulli_logger.info("Skipping Tautulli monitor start; Tautulli is not configured")
        return None

    if not context.preference_parser.use_plex:
        tautulli_logger.info("Skipping Tautulli monitor start; Plex is disabled in preferences")
        return None

    try:
        result = _backfill_episode_rating_keys(context, tv_manager)
    except Exception as exc:  # pylint: disable=broad-except
        tautulli_logger.warning(
            "Unable to backfill episode rating keys before starting monitor: %s",
            exc,
        )
    else:
        updated = result.get("updated", 0)
        if updated:
            tautulli_logger.info(
                "Backfilled episode rating keys for %d series before starting monitor",
                updated,
            )

    interval_seconds = interval_seconds or context.preference_parser.tautulli_activity_poll_interval_seconds
    interval_seconds = max(_MIN_ACTIVITY_POLL_INTERVAL_SECONDS, int(interval_seconds))

    _monitor_stop_event.clear()
    _monitor_thread = Thread(
        target=_monitor_recent_activity,
        args=(context, tv_manager, interval_seconds),
        name="tautulli-monitor",
        daemon=True,
    )
    _monitor_thread.start()
    tautulli_logger.info(
        "Started Tautulli activity monitor thread (interval=%ss)", interval_seconds
    )
    return _monitor_thread
