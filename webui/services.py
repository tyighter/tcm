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


class ActionInProgressError(RuntimeError):
    """Raised when a long-running Manager action is already in progress."""


logger = logging.getLogger(__name__)

_action_lock = Lock()
_preview_cache_lock = Lock()
_preview_cache: dict[str, tuple[str, str]] = {}
_sync_lock = Lock()
_last_sync: float = 0.0
_SYNC_COOLDOWN_SECONDS = 45.0


def _maybe_sync_series_files(
    manager: Manager, *, force: bool = False, cooldown_seconds: float = _SYNC_COOLDOWN_SECONDS
) -> bool:
    """Run ``manager.sync_series_files`` unless a recent sync was performed."""

    global _last_sync

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

    manager.sync_series_files()

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

    manager = Manager(check_tautulli=False)
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


def _preview_from_existing_sources(
    show: Show, preferred_episode_key: str | None
) -> tuple[str, str] | None:
    if preferred_episode_key:
        episode = show.episodes.get(preferred_episode_key)
        if (
            episode is None
            or episode.destination is None
            or not episode.destination.exists()
        ):
            return None
    else:
        available = [
            episode
            for episode in show.episodes.values()
            if episode.destination is not None and episode.destination.exists()
        ]
        if not available:
            return None

        episode = random.choice(available)

    mime, _ = mimetypes.guess_type(episode.destination.name)
    mime = mime or "image/jpeg"
    data = base64.b64encode(episode.destination.read_bytes()).decode("ascii")
    return mime, data


def get_or_generate_preview(
    context: AppContext,
    tv_manager: TvYamlManager,
    show_name: str,
    series_config: dict[str, Any],
    *,
    force: bool = False,
    preview_episode_key: str | None = None,
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
            return cached

    show = _load_show_for_preview(context, tv_manager, show_name, series_config)

    preview_from_source = _preview_from_existing_sources(show, preview_episode_key)
    if preview_from_source is not None:
        mime, data = preview_from_source
    else:
        mime, data = generate_preview(
            context,
            tv_manager,
            show_name,
            series_config,
            preferred_episode_key=preview_episode_key,
            preloaded_show=show,
        )

    with _preview_cache_lock:
        _preview_cache[cache_key] = (mime, data)

    return mime, data


def generate_preview(
    context: AppContext,
    tv_manager: TvYamlManager,
    show_name: str,
    series_config: dict[str, Any],
    *,
    preferred_episode_key: str | None = None,
    preloaded_show: Show | None = None,
) -> tuple[str, str]:
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

    return "image/jpeg", base64.b64encode(data).decode("ascii")


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


def _run_fixer_command(arguments: list[str]) -> None:
    """Execute fixer.py with the supplied arguments, ensuring exclusivity."""

    if not _action_lock.acquire(blocking=False):
        raise ActionInProgressError("Another task is already running")

    try:
        result = subprocess.run(
            arguments, capture_output=True, check=False, text=True
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


def _run_manager_job(task: Callable[[Manager], None]) -> None:
    """Execute a Manager job while ensuring only one runs at a time."""

    if not _action_lock.acquire(blocking=False):
        raise ActionInProgressError("Another task is already running")

    try:
        manager = Manager(check_tautulli=False)
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
