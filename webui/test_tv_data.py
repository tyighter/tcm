from datetime import datetime, timedelta
from pathlib import Path

import shutil

import pytest
from ruamel.yaml.scanner import ScannerError

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


def test_load_surfaces_line_and_column_for_invalid_yaml(tmp_path: Path) -> None:
    invalid_yaml = """series:
  Show Name:
    rating_key: 123
      library: TV Shows
"""
    tv_file = tmp_path / "tv.yml"
    tv_file.write_text(invalid_yaml)

    manager = TvYamlManager(tv_file)

    with pytest.raises(ValueError) as excinfo:
        manager.load()

    message = str(excinfo.value)
    assert "Unable to parse tv.yml" in message
    assert "Line 4, column 14" in message
    assert "library: TV Shows" in message


def test_load_recovers_when_primary_load_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tv_file = tmp_path / "tv.yml"
    tv_file.write_text(
        """libraries: {}
series:
  "Valid Show":
    rating_key: 123
"""
    )

    manager = TvYamlManager(tv_file)

    def _fail_load(*_args, **_kwargs):
        raise ScannerError("could not find expected ':'", None, None, None)

    monkeypatch.setattr(manager._yaml, "load", _fail_load)

    data = manager.load()

    assert data["series"]["Valid Show"]["rating_key"] == 123


def test_backup_daily_creates_dated_files_and_prunes(tmp_path: Path) -> None:
    tv_file = tmp_path / "tv.yml"
    tv_file.write_text("libraries: {}\nseries: {}\n")

    manager = TvYamlManager(tv_file)
    backup_dir = Path("/config/backups")
    if backup_dir.exists():
        shutil.rmtree(backup_dir)

    base_date = datetime(2024, 1, 1)
    for offset in range(9):
        manager.backup_daily(now=base_date + timedelta(days=offset), keep=7)

    backups = sorted(backup_dir.glob("tv-*.yml"))

    assert len(backups) == 7
    assert backups[-1].name == "tv-09012024.yml"
    assert backups[0].name == "tv-03012024.yml"


def test_backup_on_save_creates_latest_copy(tmp_path: Path) -> None:
    tv_file = tmp_path / "tv.yml"
    tv_file.write_text("libraries: {}\nseries: {}\n")

    manager = TvYamlManager(tv_file)
    backup_dir = Path("/config/backups")
    if backup_dir.exists():
        shutil.rmtree(backup_dir)
    backup_path = manager.backup_on_save()

    assert backup_path is not None
    assert backup_path.name == "tv-latest.yml"
    assert backup_path.read_text() == tv_file.read_text()

    tv_file.write_text("libraries: {main: []}\nseries: {}\n")
    manager.backup_on_save()

    assert backup_path.read_text() == tv_file.read_text()


def test_backup_on_save_recovers_when_copy_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tv_file = tmp_path / "tv.yml"
    tv_file.write_text("libraries: {}\nseries: {}\n")

    manager = TvYamlManager(tv_file)
    backup_dir = Path("/config/backups")
    if backup_dir.exists():
        shutil.rmtree(backup_dir)
    backup_dir.mkdir(parents=True)

    target = backup_dir / "tv-latest.yml"
    target.write_text("stale backup\n")

    def _fail_copy(src: Path, dst: Path) -> None:  # type: ignore[override]
        raise ValueError("I/O operation on closed file.")

    monkeypatch.setattr(shutil, "copy2", _fail_copy)

    backup_path = manager.backup_on_save()

    assert backup_path == target
    assert backup_path.read_text() == tv_file.read_text()


def test_restore_from_backup_replaces_tv_file(tmp_path: Path) -> None:
    tv_file = tmp_path / "tv.yml"
    tv_file.write_text("libraries: {}\nseries: {}\n")

    manager = TvYamlManager(tv_file)
    backup_dir = manager.backup_directory()
    if backup_dir.exists():
        shutil.rmtree(backup_dir)
    backup_dir.mkdir(parents=True)

    backup_file = backup_dir / "tv-latest.yml"
    backup_file.write_text("libraries: {restored: []}\nseries: {restored: {}}\n")

    restored_path = manager.restore_from_backup(backup_file)

    assert restored_path == backup_file.resolve(strict=False)
    assert tv_file.read_text() == backup_file.read_text()


def test_atomic_write_defaults_to_world_writable(tmp_path: Path) -> None:
    tv_file = tmp_path / "tv.yml"
    manager = TvYamlManager(tv_file)

    manager.write({"libraries": {}, "series": []})

    assert (tv_file.stat().st_mode & 0o777) == 0o666


def test_atomic_write_respects_executable_permissions(tmp_path: Path) -> None:
    tv_file = tmp_path / "tv.yml"
    tv_file.write_text("libraries: {}\nseries: {}\n")
    tv_file.chmod(0o777)
    manager = TvYamlManager(tv_file)

    manager.write({"libraries": {}, "series": []})

    assert (tv_file.stat().st_mode & 0o777) == 0o777


def test_backup_and_convert_legacy_keys_creates_backup_and_updates_series(tmp_path: Path) -> None:
    tv_file = tmp_path / "tv.yml"
    tv_file.write_text(
        """libraries: {}
series:
  "Demo Show (2024)":
    episode_text_case: title
    extras:
      title_text_margin: 12
"""
    )

    manager = TvYamlManager(tv_file)

    backup_path, updated_series = manager.backup_and_convert_legacy_keys()

    assert backup_path == tmp_path / "tv-backup.yml"
    assert backup_path.exists()
    assert updated_series == 1

    converted = manager.load()
    series_config = converted["series"]["Demo Show (2024)"]
    assert series_config["episode_number_text_case"] == "title"
    assert series_config["episode_text_case"] == "title"
    assert series_config["extras"]["episode_title_text_horizontal_offset"] == 12
    assert series_config["extras"]["title_text_margin"] == 12
