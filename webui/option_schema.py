from __future__ import annotations

import inspect
from collections.abc import Iterable
from typing import Any

from modules.TitleCard import TitleCard

OptionMetadata = dict[str, Any]


_BASE_PARAMETER_NAMES = {
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


def _titleize(raw: str) -> str:
    return ' '.join(segment.capitalize() for segment in raw.split('_') if segment)


def _merge_aliases(*groups: Iterable[str]) -> list[str]:
    aliases: list[str] = []
    for group in groups:
        for value in group:
            if value and value not in aliases:
                aliases.append(value)
    return aliases


COMMON_OPTION_SCHEMA: dict[str, OptionMetadata] = {
    "episode_text_font": {
        "canonical_key": "episode_number_text_font_file",
        "legacy_keys": ["episode_text_font"],
        "label": "Episode Number Font",
        "description": "Font file used for episode index text.",
        "category": "Episode Number Text",
    },
    "episode_text_case": {
        "canonical_key": "episode_number_text_case",
        "legacy_keys": ["episode_text_case"],
        "label": "Episode Number Case",
        "description": "Character casing applied to episode index text.",
        "category": "Episode Number Text",
    },
    "episode_text_font_size": {
        "canonical_key": "episode_number_text_size",
        "legacy_keys": ["episode_text_font_size"],
        "label": "Episode Number Size",
        "description": "Scales the index text (for example, 'EPISODE 5'), not the episode title.",
        "category": "Episode Number Text",
    },
    "episode_text_vertical_shift": {
        "canonical_key": "episode_number_text_vertical_shift",
        "legacy_keys": ["episode_text_vertical_shift"],
        "label": "Episode Number Vertical Shift",
        "description": "Vertical pixel shift applied to episode index text.",
        "category": "Episode Number Text",
    },
    "episode_text_stroke_color": {
        "canonical_key": "episode_number_text_stroke_color",
        "legacy_keys": ["episode_text_stroke_color", "episode_stroke_color"],
        "label": "Episode Number Stroke Color",
        "description": "Stroke color used around episode index text.",
        "category": "Episode Number Text",
    },
    "episode_text_stroke_width": {
        "canonical_key": "episode_number_text_stroke_width",
        "legacy_keys": ["episode_text_stroke_width"],
        "label": "Episode Number Stroke Width",
        "description": "Stroke width used around episode index text.",
        "category": "Episode Number Text",
    },
    "episode_title_stroke_color": {
        "canonical_key": "episode_title_text_stroke_color",
        "legacy_keys": ["episode_title_stroke_color", "stroke_color"],
        "label": "Episode Title Stroke Color",
        "description": "Stroke color used around episode title text.",
        "category": "Episode Title Text",
    },
    "episode_title_stroke_width": {
        "canonical_key": "episode_title_text_stroke_width",
        "legacy_keys": ["episode_title_stroke_width"],
        "label": "Episode Title Stroke Width",
        "description": "Stroke width used around episode title text.",
        "category": "Episode Title Text",
    },
    "title_text_margin": {
        "canonical_key": "episode_title_text_horizontal_offset",
        "legacy_keys": ["title_text_margin"],
        "label": "Episode Title Horizontal Offset",
        "description": "Horizontal offset applied to episode title text.",
        "category": "Episode Title Text",
    },
    "title_text_line_end_offset": {
        "canonical_key": "episode_title_text_margin",
        "legacy_keys": ["title_text_line_end_offset"],
        "label": "Episode Title Margin",
        "description": "Horizontal spacing used only for episode title text wrapping.",
        "category": "Episode Title Text",
    },
}


_PREFIX_RULES: tuple[tuple[str, str, str, str | None], ...] = (
    ("font_", "Episode Title Text", "Controls for episode title text.", None),
    ("episode_text_", "Episode Number Text", "Controls for episode index text.", "episode_number_text_"),
    ("title_text", "Episode Title Text", "Controls for episode title text.", "episode_title_text"),
    ("season_text_", "Episode Number Text", "Controls for season/index text rendering.", None),
    ("border_", "Borders", "Controls border styling.", None),
    ("line_", "Layout", "Controls line placement and styling.", None),
    ("shape_", "Layout", "Controls shape placement and styling.", None),
    ("graph_", "Layout", "Controls graph styling and geometry.", None),
    ("background", "Background", "Controls background appearance.", None),
    ("overlay_", "Background", "Controls color overlays and blending.", None),
    ("banner_", "Layout", "Controls banner styling and placement.", None),
    ("text_box_", "Layout", "Controls text box styling and layout.", None),
    ("frame_", "Borders", "Controls frame/border presentation.", None),
    ("box_", "Layout", "Controls card box geometry and styling.", None),
)


def option_metadata_for_key(raw_key: str) -> OptionMetadata:
    common = COMMON_OPTION_SCHEMA.get(raw_key)
    if common:
        return {
            "canonical_key": common["canonical_key"],
            "legacy_keys": _merge_aliases(common.get("legacy_keys", []), [raw_key]),
            "label": common["label"],
            "description": common["description"],
            "category": common["category"],
        }

    for prefix, category, category_description, canonical_prefix in _PREFIX_RULES:
        if raw_key.startswith(prefix):
            canonical_key = raw_key
            if canonical_prefix:
                if prefix.endswith("_"):
                    suffix = raw_key[len(prefix):]
                    canonical_key = f"{canonical_prefix}{suffix}"
                else:
                    suffix = raw_key[len(prefix):]
                    canonical_key = f"{canonical_prefix}{suffix}"
            return {
                "canonical_key": canonical_key,
                "legacy_keys": [raw_key],
                "label": _titleize(raw_key),
                "description": f"{category_description} ({raw_key}).",
                "category": category,
            }

    return {
        "canonical_key": raw_key,
        "legacy_keys": [raw_key],
        "label": _titleize(raw_key),
        "description": f"Card-specific option for {raw_key}.",
        "category": "Card Specific",
    }


def build_card_type_option_schema() -> dict[str, OptionMetadata]:
    """Build canonical option metadata for all known card-type constructor extras."""

    schema = {key: option_metadata_for_key(key) for key in COMMON_OPTION_SCHEMA}

    for card_type in TitleCard.BUILTIN_CARD_TYPES.values():
        for parameter in list(inspect.signature(card_type.__init__).parameters.values())[1:]:
            if parameter.name in _BASE_PARAMETER_NAMES:
                continue
            schema.setdefault(parameter.name, option_metadata_for_key(parameter.name))


    return schema
