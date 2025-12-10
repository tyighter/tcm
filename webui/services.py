from __future__ import annotations

import base64
import hashlib
import json
import logging
import mimetypes
import random
import re
import subprocess
import sys
import tempfile
import time
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from shutil import rmtree
from threading import Lock
from typing import Any, Callable

from ruamel.yaml.comments import CommentedMap

from modules.CleanPath import CleanPath
from modules.Episode import Episode
from modules.Manager import Manager
from modules.Show import Show
from modules.ShowArchive import ShowArchive
from modules.TitleCard import TitleCard
from modules.SeriesInfo import SeriesInfo
from modules.TMDbInterface import TMDbInterface

from .config import AppContext
from .tv_data import TvYamlManager, _to_builtin
from .user_settings import load_settings


class ActionInProgressError(RuntimeError):
    """Raised when a long-running Manager action is already in progress."""


logger = logging.getLogger(__name__)

_action_lock = Lock()
_preview_cache_lock = Lock()
_preview_cache: dict[str, "PreviewPayload"] = {}
_preview_log_lock = Lock()
_sync_lock = Lock()
_last_sync: float = 0.0
_DEFAULT_SYNC_COOLDOWN_SECONDS = 45.0
_SYNC_COOLDOWN_SECONDS = _DEFAULT_SYNC_COOLDOWN_SECONDS
PREVIEW_LOG_FILE = Path("/config/preview.log")
PREVIEW_CACHE_DIR = Path("/config/preview-cache")


@dataclass(frozen=True)
class PreviewPayload:
    """Preview data along with the path used to build it."""

    mime: str
    data: str
    source_path: Path | None
    existing_source: bool = False


def _preview_logger() -> logging.Logger | None:
    """Return a file-backed logger dedicated to preview activity."""

    with _preview_log_lock:
        logger_name = "tcm.preview"
        preview_logger = logging.getLogger(logger_name)

        if getattr(preview_logger, "_configured", False):
            return preview_logger

        try:
            PREVIEW_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
            handler = logging.FileHandler(PREVIEW_LOG_FILE, mode="a")
        except OSError as exc:  # pragma: no cover - filesystem errors are environment-specific
            logger.warning("Unable to write preview log to %s: %s", PREVIEW_LOG_FILE, exc)
            return None

        handler.setLevel(logging.INFO)
        handler.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
        )

        preview_logger.setLevel(logging.INFO)
        preview_logger.addHandler(handler)
        preview_logger.propagate = False
        preview_logger._configured = True  # type: ignore[attr-defined]
        preview_logger.info("Preview logging initialized")

        return preview_logger


def _log_preview_event(
    show_name: str,
    source_path: Path | str | None,
    *,
    status: str,
    origin: str | None = None,
    episode_key: str | None,
    cached: bool = False,
    persistent: bool = False,
    existing_source: bool = False,
    error: str | None = None,
) -> None:
    """Write a structured preview event to the preview log file."""

    preview_logger = _preview_logger()
    if preview_logger is None:
        return

    episode_label = episode_key or "random"
    resolved_source = str(source_path) if source_path else "unknown"
    resolved_origin = origin or "unknown"
    message = (
        "Preview %s | origin=%s | show=%s | episode=%s | source=%s | cached=%s | persistent_cache=%s | existing=%s"
        % (
            status,
            resolved_origin,
            show_name,
            episode_label,
            resolved_source,
            cached,
            persistent,
            existing_source,
        )
    )

    if error:
        preview_logger.error("%s | error=%s", message, error)
    else:
        preview_logger.info(message)


def _safe_cache_key(cache_key: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", cache_key)


def _persistent_cache_path(cache_key: str) -> Path:
    return PREVIEW_CACHE_DIR / f"{_safe_cache_key(cache_key)}.json"


def _persist_preview_payload(cache_key: str, payload: PreviewPayload) -> None:
    """Persist preview payloads so reloads do not require regeneration."""

    try:
        PREVIEW_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _persistent_cache_path(cache_key).write_text(
            json.dumps(
                {
                    "mime": payload.mime,
                    "data": payload.data,
                    "source_path": str(payload.source_path) if payload.source_path else None,
                    "existing_source": payload.existing_source,
                }
            )
        )
    except OSError as exc:
        logger.debug("Unable to persist preview cache for %s: %s", cache_key, exc)


def _load_persistent_preview(cache_key: str) -> PreviewPayload | None:
    """Load a preview payload from the persistent cache if present."""

    cache_path = _persistent_cache_path(cache_key)
    if not cache_path.exists():
        return None

    try:
        payload = json.loads(cache_path.read_text())
    except (OSError, ValueError) as exc:
        logger.debug("Unable to read persistent preview cache %s: %s", cache_path, exc)
        return None

    mime = payload.get("mime") or "image/jpeg"
    data = payload.get("data")
    if not isinstance(data, str):
        return None

    source_path = payload.get("source_path")
    existing_source = bool(payload.get("existing_source"))
    resolved_source = Path(source_path) if isinstance(source_path, str) else None
    return PreviewPayload(
        mime=mime,
        data=data,
        source_path=resolved_source,
        existing_source=existing_source,
    )


def _maybe_sync_series_files(
    manager: Manager,
    *,
    force: bool = False,
    cooldown_seconds: float | None = None,
) -> bool:
    """Run ``manager.sync_series_files`` unless a recent sync was performed."""

    global _last_sync

    def _series_sync_interval_seconds() -> float:
        global _SYNC_COOLDOWN_SECONDS
        try:
            settings = load_settings()
            interval = settings.get("series_sync_interval_seconds")
            if isinstance(interval, (int, float)):
                _SYNC_COOLDOWN_SECONDS = max(0.0, float(interval))
        except Exception:  # pragma: no cover - defensive
            _SYNC_COOLDOWN_SECONDS = max(0.0, _SYNC_COOLDOWN_SECONDS)

        return _SYNC_COOLDOWN_SECONDS or _DEFAULT_SYNC_COOLDOWN_SECONDS

    if cooldown_seconds is None:
        cooldown_seconds = _series_sync_interval_seconds()

    if not force:
        now = time.monotonic()
        with _sync_lock:
            if _last_sync and (now - _last_sync) < cooldown_seconds:
                logger.debug(
                    "Skipping series sync; last run %.1fs ago (cooldown %.1fs)",
                    now - _last_sync,
                    cooldown_seconds,
                )
                return False

    attempted_at = time.monotonic()

    try:
        manager.sync_series_files()
    except Exception:  # pragma: no cover - defensive
        logger.exception("Series sync failed")
        with _sync_lock:
            _last_sync = attempted_at
        raise
    else:
        with _sync_lock:
            _last_sync = time.monotonic()

    return True


def merge_series_configuration(
    context: AppContext,
    tv_manager: TvYamlManager,
    show_name: str,
    series_config: dict[str, Any],
) -> dict[str, Any]:
    """Prepare a series configuration for runtime consumption."""

    source = tv_manager.load()
    library_map = _to_builtin(source.get("libraries", {}))
    font_map = _to_builtin(source.get("fonts", {}))

    finalize = getattr(
        context.preference_parser,
        "_PreferenceParser__finalize_show_yaml",
    )

    merged_config = (
        deepcopy(series_config)
        if isinstance(series_config, dict)
        else _to_builtin(series_config)
    )

    merged = finalize(
        show_name,
        merged_config,
        {},
        library_map,
        font_map,
        default_media_server=context.preference_parser.default_media_server,
    )

    if merged is None:
        raise ValueError("Unable to resolve libraries or fonts for series")

    return merged


def backfill_tmdb_ids(context: AppContext, tv_manager: TvYamlManager) -> dict[str, int]:
    """Populate missing TMDb IDs for configured series and persist the changes."""

    if not context.preference_parser.use_tmdb:
        raise RuntimeError("TMDb is not configured in preferences.yml")

    tmdb = TMDbInterface(**context.preference_parser.tmdb_interface_kwargs)
    tv_data = tv_manager.load()

    series_entries = tv_data.get("series", CommentedMap())
    updated = 0
    processed = 0

    payload = {"libraries": _to_builtin(tv_data.get("libraries", CommentedMap())), "series": []}

    for name, raw_config in series_entries.items():
        processed += 1
        config = _to_builtin(raw_config)

        if not config.get("tmdb_id"):
            try:
                series_info = SeriesInfo(name)
            except Exception:
                series_info = None

            if series_info is not None:
                tmdb.set_series_ids(None, series_info)
                if series_info.tmdb_id:
                    config["tmdb_id"] = series_info.tmdb_id
                    updated += 1

        payload["series"].append({"name": name, "config": config})

    if updated:
        tv_manager.write(payload)
        tv_manager.invalidate()

    return {"updated": updated, "total": processed}


def backfill_rating_keys(context: AppContext, tv_manager: TvYamlManager) -> dict[str, int]:
    """Populate missing Plex rating keys for configured series."""

    if not context.preference_parser.use_plex:
        raise RuntimeError("Plex is not configured in preferences.yml")

    plex = context.get_plex_interface()
    tv_data = tv_manager.load()

    series_entries = tv_data.get("series", CommentedMap())
    updated = 0
    processed = 0

    payload = {"libraries": _to_builtin(tv_data.get("libraries", CommentedMap())), "series": []}

    for name, raw_config in series_entries.items():
        processed += 1
        config = _to_builtin(raw_config)

        library = config.get("library")
        if not library:
            payload["series"].append({"name": name, "config": config})
            continue

        current_rating_key = config.get("rating_key")

        try:
            series_info = SeriesInfo(name, config.get("year"))
        except Exception:
            payload["series"].append({"name": name, "config": config})
            continue

        rating_key = plex.get_series_rating_key(library, series_info)
        if rating_key is None:
            payload["series"].append({"name": name, "config": config})
            continue

        try:
            rating_key_value: int | str = int(rating_key)
        except (TypeError, ValueError):
            rating_key_value = str(rating_key)

        if current_rating_key != rating_key_value:
            config["rating_key"] = rating_key_value
            updated += 1

        payload["series"].append({"name": name, "config": config})

    if updated:
        tv_manager.write(payload)
        tv_manager.invalidate()

    return {"updated": updated, "total": processed}


def search_plex(context: AppContext, query: str, limit: int = 10) -> list[dict[str, Any]]:
    """Search Plex for shows matching the query string."""

    interface = context.get_plex_interface()
    results = interface.search_series(query, limit=limit)

    serialised = []
    for show in results:
        entry = {
            "title": show.get("title"),
            "year": show.get("year"),
            "library": show.get("library"),
            "summary": show.get("summary"),
            "ids": show.get("ids", {}),
        }
        if show.get("rating_key") is not None:
            entry["rating_key"] = show.get("rating_key")
        serialised.append(entry)

    return serialised


def _preview_cache_key(
    show_name: str,
    series_config: dict[str, Any],
    *,
    preview_episode_key: str | None = None,
) -> str:
    serialised = json.dumps(_to_builtin(series_config), sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(serialised.encode("utf-8")).hexdigest()
    suffix = preview_episode_key or "random"
    return f"{show_name}:{digest}:{suffix}"


def invalidate_preview_cache(series_name: str | None = None) -> None:
    """Invalidate cached previews, optionally only for a specific series."""

    with _preview_cache_lock:
        if series_name is None:
            _preview_cache.clear()
            return

        prefix = f"{series_name}:"
        stale_keys = [key for key in _preview_cache if key.startswith(prefix)]
        for key in stale_keys:
            del _preview_cache[key]


def _load_show_for_preview(
    context: AppContext,
    tv_manager: TvYamlManager,
    show_name: str,
    series_config: dict[str, Any],
    *,
    force_sync: bool = False,
) -> Show:
    runtime_config = merge_series_configuration(
        context,
        tv_manager,
        show_name,
        series_config,
    )

    show = Show(
        show_name,
        runtime_config,
        context.preference_parser.source_directory,
        context.preference_parser,
    )
    if not show.valid:
        raise RuntimeError("Series configuration is invalid; check required fields")

    manager = Manager()
    _maybe_sync_series_files(manager, force=force_sync)
    show.assign_interfaces(
        manager.emby_interface,
        manager.jellyfin_interface,
        manager.plex_interface,
        manager.sonarr_interfaces,
        manager.tmdb_interface,
    )

    show.set_series_ids()
    show.read_source()
    show.find_multipart_episodes()

    # If no local episode metadata exists yet, fetch it from the media server
    # so the preview can still render a representative card.
    if not show.episodes:
        show.add_new_episodes()
        show.find_multipart_episodes()

    if not show.episodes:
        raise RuntimeError("No episodes are available for preview")

    return show


def _existing_card_path(show: Show, episode: Episode | None) -> Path | None:
    if episode is None:
        return None

    if episode.destination is not None and episode.destination.exists():
        return episode.destination

    if not show.media_directory:
        return None

    search_roots: list[Path] = []
    season_dir = Path(show.media_directory) / f"Season {episode.episode_info.season_number}"
    search_roots.append(season_dir)
    search_roots.append(Path(show.media_directory))

    candidates: list[Path] = []
    for root in search_roots:
        try:
            if not root.exists() or not root.is_dir():
                continue
        except OSError:
            continue

        for pattern in ("*.jpg", "*.jpeg", "*.png", "*.webp"):
            candidates.extend(sorted(root.rglob(pattern)))

    if not candidates:
        return None

    episode_pattern = re.compile(
        rf"(?i)(s0*{episode.episode_info.season_number}e0*{episode.episode_info.episode_number}|"
        rf"{episode.episode_info.season_number}x0*{episode.episode_info.episode_number})"
    )

    matching = [
        candidate
        for candidate in candidates
        if episode_pattern.search(candidate.name)
    ]

    return (matching or candidates)[0]


def _preview_from_existing_sources(
    show: Show, preferred_episode_key: str | None
) -> PreviewPayload | None:
    preferred_episode = (
        show.episodes.get(preferred_episode_key) if preferred_episode_key else None
    )
    preferred_card = _existing_card_path(show, preferred_episode)

    available_cards = [
        (episode, _existing_card_path(show, episode))
        for episode in show.episodes.values()
    ]
    available_cards = [item for item in available_cards if item[1] is not None]

    if preferred_card is not None:
        selected_card = preferred_card
    elif available_cards:
        _, selected_card = random.choice(available_cards)
    else:
        return None

    mime, _ = mimetypes.guess_type(selected_card.name)
    mime = mime or "image/jpeg"
    data = base64.b64encode(selected_card.read_bytes()).decode("ascii")
    return PreviewPayload(
        mime=mime, data=data, source_path=selected_card, existing_source=True
    )


def get_or_generate_preview(
    context: AppContext,
    tv_manager: TvYamlManager,
    show_name: str,
    series_config: dict[str, Any],
    *,
    force: bool = False,
    preview_episode_key: str | None = None,
    prefer_existing: bool = True,
) -> tuple[str, str]:
    """Return a cached preview or generate and cache a new one."""

    cache_key = _preview_cache_key(
        show_name,
        series_config,
        preview_episode_key=preview_episode_key,
    )
    if not force:
        with _preview_cache_lock:
            cached = _preview_cache.get(cache_key)
        if cached is not None:
            if prefer_existing and not cached.existing_source:
                _log_preview_event(
                    show_name,
                    cached.source_path,
                    status="invalidated",
                    origin="memory-cache",
                    episode_key=preview_episode_key,
                    cached=True,
                    existing_source=cached.existing_source,
                )
                with _preview_cache_lock:
                    _preview_cache.pop(cache_key, None)
            else:
                _log_preview_event(
                    show_name,
                    cached.source_path,
                    status="success",
                    origin="memory-cache",
                    episode_key=preview_episode_key,
                    cached=True,
                    existing_source=cached.existing_source,
                )
                return cached.mime, cached.data

        persistent_cached = _load_persistent_preview(cache_key)
        if persistent_cached is not None:
            if prefer_existing and not persistent_cached.existing_source:
                _log_preview_event(
                    show_name,
                    persistent_cached.source_path,
                    status="invalidated",
                    origin="persistent-cache",
                    episode_key=preview_episode_key,
                    cached=True,
                    persistent=True,
                    existing_source=persistent_cached.existing_source,
                )
                try:
                    _persistent_cache_path(cache_key).unlink()
                except OSError:
                    logger.debug(
                        "Unable to remove invalid persistent preview cache for %s", cache_key
                    )
            else:
                with _preview_cache_lock:
                    _preview_cache[cache_key] = persistent_cached
                _log_preview_event(
                    show_name,
                    persistent_cached.source_path,
                    status="success",
                    origin="persistent-cache",
                    episode_key=preview_episode_key,
                    cached=True,
                    persistent=True,
                    existing_source=persistent_cached.existing_source,
                )
                return persistent_cached.mime, persistent_cached.data

    try:
        show = _load_show_for_preview(context, tv_manager, show_name, series_config)

        preview_from_source = (
            _preview_from_existing_sources(show, preview_episode_key)
            if prefer_existing
            else None
        )
        if preview_from_source is not None:
            payload = preview_from_source
            preview_origin = "existing-source"
        else:
            payload = generate_preview(
                context,
                tv_manager,
                show_name,
                series_config,
                preferred_episode_key=preview_episode_key,
                preloaded_show=show,
            )
            preview_origin = "generated"
    except Exception as exc:  # pylint: disable=broad-except
        _log_preview_event(
            show_name,
            None,
            status="failure",
            episode_key=preview_episode_key,
            error=str(exc),
        )
        raise

    with _preview_cache_lock:
        _preview_cache[cache_key] = payload

    _persist_preview_payload(cache_key, payload)
    _log_preview_event(
        show_name,
        payload.source_path,
        status="success",
        origin=preview_origin,
        episode_key=preview_episode_key,
        cached=False,
        persistent=False,
        existing_source=payload.existing_source,
    )

    return payload.mime, payload.data


def generate_preview(
    context: AppContext,
    tv_manager: TvYamlManager,
    show_name: str,
    series_config: dict[str, Any],
    *,
    preferred_episode_key: str | None = None,
    preloaded_show: Show | None = None,
) -> PreviewPayload:
    """Generate a title card preview, returning (mime, base64_data)."""

    show = preloaded_show or _load_show_for_preview(
        context,
        tv_manager,
        show_name,
        series_config,
    )

    episode = (
        show.episodes.get(preferred_episode_key)
        if preferred_episode_key
        else None
    )
    if episode is None:
        episode = random.choice(list(show.episodes.values()))
    show.select_source_images(select_only=episode)

    if not episode.source.exists():
        raise RuntimeError("Episode source image is missing; run sync first")

    temp_dir = Path(tempfile.mkdtemp(prefix="tcm-preview-"))
    destination = temp_dir / "preview.jpg"

    original_destination = episode.destination
    episode.destination = destination

    title_card = TitleCard(
        episode,
        show.profile,
        show.card_class.TITLE_CHARACTERISTICS,
        **show.extras,
        **episode.extra_characteristics,
    )

    title_card.converted_title, valid = show.font.validate_title(
        title_card.converted_title
    )
    if not valid:
        raise RuntimeError("The selected font is missing characters for the preview")

    created = title_card.create()
    if not created or not destination.exists():
        episode.destination = original_destination
        rmtree(temp_dir, ignore_errors=True)
        raise RuntimeError("Failed to generate preview image")

    data = destination.read_bytes()

    # Reset and cleanup
    episode.destination = original_destination
    rmtree(temp_dir, ignore_errors=True)

    return PreviewPayload(
        mime="image/jpeg", data=base64.b64encode(data).decode("ascii"), source_path=destination
    )


def list_preview_episodes(
    context: AppContext,
    tv_manager: TvYamlManager,
    show_name: str,
    series_config: dict[str, Any],
) -> list[dict[str, Any]]:
    """Return available episodes for preview selection."""

    def _safe_int(value: Any) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    show = _load_show_for_preview(context, tv_manager, show_name, series_config)

    sorted_episodes = sorted(
        show.episodes.values(),
        key=lambda ep: (
            _safe_int(ep.episode_info.season_number),
            _safe_int(ep.episode_info.episode_number),
        ),
    )

    options: list[dict[str, Any]] = []
    for episode in sorted_episodes:
        info = episode.episode_info
        season_number = _safe_int(info.season_number)
        episode_number = _safe_int(info.episode_number)
        label = f"S{season_number:02d}E{episode_number:02d}"
        if getattr(info, "title", None):
            label = f"{label} — {info.title}"

        options.append(
            {
                "key": info.key,
                "label": label,
                "season": season_number,
                "episode": episode_number,
            }
        )

    return options


def _prepare_series_context(
    tv_manager: TvYamlManager,
    series_name: str,
    series_config: dict[str, Any] | None,
) -> dict[str, Any]:
    """Resolve a usable series configuration for the given entry."""

    if series_config is not None:
        return tv_manager.clone_series_yaml(series_name, series_config)

    data = tv_manager.load()
    source_config = data.get("series", {}).get(series_name)
    if source_config is None:
        raise ValueError(f'Series "{series_name}" was not found in tv.yml')

    return tv_manager.clone_series_yaml(series_name, source_config)


def _split_series_name(series_name: str) -> tuple[str, str]:
    """Split a series name into title and year components."""

    match = re.match(r"^(.*)\((\d{4})\)\s*$", series_name)
    if not match:
        raise ValueError(
            "Series name must include a year in parentheses, e.g. "
            '"Example (2024)"'
        )

    title = match.group(1).strip()
    year = match.group(2)
    return title, year


def run_builder_for_series(
    context: AppContext,
    tv_manager: TvYamlManager,
    series_name: str,
    series_config: dict[str, Any] | None = None,
    *,
    force_sync: bool = False,
) -> None:
    """Run the builder pipeline for a single series."""

    config = _prepare_series_context(tv_manager, series_name, series_config)

    runtime_config = merge_series_configuration(
        context, tv_manager, series_name, config
    )

    show = Show(
        series_name,
        runtime_config,
        context.preference_parser.source_directory,
        context.preference_parser,
    )

    if not show.valid:
        raise RuntimeError("Series configuration is invalid; check required fields")

    def _run(manager: Manager) -> None:
        _maybe_sync_series_files(manager, force=force_sync)
        manager.shows = [show]
        manager.archives = []

        if manager.preferences.create_archive and show.archive:
            manager.archives = [
                ShowArchive(manager.preferences.archive_directory, show)
            ]

        manager._Manager__run(serial=True)  # pylint: disable=protected-access

    _run_manager_job(_run)


def download_logo_for_series(
    context: AppContext,
    tv_manager: TvYamlManager,
    series_name: str,
    series_config: dict[str, Any] | None = None,
    *,
    force_sync: bool = False,
    max_wait_attempts: int = 6,
    wait_interval: float = 0.5,
) -> None:
    """Ensure the specified series has an up-to-date logo on disk."""

    config = _prepare_series_context(tv_manager, series_name, series_config)

    runtime_config = merge_series_configuration(
        context,
        tv_manager,
        series_name,
        config,
    )

    show = Show(
        series_name,
        runtime_config,
        context.preference_parser.source_directory,
        context.preference_parser,
    )

    if not show.valid:
        raise RuntimeError("Series configuration is invalid; check required fields")

    safe_series_dir = CleanPath.sanitize_name(series_name)
    logo_path = (
        context.preference_parser.source_directory / safe_series_dir / "logo.png"
    )

    def _run(manager: Manager) -> None:
        _maybe_sync_series_files(manager, force=force_sync)
        show.assign_interfaces(
            manager.emby_interface,
            manager.jellyfin_interface,
            manager.plex_interface,
            manager.sonarr_interfaces,
            manager.tmdb_interface,
        )
        show.download_logo()

    attempts = 0
    while True:
        try:
            _run_manager_job(_run)
            return
        except ActionInProgressError:
            attempts += 1
            if attempts > max_wait_attempts:
                raise

            time.sleep(wait_interval)

            if not _action_lock.locked() and logo_path.exists() and logo_path.is_file():
                return


def run_asset_downloads_for_series(
    context: AppContext,
    tv_manager: TvYamlManager,
    series_name: str,
    series_config: dict[str, Any] | None = None,
    *,
    force_sync: bool = False,
) -> None:
    """Download logos and sources for a single series."""

    config = _prepare_series_context(tv_manager, series_name, series_config)
    runtime_config = merge_series_configuration(
        context, tv_manager, series_name, config
    )

    show = Show(
        series_name,
        runtime_config,
        context.preference_parser.source_directory,
        context.preference_parser,
    )

    if not show.valid:
        raise RuntimeError("Series configuration is invalid; check required fields")

    def _run(manager: Manager) -> None:
        _maybe_sync_series_files(manager, force=force_sync)
        manager.shows = [show]
        manager.archives = []

        if manager.preferences.create_archive and show.archive:
            manager.archives = [
                ShowArchive(manager.preferences.archive_directory, show)
            ]

        manager.assign_interfaces()
        manager.set_show_ids()
        manager.read_show_source()
        manager.add_new_episodes()
        manager.set_episode_ids()
        manager.add_translations()
        manager.download_logos()
        manager.select_source_images()

    _run_manager_job(_run)


def _run_fixer_command(arguments: list[str], *, input_text: str | None = None) -> None:
    """Execute fixer.py with the supplied arguments, ensuring exclusivity."""

    if not _action_lock.acquire(blocking=False):
        raise ActionInProgressError("Another task is already running")

    try:
        result = subprocess.run(
            arguments,
            capture_output=True,
            check=False,
            text=True,
            input=input_text,
        )
    finally:
        _action_lock.release()

    if result.returncode != 0:
        stderr = result.stderr.strip()
        stdout = result.stdout.strip()
        message = stderr or stdout or "Fixer command failed"
        raise RuntimeError(message)


def _build_fixer_arguments(
    tv_manager: TvYamlManager,
    series_name: str,
    series_config: dict[str, Any] | None,
    flag: str,
) -> list[str]:
    """Construct the fixer.py argument list for the provided flag."""

    config = _prepare_series_context(tv_manager, series_name, series_config)
    library = config.get("library")
    if not library:
        raise ValueError("Series must specify a library to run fixer actions")

    title, year = _split_series_name(series_name)

    fixer_script = Path(__file__).resolve().parent.parent / "fixer.py"
    return [
        sys.executable,
        fixer_script.as_posix(),
        flag,
        str(library),
        title,
        year,
    ]


def revert_series_cards(
    tv_manager: TvYamlManager,
    series_name: str,
    series_config: dict[str, Any] | None = None,
) -> None:
    """Invoke fixer.py to revert cards for a single series."""

    args = _build_fixer_arguments(
        tv_manager, series_name, series_config, "--revert-series"
    )
    _run_fixer_command(args)


def forget_series_cards(
    tv_manager: TvYamlManager,
    series_name: str,
    series_config: dict[str, Any] | None = None,
) -> None:
    """Invoke fixer.py to forget previously loaded cards for a series."""

    args = _build_fixer_arguments(
        tv_manager, series_name, series_config, "--forget-cards"
    )
    _run_fixer_command(args)


def delete_series_cards(
    context: AppContext,
    tv_manager: TvYamlManager,
    series_name: str,
    series_config: dict[str, Any] | None = None,
) -> None:
    """Delete generated cards for a single series using fixer.py."""

    config = _prepare_series_context(tv_manager, series_name, series_config)
    card_directory = config.get("card_directory")
    if not card_directory:
        raise ValueError("Series must specify a card_directory to delete cards")

    target = CleanPath(card_directory).sanitize()
    if not target.is_absolute():
        target = (context.preference_parser.source_directory / target).resolve()

    extension = getattr(
        context.preference_parser,
        "card_extension",
        TitleCard.DEFAULT_CARD_EXTENSION,
    )

    fixer_script = Path(__file__).resolve().parent.parent / "fixer.py"
    args = [
        sys.executable,
        str(fixer_script),
        "--delete-cards",
        str(target),
        "--delete-extension",
        extension,
    ]

    _run_fixer_command(args, input_text="Y\n")


def _run_manager_job(task: Callable[[Manager], None]) -> None:
    """Execute a Manager job while ensuring only one runs at a time."""

    if not _action_lock.acquire(blocking=False):
        raise ActionInProgressError("Another task is already running")

    try:
        manager = Manager()
        task(manager)
    finally:
        _action_lock.release()


def run_metadata_sync(*, force_sync: bool = False) -> None:
    """Trigger only the metadata sync step."""

    _run_manager_job(lambda manager: _maybe_sync_series_files(manager, force=force_sync))


def run_builder() -> None:
    """Run the full TitleCardMaker pipeline."""

    _run_manager_job(lambda manager: manager.run())


def run_asset_downloads() -> None:
    """Download logos and source images for all configured series."""

    def _execute(manager: Manager) -> None:
        manager.sync_series_files()
        manager.create_shows()
        manager.assign_interfaces()
        manager.set_show_ids()
        manager.read_show_source()
        manager.add_new_episodes()
        manager.set_episode_ids()
        manager.add_translations()
        manager.download_logos()
        manager.select_source_images()

    _run_manager_job(_execute)
