from pathlib import Path

from modules.TitleCard import TitleCard


APP_JS_PATH = Path(__file__).resolve().parents[1] / "webui" / "static" / "app.js"


def test_app_js_option_tooltips_include_description_attributes() -> None:
    source = APP_JS_PATH.read_text(encoding="utf-8")

    assert "buildOptionLabel(field.label, field.description)" in source
    assert "function createOptionInfoIcon(description, labelText)" in source
    assert "icon.setAttribute('title', titleText);" in source
    assert "icon.setAttribute('aria-label', titleText);" in source


def test_legacy_and_canonical_option_keys_normalize_to_equivalent_card_extras() -> None:
    TitleCard._LOGGED_ALIAS_WARNINGS.clear()

    legacy = TitleCard._normalize_text_option_aliases(
        {
            "episode_text_case": "title",
            "title_text_margin": 18,
        }
    )
    canonical = TitleCard._normalize_text_option_aliases(
        {
            "episode_number_text_case": "title",
            "episode_title_text_horizontal_offset": 18,
        }
    )

    keys = (
        "episode_number_text_case",
        "episode_text_case",
        "episode_title_text_horizontal_offset",
        "title_text_margin",
    )
    for key in keys:
        assert legacy[key] == canonical[key]
