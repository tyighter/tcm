from __future__ import annotations

import base64
import tempfile
from copy import deepcopy
from pathlib import Path
from shutil import rmtree
from typing import Any

from modules.Manager import Manager
from modules.Show import Show
from modules.TitleCard import TitleCard

from .config import AppContext
from .tv_data import TvYamlManager, _to_builtin


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
