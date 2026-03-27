from __future__ import annotations

import inspect
from typing import Any, Literal, get_args, get_origin

from modules.BaseCardType import BaseCardType
from modules.PreferenceParser import PreferenceParser
from modules.StyleSet import StyleSet
from modules.TitleCard import TitleCard
from .card_type_images import load_card_type_thumbnails, slugify_card_type
from .option_schema import build_card_type_option_schema, option_metadata_for_key

STYLE_CHOICES = ["unique", "blur", "grayscale", "blur grayscale"]
_BASIC_SERIES_FIELD_IDS = {
    "library",
    "card_type",
    "episode_number_text_format",
    "episode_number_text_case",
    "episode_data_source",
    "watched_style",
    "unwatched_style",
    "image_source_priority",
    "font.file",
    "font.size",
    "font.color",
    "font.case",
    "seasons.hide",
    "seasons.titles",
    "translation",
}

SERIES_FIELD_DESCRIPTIONS = {
    "library": "Choose which media library this series belongs to when importing and syncing.",
    "card_type": "Select the card design template used to render this series.",
    "episode_number_text_format": "Controls the pattern used for episode index text (for example, 'EPISODE 5').",
    "episode_number_text_case": "Sets uppercase/lowercase rules for episode index text, not the episode title.",
    "episode_data_source": "Selects where season and episode metadata is pulled from for this entry.",
    "watched_style": "Visual style applied to cards for watched episodes.",
    "unwatched_style": "Visual style applied to cards for unwatched episodes.",
    "tmdb_id": "TMDb series ID used to fetch metadata and artwork for this show.",
    "tvdb_id": "TVDb series ID used to fetch metadata and artwork for this show.",
    "imdb_id": "IMDb series ID used when matching and syncing metadata.",
    "tvrage_id": "Legacy TVRage ID used for compatibility with older metadata sources.",
    "emby_id": "Emby library item ID used to map this series to Emby.",
    "jellyfin_id": "Jellyfin library item ID used to map this series to Jellyfin.",
    "sonarr_id": "Sonarr series ID used for Sonarr syncing and lookups.",
    "refresh_titles": "When enabled, refreshes episode titles from the configured metadata source.",
    "sync_specials": "Includes season 0/special episodes during metadata sync and card generation.",
    "sonarr_sync": "Enable automatic metadata syncing for this series from Sonarr.",
    "tmdb_sync": "Enable automatic metadata syncing for this series from TMDb.",
    "tmdb_skip_localized_images": "If enabled, ignores localized TMDb images and prefers primary artwork.",
    "archive": "Creates an archive copy of generated cards for this series.",
    "archive_all_variations": "Archives all generated style variations instead of only the active output.",
    "archive_name": "Folder name used when saving archived cards for this series.",
    "library_override": "Overrides the default media directory path used to find this series.",
    "filename_format": "Template used to build output filenames for generated cards.",
    "image_source_priority": "Comma-separated source priority order used when selecting episode images.",
    "translation": "List of title translations to generate in additional languages.",
    "font.file": "Font file used for episode title text (the main title on each card).",
    "font.size": "Episode title text size scale as a percentage of the card type default.",
    "font.color": "Episode title text color.",
    "font.case": "Uppercase/lowercase rules for episode title text only.",
    "font.vertical_shift": "Moves episode title text up or down in pixels.",
    "font.interline_spacing": "Vertical spacing between wrapped episode title lines.",
    "font.interword_spacing": "Additional spacing between words in episode title text.",
    "font.kerning": "Character spacing scale for episode title text.",
    "font.stroke_width": "Outline width around episode title text.",
    "font.validate": "Validates that the selected episode title font can render required characters.",
    "font.replacements": "Character replacement map applied before rendering episode title text.",
    "extras": "Card-type-specific advanced options for this series.",
    "seasons.hide": "Controls whether season labels are hidden on generated cards.",
    "seasons.titles": "Custom display title for each season number.",
    "episode_ranges": "Maps named ranges to groups of episode numbers for batch styling.",
}

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
        "id": "episode_number_text_format",
        "label": "Episode number text format",
        "path": ["episode_number_text_format"],
        "type": "text",
    },
    {
        "id": "episode_number_text_case",
        "label": "Episode number text casing",
        "path": ["episode_number_text_case"],
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
        "label": "Episode title font file",
        "path": ["font", "file"],
        "type": "font",
    },
    {
        "id": "font.size",
        "label": "Episode title size (%)",
        "path": ["font", "size"],
        "type": "text",
    },
    {
        "id": "font.color",
        "label": "Episode title color",
        "path": ["font", "color"],
        "type": "color",
    },
    {
        "id": "font.case",
        "label": "Episode title casing",
        "path": ["font", "case"],
        "type": "font-case",
    },
    {
        "id": "font.vertical_shift",
        "label": "Episode title vertical shift",
        "path": ["font", "vertical_shift"],
        "type": "number",
    },
    {
        "id": "font.interline_spacing",
        "label": "Episode title line spacing",
        "path": ["font", "interline_spacing"],
        "type": "number",
    },
    {
        "id": "font.interword_spacing",
        "label": "Episode title word spacing",
        "path": ["font", "interword_spacing"],
        "type": "number",
    },
    {
        "id": "font.kerning",
        "label": "Episode title kerning",
        "path": ["font", "kerning"],
        "type": "text",
    },
    {
        "id": "font.stroke_width",
        "label": "Episode title stroke width",
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
        "label": "Episode title replacements",
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
        filled["description"] = SERIES_FIELD_DESCRIPTIONS.get(
            field["id"],
            f"Configure {field['label'].lower()} for this series.",
        )
        filled["tier"] = "basic" if field["id"] in _BASIC_SERIES_FIELD_IDS else "advanced"
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
        elif field["id"] == "font.case" or field["id"] == "episode_number_text_case":
            filled["choices"] = [
                {"value": value, "label": value} for value in font_cases
            ]
        fields.append(filled)

    return fields


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
    metadata = option_metadata_for_key(name)
    definition: dict[str, Any] = {
        "key": name,
        "canonicalKey": metadata["canonical_key"],
        "legacyKeys": metadata["legacy_keys"],
        "label": metadata["label"],
        "description": metadata["description"],
        "category": metadata["category"],
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

    option_schema = build_card_type_option_schema()
    extras: dict[str, list[dict[str, Any]]] = {}
    for identifier, card_type in TitleCard.BUILTIN_CARD_TYPES.items():
        parameters = list(inspect.signature(card_type.__init__).parameters.values())[1:]
        definitions: dict[str, dict[str, Any]] = {}

        for parameter in parameters:
            if parameter.name in base_parameters:
                continue
            metadata = option_schema.get(parameter.name)
            definitions[parameter.name] = _build_extra_definition(parameter.name, parameter)
            if metadata:
                definitions[parameter.name].setdefault("canonicalKey", metadata["canonical_key"])
                definitions[parameter.name].setdefault("legacyKeys", metadata["legacy_keys"])
                definitions[parameter.name].setdefault("description", metadata["description"])
                definitions[parameter.name].setdefault("category", metadata["category"])

        for key, options in universal_extras.items():
            definition = definitions.setdefault(
                key,
                _build_extra_definition(key, expected_type=options.get("expectedType")),
            )
            if choices := options.get("choices"):
                definition.setdefault("choices", choices)

        extras[identifier] = sorted(definitions.values(), key=lambda item: item["label"].casefold())

    return extras
