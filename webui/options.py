from __future__ import annotations

from typing import Any

from modules.BaseCardType import BaseCardType
from modules.PreferenceParser import PreferenceParser
from modules.StyleSet import StyleSet
from modules.TitleCard import TitleCard

SERIES_FIELD_TEMPLATE = [
    {
        "id": "library",
        "label": "Library",
        "path": ["library"],
        "type": "library",
        "default": "TV Shows",
    },
    {
        "id": "card_type",
        "label": "Card Type",
        "path": ["card_type"],
        "type": "card-type",
        "default": "standard",
    },
    {
        "id": "episode_text_format",
        "label": "Episode text format",
        "path": ["episode_text_format"],
        "type": "text",
    },
    {
        "id": "episode_data_source",
        "label": "Episode data source",
        "path": ["episode_data_source"],
        "type": "choice",
        "choices": [],
    },
    {
        "id": "watched_style",
        "label": "Watched style",
        "path": ["watched_style"],
        "type": "style",
    },
    {
        "id": "unwatched_style",
        "label": "Unwatched style",
        "path": ["unwatched_style"],
        "type": "style",
    },
    {
        "id": "tmdb_id",
        "label": "TMDb ID",
        "path": ["tmdb_id"],
        "type": "number",
    },
    {
        "id": "tvdb_id",
        "label": "TVDb ID",
        "path": ["tvdb_id"],
        "type": "number",
    },
    {
        "id": "imdb_id",
        "label": "IMDb ID",
        "path": ["imdb_id"],
        "type": "text",
    },
    {
        "id": "tvrage_id",
        "label": "TVRage ID",
        "path": ["tvrage_id"],
        "type": "number",
    },
    {
        "id": "emby_id",
        "label": "Emby ID",
        "path": ["emby_id"],
        "type": "text",
    },
    {
        "id": "jellyfin_id",
        "label": "Jellyfin ID",
        "path": ["jellyfin_id"],
        "type": "text",
    },
    {
        "id": "sonarr_id",
        "label": "Sonarr ID",
        "path": ["sonarr_id"],
        "type": "number",
    },
    {
        "id": "refresh_titles",
        "label": "Refresh titles",
        "path": ["refresh_titles"],
        "type": "boolean",
    },
    {
        "id": "sync_specials",
        "label": "Sync specials",
        "path": ["sync_specials"],
        "type": "boolean",
    },
    {
        "id": "sonarr_sync",
        "label": "Sync from Sonarr",
        "path": ["sonarr_sync"],
        "type": "boolean",
    },
    {
        "id": "tmdb_sync",
        "label": "Sync from TMDb",
        "path": ["tmdb_sync"],
        "type": "boolean",
    },
    {
        "id": "tmdb_skip_localized_images",
        "label": "Skip localized TMDb images",
        "path": ["tmdb_skip_localized_images"],
        "type": "boolean",
    },
    {
        "id": "archive",
        "label": "Create archive",
        "path": ["archive"],
        "type": "boolean",
    },
    {
        "id": "archive_all_variations",
        "label": "Archive all variations",
        "path": ["archive_all_variations"],
        "type": "boolean",
    },
    {
        "id": "archive_name",
        "label": "Archive name",
        "path": ["archive_name"],
        "type": "text",
    },
    {
        "id": "library_override",
        "label": "Override media directory",
        "path": ["media_directory"],
        "type": "text",
    },
    {
        "id": "filename_format",
        "label": "Filename format",
        "path": ["filename_format"],
        "type": "text",
    },
    {
        "id": "image_source_priority",
        "label": "Image source priority",
        "path": ["image_source_priority"],
        "type": "csv",
    },
    {
        "id": "translation",
        "label": "Translations",
        "path": ["translation"],
        "type": "translation-list",
    },
    {
        "id": "font.file",
        "label": "Font file",
        "path": ["font", "file"],
        "type": "font",
    },
    {
        "id": "font.size",
        "label": "Font size (%)",
        "path": ["font", "size"],
        "type": "text",
    },
    {
        "id": "font.color",
        "label": "Font color",
        "path": ["font", "color"],
        "type": "text",
    },
    {
        "id": "font.case",
        "label": "Font casing",
        "path": ["font", "case"],
        "type": "font-case",
    },
    {
        "id": "font.vertical_shift",
        "label": "Font vertical shift",
        "path": ["font", "vertical_shift"],
        "type": "number",
    },
    {
        "id": "font.interline_spacing",
        "label": "Font interline spacing",
        "path": ["font", "interline_spacing"],
        "type": "number",
    },
    {
        "id": "font.interword_spacing",
        "label": "Font interword spacing",
        "path": ["font", "interword_spacing"],
        "type": "number",
    },
    {
        "id": "font.kerning",
        "label": "Font kerning",
        "path": ["font", "kerning"],
        "type": "text",
    },
    {
        "id": "font.stroke_width",
        "label": "Font stroke width",
        "path": ["font", "stroke_width"],
        "type": "text",
    },
    {
        "id": "font.validate",
        "label": "Validate font",
        "path": ["font", "validate"],
        "type": "boolean",
    },
    {
        "id": "font.replacements",
        "label": "Font replacements",
        "path": ["font", "replacements"],
        "type": "replacement-map",
    },
    {
        "id": "extras",
        "label": "Extra card options",
        "path": ["extras"],
        "type": "extras",
    },
    {
        "id": "seasons.hide",
        "label": "Hide seasons",
        "path": ["seasons", "hide"],
        "type": "hide-seasons",
    },
    {
        "id": "seasons.titles",
        "label": "Season titles",
        "path": ["seasons"],
        "type": "season-map",
    },
    {
        "id": "episode_ranges",
        "label": "Episode ranges",
        "path": ["episode_ranges"],
        "type": "range-map",
    },
]


def build_series_fields(libraries: dict[str, Any]) -> list[dict[str, Any]]:
    """Return field metadata with dynamic options populated."""

    fields = []
    library_choices = [
        {"value": name, "label": name}
        for name in libraries.keys()
    ]

    card_types = sorted(set(TitleCard.CARD_TYPES.keys()))
    style_choices = sorted(set(StyleSet.SPOIL_TYPE_STYLE_MAP.keys()))
    episode_sources = list(PreferenceParser.VALID_EPISODE_DATA_SOURCES)
    font_cases = sorted(BaseCardType.CASE_FUNCTIONS.keys())

    for field in SERIES_FIELD_TEMPLATE:
        filled = dict(field)
        if field["id"] == "library":
            filled["choices"] = library_choices
        elif field["id"] == "card_type":
            filled["choices"] = [
                {"value": value, "label": value.title()} for value in card_types
            ]
        elif field["id"] == "watched_style" or field["id"] == "unwatched_style":
            filled["choices"] = [
                {"value": value, "label": value} for value in style_choices
            ]
        elif field["id"] == "episode_data_source":
            filled["choices"] = [
                {"value": value, "label": value} for value in episode_sources
            ]
        elif field["id"] == "font.case":
            filled["choices"] = [
                {"value": value, "label": value} for value in font_cases
            ]
        fields.append(filled)

    return fields
