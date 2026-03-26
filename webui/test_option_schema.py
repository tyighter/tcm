from webui.option_schema import build_card_type_option_schema, option_metadata_for_key
from webui.options import build_card_type_extras


def test_common_episode_text_metadata_contains_aliases() -> None:
    metadata = option_metadata_for_key("episode_text_stroke_color")

    assert metadata["canonical_key"] == "episode_index_text_stroke_color"
    assert "episode_stroke_color" in metadata["legacy_keys"]
    assert metadata["category"] == "Episode Number Text"


def test_card_type_option_schema_covers_constructor_extras() -> None:
    schema = build_card_type_option_schema()

    assert "title_text_margin" in schema
    assert schema["title_text_margin"]["category"] == "Episode Title Text"
    assert "border_color" in schema
    assert schema["border_color"]["category"] == "Borders"


def test_card_type_extras_include_canonical_metadata() -> None:
    extras = build_card_type_extras()

    assert extras, "Expected extras for built-in card types"
    first_card = next(iter(extras.values()))
    first_entry = first_card[0]

    assert "canonicalKey" in first_entry
    assert "legacyKeys" in first_entry
    assert "description" in first_entry
    assert "category" in first_entry
