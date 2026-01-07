from __future__ import annotations

import inspect
from typing import Any, Literal, get_args, get_origin

from modules.BaseCardType import BaseCardType
from modules.PreferenceParser import PreferenceParser
from modules.StyleSet import StyleSet
from modules.TitleCard import TitleCard
from .card_type_images import load_card_type_thumbnails, slugify_card_type

STYLE_CHOICES = ["unique", "blur", "grayscale", "blur grayscale"]

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
        "id": "episode_text_case",
        "label": "Episode text casing",
        "path": ["episode_text_case"],
        "type": "font-case",
        "default": BaseCardType.DEFAULT_FONT_CASE,
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
        "type": "color",
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

    card_types = sorted(
        (
            (identifier, identifier.title())
            for identifier in TitleCard.BUILTIN_CARD_TYPES.keys()
        ),
        key=lambda item: item[1].casefold(),
    )
    thumbnails = load_card_type_thumbnails()
    style_choices = [
        choice for choice in STYLE_CHOICES if choice in StyleSet.SPOIL_TYPE_STYLE_MAP
    ]
    episode_sources = list(PreferenceParser.VALID_EPISODE_DATA_SOURCES)
    font_cases = sorted(BaseCardType.CASE_FUNCTIONS.keys())

    for field in SERIES_FIELD_TEMPLATE:
        filled = dict(field)
        if field["id"] == "library":
            filled["choices"] = library_choices
        elif field["id"] == "card_type":
            filled["choices"] = []
            for value, label in card_types:
                slug = slugify_card_type(value)
                thumbnail = thumbnails.get(slug)
                choice = {"value": value, "label": label, "slug": slug}
                if thumbnail:
                    choice["thumbnail"] = thumbnail
                filled["choices"].append(choice)
        elif field["id"] == "watched_style" or field["id"] == "unwatched_style":
            filled["choices"] = [
                {"value": value, "label": value.title()} for value in style_choices
            ]
        elif field["id"] == "episode_data_source":
            filled["choices"] = [
                {"value": value, "label": value} for value in episode_sources
            ]
        elif field["id"] == "font.case" or field["id"] == "episode_text_case":
            filled["choices"] = [
                {"value": value, "label": value} for value in font_cases
            ]
        fields.append(filled)

    return fields


_EXTRA_LABEL_OVERRIDES = {
    "title_text_line_end_offset": "Title Text Margin",
    "title_text_margin": "Title Text Horizontal Offset",
}


def _format_extra_label(key: str) -> str:
    if key in _EXTRA_LABEL_OVERRIDES:
        return _EXTRA_LABEL_OVERRIDES[key]

    parts = [part.capitalize() for part in key.split('_') if part]
    return ' '.join(parts) or 'Custom extra'


def _literal_choices(annotation: Any) -> list[str]:
    origin = get_origin(annotation)
    if origin is Literal:
        return [str(value) for value in get_args(annotation)]

    if origin in (tuple, list, set):
        # Handle nested Literal definitions like tuple[Literal['foo', 'bar'], int]
        choices: list[str] = []
        for arg in get_args(annotation):
            choices.extend(_literal_choices(arg))
        return choices

    if origin is None:
        return []

    choices: list[str] = []
    for arg in get_args(annotation):
        choices.extend(_literal_choices(arg))
    return choices


def _expected_type_label(param: inspect.Parameter | None) -> str | None:
    if param is None:
        return None

    expected = TitleCard._expected_type(param)
    if expected is bool:
        return 'boolean'
    if expected is float:
        return 'float'
    if expected is int:
        return 'int'
    return None


def _build_extra_definition(
        name: str,
        param: inspect.Parameter | None = None,
        *,
        expected_type: str | None = None,
    ) -> dict[str, Any]:
    definition: dict[str, Any] = {
        "key": name,
        "label": _format_extra_label(name),
    }

    expected_type_label = expected_type or _expected_type_label(param)
    if expected_type_label:
        definition["expectedType"] = expected_type_label

    choices = _literal_choices(param.annotation) if param else []
    if expected_type == 'boolean':
        choices = choices or ['true', 'false']

    unique_choices: list[str] = []
    for choice in choices:
        if choice not in unique_choices:
            unique_choices.append(choice)

    if unique_choices:
        definition["choices"] = unique_choices

    return definition


def build_card_type_extras() -> dict[str, list[dict[str, Any]]]:
    """Return a mapping of card types to supported extra option definitions."""

    base_parameters = {
        "source_file",
        "card_file",
        "title_text",
        "season_text",
        "episode_text",
        "hide_season_text",
        "hide_episode_text",
        "blur",
        "grayscale",
        "watched",
        "preferences",
        "unused",
        "font_color",
        "font_file",
        "font_interline_spacing",
        "font_interword_spacing",
        "font_kerning",
        "font_size",
        "font_stroke_width",
        "font_vertical_shift",
        "font_replacements",
        "title_text_format",
        "episode_text_format",
        "season_number",
        "episode_number",
        "library",
    }

    universal_extras: dict[str, dict[str, list[str]]] = {
        "episode_text_font_size": {},
        "episode_text_stroke_color": {},
        "episode_text_stroke_width": {},
        "episode_title_stroke_color": {},
        "episode_title_stroke_width": {},
        "episode_text_font": {},
        "episode_text_case": {
            "choices": list(BaseCardType.CASE_FUNCTIONS.keys()),
        },
        "episode_text_vertical_shift": {
            "expectedType": "int",
        },
    }

    extras: dict[str, list[dict[str, Any]]] = {}
    for identifier, card_type in TitleCard.BUILTIN_CARD_TYPES.items():
        parameters = list(inspect.signature(card_type.__init__).parameters.values())[1:]
        definitions: dict[str, dict[str, Any]] = {}

        for parameter in parameters:
            if parameter.name in base_parameters:
                continue
            definitions[parameter.name] = _build_extra_definition(parameter.name, parameter)

        for key, options in universal_extras.items():
            definition = definitions.setdefault(
                key,
                _build_extra_definition(key, expected_type=options.get("expectedType")),
            )
            if choices := options.get("choices"):
                definition.setdefault("choices", choices)

        extras[identifier] = sorted(definitions.values(), key=lambda item: item["label"].casefold())

    return extras
