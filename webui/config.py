from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Optional

from modules.FontValidator import FontValidator
from modules.MediaInfoSet import MediaInfoSet
from modules.PreferenceParser import PreferenceParser
from modules.ShowRecordKeeper import ShowRecordKeeper
from modules import global_objects


ENV_PREFERENCE_FILE = "TCM_PREFERENCES"
ENV_IS_DOCKER = "TCM_IS_DOCKER"


@dataclass(slots=True)
class AppContext:
    """Shared application context for the web interface."""

    preference_parser: PreferenceParser
    preference_file: Path
    is_docker: bool
    _plex_interface: Optional["PlexInterface"] = None
    _plex_lock: Lock = Lock()

    @property
    def tv_files(self) -> list[Path]:
        """All configured series YAML files from the preferences."""

        files: list[Path] = []
        seen: set[Path] = set()

        for raw_path in self.preference_parser.series_files:
            if not raw_path:
                continue
            path = Path(raw_path)
            if path in seen:
                continue
            files.append(path)
            seen.add(path)

        fallback_candidates = [
            Path("/config/tv.yml"),
            self.preference_file.with_name("tv.yml"),
        ]

        for candidate in fallback_candidates:
            if candidate in seen:
                continue
            if candidate.exists():
                files.append(candidate)
                seen.add(candidate)

        return files

    @property
    def default_tv_file(self) -> Path:
        """Primary TV YAML file to operate on."""

        if not self.tv_files:
            raise RuntimeError(
                "No series YAML files are configured in preferences."
            )
        return self.tv_files[0]

    def get_plex_interface(self) -> "PlexInterface":
        """Lazy-load and cache a Plex interface."""

        from modules.PlexInterface import PlexInterface  # avoid circular import

        if not self.preference_parser.use_plex:
            raise RuntimeError("Plex is not enabled in the preferences file")

        if self._plex_interface is None:
            with self._plex_lock:
                if self._plex_interface is None:
                    self._plex_interface = PlexInterface(
                        **self.preference_parser.plex_interface_kwargs
                    )
        return self._plex_interface


def _resolve_preference_file(repo_root: Path) -> Path:
    """Resolve the preferences file path from environment or defaults."""

    pref = os.environ.get(ENV_PREFERENCE_FILE)
    if pref:
        return Path(pref)

    docker_pref = Path("/config/preferences.yml")
    if docker_pref.exists():
        return docker_pref

    return repo_root / "config" / "preferences.yml"


def create_app_context() -> AppContext:
    """Create the shared application context."""

    repo_root = Path(__file__).resolve().parent.parent
    preference_file = _resolve_preference_file(repo_root)
    is_docker = os.environ.get(ENV_IS_DOCKER, "false").lower() == "true"

    parser = PreferenceParser(preference_file, is_docker)
    if not parser.valid:
        raise RuntimeError("Preferences file is invalid; see logs for details")

    # Populate global objects so downstream modules behave as expected.
    global_objects.set_preference_parser(parser)
    global_objects.set_font_validator(FontValidator())
    global_objects.set_media_info_set(MediaInfoSet())
    global_objects.set_show_record_keeper(
        ShowRecordKeeper(parser.database_directory)
    )

    return AppContext(
        preference_parser=parser,
        preference_file=preference_file,
        is_docker=is_docker,
    )
