from __future__ import annotations

import base64
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

from modules.Manager import Manager
from modules.Show import Show
from modules.ShowArchive import ShowArchive
from modules.TitleCard import TitleCard

from .config import AppContext
from .tv_data import TvYamlManager, _to_builtin


class ActionInProgressError(RuntimeError):
    """Raised when a long-running Manager action is already in progress."""


_action_lock = Lock()


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
        serialised.append(entry)

    return serialised


def generate_preview(
    context: AppContext,
    tv_manager: TvYamlManager,
    show_name: str,
    series_config: dict[str, Any],
) -> tuple[str, str]:
    """Generate a title card preview, returning (mime, base64_data)."""

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
    manager.sync_series_files()
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

    episode = next(iter(show.episodes.values()))
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

    title_card.create()
    data = destination.read_bytes()

    # Reset and cleanup
    episode.destination = original_destination
    rmtree(temp_dir, ignore_errors=True)

    return "image/jpeg", base64.b64encode(data).decode("ascii")


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
        manager.sync_series_files()
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

    logo_path = (
        context.preference_parser.source_directory / series_name / "logo.png"
    )

    def _run(manager: Manager) -> None:
        manager.sync_series_files()
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


def run_metadata_sync() -> None:
    """Trigger only the metadata sync step."""

    _run_manager_job(lambda manager: manager.sync_series_files())


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
