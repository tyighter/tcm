from datetime import datetime, timedelta
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


def test_backup_daily_creates_dated_files_and_prunes(tmp_path: Path) -> None:
    tv_file = tmp_path / "tv.yml"
    tv_file.write_text("libraries: {}\nseries: {}\n")

    manager = TvYamlManager(tv_file)

    base_date = datetime(2024, 1, 1)
    for offset in range(9):
        manager.backup_daily(now=base_date + timedelta(days=offset), keep=7)

    backup_dir = tv_file.parent / "backups"
    backups = sorted(backup_dir.glob("tv-*.yml"))

    assert len(backups) == 7
    assert backups[-1].name == "tv-20240109.yml"
    assert backups[0].name == "tv-20240103.yml"


def test_backup_on_save_creates_latest_copy(tmp_path: Path) -> None:
    tv_file = tmp_path / "tv.yml"
    tv_file.write_text("libraries: {}\nseries: {}\n")

    manager = TvYamlManager(tv_file)
    backup_path = manager.backup_on_save()

    assert backup_path is not None
    assert backup_path.name == "tv-latest.yml"
    assert backup_path.read_text() == tv_file.read_text()

    tv_file.write_text("libraries: {main: []}\nseries: {}\n")
    manager.backup_on_save()

    assert backup_path.read_text() == tv_file.read_text()
