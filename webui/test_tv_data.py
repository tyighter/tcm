from pathlib import Path

import pytest

from webui.tv_data import TvYamlManager


def test_load_raises_value_error_for_invalid_yaml(tmp_path: Path) -> None:
    invalid_yaml = """
series:
  Show Name
    rating_key: 123
"""
    tv_file = tmp_path / "tv.yml"
    tv_file.write_text(invalid_yaml)

    manager = TvYamlManager(tv_file)

    with pytest.raises(ValueError) as excinfo:
        manager.load()

    assert "Unable to parse tv.yml" in str(excinfo.value)
    assert str(tv_file) in str(excinfo.value.__cause__)
