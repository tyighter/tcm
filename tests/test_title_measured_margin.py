import pytest

from modules.Title import Title


def test_measured_wrapping_avoids_tight_single_line(monkeypatch):
    title = Title("One Two Three Four")

    def fake_measure(text, *_args, **_kwargs):
        if text == title.full_title:
            return 99.0
        return len(text) * 10.0

    monkeypatch.setattr(Title, "_Title__measure_line_width", staticmethod(fake_measure))

    lines = title.split(
        max_line_width=12,
        max_line_count=2,
        top_heavy=False,
        width_budget=100,
        measurement={"font_file": "fake.ttf", "point_size": 12, "kerning": 0, "interword_spacing": 0},
    )

    assert lines == ["One Two", "Three Four"]
    for line in lines:
        assert fake_measure(line) <= 100
