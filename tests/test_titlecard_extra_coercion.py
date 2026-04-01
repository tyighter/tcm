import inspect

from modules.TitleCard import TitleCard
from modules.cards.LandscapeTitleCard import LandscapeTitleCard


def _landscape_param(name: str) -> inspect.Parameter:
    signature = inspect.signature(LandscapeTitleCard.__init__)
    return signature.parameters[name]


def test_expected_type_skips_mixed_literal_bool_union() -> None:
    darken = _landscape_param("darken")

    assert TitleCard._expected_type(darken) is None


def test_expected_type_keeps_true_bool_parameters() -> None:
    blur = _landscape_param("blur")

    assert TitleCard._expected_type(blur) is bool


def test_coerce_extra_types_does_not_coerce_darken_box_to_bool() -> None:
    title_card = TitleCard.__new__(TitleCard)
    title_card.episode = type("EpisodeStub", (), {"card_class": LandscapeTitleCard})()

    kwargs = {"darken": "box"}
    title_card._coerce_extra_types(kwargs)

    assert kwargs["darken"] == "box"


def test_invalid_boolean_still_falls_back_to_default() -> None:
    title_card = TitleCard.__new__(TitleCard)
    title_card.episode = type("EpisodeStub", (), {"card_class": LandscapeTitleCard})()

    kwargs = {"blur": "not-a-bool"}
    title_card._coerce_extra_types(kwargs)

    assert kwargs["blur"] is False


def test_numeric_font_extra_coercion_still_works() -> None:
    title_card = TitleCard.__new__(TitleCard)
    title_card.episode = type("EpisodeStub", (), {"card_class": LandscapeTitleCard})()

    kwargs = {"font_size": "1.25", "font_vertical_shift": "3"}
    title_card._coerce_extra_types(kwargs)

    assert kwargs["font_size"] == 1.25
    assert kwargs["font_vertical_shift"] == 3.0
