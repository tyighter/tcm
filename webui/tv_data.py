from __future__ import annotations

import logging
import re
import shutil
from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path
from threading import Event, Thread
from typing import Any

from modules.CleanPath import CleanPath
from modules.Show import Show

from ruamel.yaml import YAML
from ruamel.yaml.composer import ComposerError
from ruamel.yaml.parser import ParserError
from ruamel.yaml.scanner import ScannerError
from ruamel.yaml.comments import CommentedMap, CommentedSeq
from ruamel.yaml.scalarstring import DoubleQuotedScalarString


logger = logging.getLogger(__name__)


_DAILY_BACKUP_INTERVAL = timedelta(days=1)
_backup_thread: Thread | None = None
_backup_stop_event = Event()


class TvYamlManager:
    """Utility for reading and writing the tv.yml configuration."""

    def __init__(self, file_path: Path) -> None:
        self.file_path = file_path
        self._yaml = YAML()
        self._yaml.indent(sequence=4, offset=2)
        self._yaml.preserve_quotes = True
        self._data: CommentedMap[str, Any] | None = None

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------
    def load(self) -> CommentedMap:
        """Load the YAML content from disk."""

        if self._data is not None:
            return self._data

        if not self.file_path.exists():
            self._data = CommentedMap(
                {
                    "libraries": CommentedMap(),
                    "series": CommentedMap(),
                }
            )
            return self._data

        try:
            with self.file_path.open("r", encoding="utf-8") as handle:
                data = self._yaml.load(handle) or CommentedMap()
        except (ComposerError, ParserError, ScannerError) as exc:
            try:
                with self.file_path.open("r", encoding="utf-8") as handle:
                    documents = list(self._yaml.load_all(handle))
            except Exception as inner_exc:  # pylint: disable=broad-except
                message = (
                    "Unable to parse tv.yml; check YAML formatting for syntax errors"
                    f" ({exc})"
                )
                raise ValueError(message) from inner_exc

            data = CommentedMap()
            for document in documents:
                if document is None:
                    continue

                if isinstance(document, CommentedMap):
                    update = document
                elif isinstance(document, dict):
                    update = CommentedMap(document)
                else:
                    continue

                data.update(update)

        if not isinstance(data, CommentedMap):
            data = CommentedMap(data or {})

        if "libraries" not in data or data["libraries"] is None:
            data["libraries"] = CommentedMap()
        if "series" not in data or data["series"] is None:
            data["series"] = CommentedMap()
        if "rating_tmdb_lookup" not in data or data["rating_tmdb_lookup"] is None:
            data["rating_tmdb_lookup"] = CommentedMap()

        self._data = data
        return data

    def as_payload(self) -> dict[str, Any]:
        """Return the YAML content as JSON-serialisable payload."""

        data = self.load()
        libraries = _to_builtin(data.get("libraries", CommentedMap()))
        rating_lookup = _to_builtin(data.get("rating_tmdb_lookup", CommentedMap()))
        series_entries = []
        for name, config in data.get("series", CommentedMap()).items():
            series_entries.append(
                {
                    "name": name,
                    "slug": _series_slug(name),
                    "config": _apply_series_defaults(name, _to_builtin(config)),
                }
            )

        return {
            "libraries": libraries,
            "rating_tmdb_lookup": rating_lookup,
            "series": series_entries,
        }

    def write(self, payload: dict[str, Any]) -> None:
        """Persist the provided payload to disk."""

        libraries = payload.get("libraries")
        rating_lookup = payload.get("rating_tmdb_lookup")
        series_payload = payload.get("series", [])

        current = self.load()
        if libraries is not None:
            current["libraries"] = _to_commented(libraries)
        if rating_lookup is not None:
            current["rating_tmdb_lookup"] = _to_commented(rating_lookup)

        series_map = CommentedMap()
        sorted_series = sorted(
            series_payload,
            key=lambda item: str(item.get("name", "")).casefold(),
        )

        for entry in sorted_series:
            name = entry.get("name")
            config = entry.get("config", {})
            if not name:
                continue
            quoted_name = DoubleQuotedScalarString(str(name))
            series_map[quoted_name] = _to_commented(config)

        current["series"] = series_map

        with self.file_path.open("w", encoding="utf-8") as handle:
            self._yaml.dump(current, handle)

        self._data = current

    def backup_daily(self, *, now: datetime | None = None, keep: int = 7) -> Path | None:
        """Create a dated backup of the tv.yml file and prune old copies."""

        if not self.file_path.exists():
            return None

        timestamp = (now or datetime.now()).strftime("%d%m%Y")
        backup_dir = self._backup_directory()
        backup_dir.mkdir(parents=True, exist_ok=True)

        target = backup_dir / f"{self.file_path.stem}-{timestamp}{self.file_path.suffix}"
        if not target.exists():
            shutil.copy2(self.file_path, target)

        self._rotate_backups(keep=keep)
        return target

    def backup_on_save(self) -> Path | None:
        """Create a single rolling backup for manual saves."""

        if not self.file_path.exists():
            return None

        backup_dir = self._backup_directory()
        backup_dir.mkdir(parents=True, exist_ok=True)

        target = backup_dir / f"{self.file_path.stem}-latest{self.file_path.suffix}"
        shutil.copy2(self.file_path, target)
        return target

    def backup_directory(self) -> Path:
        """Return the directory used for backup files."""

        return self._backup_directory()

    def restore_from_backup(self, source: Path) -> Path:
        """Restore ``tv.yml`` from a backup file inside the backup directory."""

        base = self._backup_directory().resolve(strict=False)
        base.mkdir(parents=True, exist_ok=True)

        candidate = source if source.is_absolute() else (base / source)
        candidate = candidate.resolve(strict=False)

        try:
            candidate.relative_to(base)
        except ValueError as exc:  # pragma: no cover - safety guard
            raise ValueError("Backup file must be within the backup directory") from exc

        if not candidate.exists() or not candidate.is_file():
            raise ValueError(f"Backup file not found: {candidate}")

        shutil.copy2(candidate, self.file_path)
        self.invalidate()
        return candidate

    def invalidate(self) -> None:
        """Drop the cached YAML data so it is reloaded on next access."""

        self._data = None

    def clone_series_yaml(self, name: str, config: dict[str, Any]) -> dict[str, Any]:
        """Return a deep copy of the provided series YAML."""

        return deepcopy(config)

    def update_episode_rating_keys(
        self,
        series_name: str,
        show_rating_key: Any,
        episode_keys_by_label: dict[str, Any],
    ) -> bool:
        """Persist episode rating keys for a given series and show key.

        Args:
            series_name: Series entry in ``tv.yml`` to update.
            show_rating_key: The Plex rating key identifying the show.
            episode_keys_by_label: Mapping of episode labels (e.g., ``"S1E1"``)
                to episode-level Plex rating keys.

        Returns:
            ``True`` if the YAML content was updated, ``False`` otherwise.
        """

        if not episode_keys_by_label:
            return False

        tv_data = self.load()
        series_entries = tv_data.get("series", CommentedMap())
        if series_name not in series_entries:
            return False

        normalized_show_key = _normalize_rating_key(show_rating_key)
        if normalized_show_key is None:
            return False

        config = _to_builtin(series_entries.get(series_name, {}))
        existing_mappings: dict[str, dict[str, Any]] = (
            config.get("episode_rating_keys") or {}
        )
        current = existing_mappings.get(normalized_show_key, {})

        changes: dict[str, Any] = {}
        for label, rating_key in episode_keys_by_label.items():
            normalized_episode_key = _normalize_rating_key(rating_key)
            if not label or normalized_episode_key is None:
                continue
            if str(current.get(label)) == normalized_episode_key:
                continue
            changes[label] = normalized_episode_key

        if not changes:
            return False

        merged = {**current, **changes}
        existing_mappings[normalized_show_key] = merged
        config["episode_rating_keys"] = existing_mappings

        series_entries[series_name] = _to_commented(config)

        with self.file_path.open("w", encoding="utf-8") as handle:
            self._yaml.dump(tv_data, handle)

        self._data = tv_data
        return True

    def _backup_directory(self) -> Path:
        return Path("/config/backups")

    def _rotate_backups(self, *, keep: int) -> None:
        if keep < 1:
            keep = 1

        pattern = re.compile(
            rf"^{re.escape(self.file_path.stem)}-\d{{8}}{re.escape(self.file_path.suffix)}$"
        )

        backups = [
            path
            for path in self._backup_directory().glob("*")
            if path.is_file() and pattern.match(path.name)
        ]

        backups.sort(key=lambda p: p.name, reverse=True)
        for extra in backups[keep:]:
            try:
                extra.unlink()
            except OSError as exc:  # pylint: disable=broad-except
                logger.warning("Unable to prune old tv.yml backup %s: %s", extra, exc)


def start_daily_tv_yaml_backup(
    tv_manager: TvYamlManager,
    *,
    keep: int = 7,
    interval: timedelta = _DAILY_BACKUP_INTERVAL,
) -> Thread:
    """Start a background thread that creates daily tv.yml backups."""

    global _backup_thread

    if _backup_thread and _backup_thread.is_alive():
        return _backup_thread

    _backup_stop_event.clear()

    def _task() -> None:
        while not _backup_stop_event.is_set():
            try:
                tv_manager.backup_daily(keep=keep)
            except Exception as exc:  # pylint: disable=broad-except
                logger.warning("Unable to create daily tv.yml backup: %s", exc)

            if _backup_stop_event.wait(interval.total_seconds()):
                break

    _backup_thread = Thread(target=_task, name="tv.yml-backups", daemon=True)
    _backup_thread.start()
    return _backup_thread


# ----------------------------------------------------------------------
# Conversion helpers
# ----------------------------------------------------------------------

def _to_builtin(value: Any) -> Any:
    """Convert ruamel Commented structures to builtins recursively."""

    if isinstance(value, CommentedMap):
        return {key: _to_builtin(val) for key, val in value.items()}
    if isinstance(value, CommentedSeq):
        return [_to_builtin(item) for item in value]
    return value


def _normalize_rating_key(value: Any) -> str | None:
    """Return a string representation of a rating key or ``None``."""

    try:
        numeric = int(value)
        return str(numeric)
    except (TypeError, ValueError):
        try:
            return str(value) if value is not None else None
        except Exception:
            return None


def _series_slug(name: str) -> str:
    """Return a filesystem-safe slug for the given series name."""

    return CleanPath.sanitize_name(str(name))


def _to_commented(value: Any) -> Any:
    """Convert python structures into ruamel Commented equivalents."""

    if isinstance(value, dict):
        commented = CommentedMap()
        for key, val in value.items():
            commented[key] = _to_commented(val)
        return commented
    if isinstance(value, (list, tuple)):
        seq = CommentedSeq()
        for item in value:
            seq.append(_to_commented(item))
        return seq
    return value


def _apply_series_defaults(name: str, config: dict[str, Any]) -> dict[str, Any]:
    """Apply runtime defaults so they surface in the web UI."""

    card_type = config.get("card_type")

    extras = config.get("extras") if isinstance(config.get("extras"), dict) else {}
    translations_raw = config.get("translation")

    translations: list[dict[str, Any]] = []
    if isinstance(translations_raw, dict) and translations_raw.keys() == {"language", "key"}:
        translations = [translations_raw]
    elif isinstance(translations_raw, list):
        translations = [
            translation
            for translation in translations_raw
            if isinstance(translation, dict) and translation.keys() >= {"language", "key"}
        ]

    if card_type == "anime" and not translations:
        translations = [dict(Show.DEFAULT_ANIME_TRANSLATION)]

    if card_type in Show.DEFAULT_LOGO_CARD_TYPES and "logo" not in extras:
        extras["logo"] = f"/config/source/{name}/logo.png"

    if translations:
        config["translation"] = translations
    elif translations_raw is not None:
        config["translation"] = []

    if extras:
        config["extras"] = extras

    return config
