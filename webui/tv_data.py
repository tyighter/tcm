from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq


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

        with self.file_path.open("r", encoding="utf-8") as handle:
            data = self._yaml.load(handle) or CommentedMap()

        if not isinstance(data, CommentedMap):
            data = CommentedMap(data or {})

        if "libraries" not in data or data["libraries"] is None:
            data["libraries"] = CommentedMap()
        if "series" not in data or data["series"] is None:
            data["series"] = CommentedMap()

        self._data = data
        return data

    def as_payload(self) -> dict[str, Any]:
        """Return the YAML content as JSON-serialisable payload."""

        data = self.load()
        libraries = _to_builtin(data.get("libraries", CommentedMap()))
        series_entries = []
        for name, config in data.get("series", CommentedMap()).items():
            series_entries.append(
                {
                    "name": name,
                    "config": _to_builtin(config),
                }
            )

        return {
            "libraries": libraries,
            "series": series_entries,
        }

    def write(self, payload: dict[str, Any]) -> None:
        """Persist the provided payload to disk."""

        libraries = payload.get("libraries")
        series_payload = payload.get("series", [])

        current = self.load()
        if libraries is not None:
            current["libraries"] = _to_commented(libraries)

        series_map = CommentedMap()
        for entry in series_payload:
            name = entry.get("name")
            config = entry.get("config", {})
            if not name:
                continue
            series_map[name] = _to_commented(config)

        current["series"] = series_map

        with self.file_path.open("w", encoding="utf-8") as handle:
            self._yaml.dump(current, handle)

        self._data = current

    def clone_series_yaml(self, name: str, config: dict[str, Any]) -> dict[str, Any]:
        """Return a deep copy of the provided series YAML."""

        return deepcopy(config)


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
