from pathlib import Path


STYLE_PATH = Path(__file__).resolve().parents[1] / "webui" / "static" / "style.css"


def test_dirty_indicator_hidden_attribute_is_respected() -> None:
    source = STYLE_PATH.read_text(encoding="utf-8")

    assert ".dirty-indicator[hidden]" in source
    assert "display: none;" in source
