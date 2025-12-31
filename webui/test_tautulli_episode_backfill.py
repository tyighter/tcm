import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import webui.tautulli as tautulli
from webui.tautulli import (
    TautulliSettings,
    _backfill_episode_rating_keys,
    _monitor_stop_event,
    start_recent_activity_monitor,
)
from webui.tv_data import TvYamlManager


class _DummyContext:
    def __init__(self, plex):
        self.preference_parser = SimpleNamespace(
            use_plex=True, tautulli_activity_poll_interval_seconds=15
        )
        self._plex = plex

    def get_plex_interface(self):
        return self._plex


class EpisodeRatingKeyBackfillTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.tv_file = Path(self.tempdir.name) / "tv.yml"

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _write_tv_file(self, content: str) -> TvYamlManager:
        self.tv_file.write_text(content, encoding="utf-8")
        return TvYamlManager(self.tv_file)

    def test_backfill_populates_missing_mapping_for_show_and_fallback_keys(self) -> None:
        manager = self._write_tv_file(
            """
libraries: {}
series:
  "Example (2024)":
    library: TV
    rating_key: 555
"""
        )

        plex = MagicMock()
        plex.expand_rating_key_to_episodes.return_value = [
            {
                "season": 1,
                "episode": 1,
                "episode_rating_key": 901,
                "show_rating_key": 999,
            },
            {
                "season": 1,
                "episode": 2,
                "episode_rating_key": 902,
                "show_rating_key": 999,
            },
        ]

        context = _DummyContext(plex)

        result = _backfill_episode_rating_keys(context, manager)

        self.assertEqual(result.get("updated"), 1)
        data = manager.load()
        mappings = data["series"]["Example (2024)"]["episode_rating_keys"]

        self.assertIn("999", mappings)
        self.assertEqual(
            mappings["999"],
            {
                "S1E1": "901",
                "S1E2": "902",
            },
        )
        self.assertIn("555", mappings)

    def test_backfill_merges_when_mapping_incomplete(self) -> None:
        manager = self._write_tv_file(
            """
libraries: {}
series:
  "Example (2024)":
    rating_key: 555
    episode_rating_keys:
      "555":
        S1E1: "901"
"""
        )

        plex = MagicMock()
        plex.expand_rating_key_to_episodes.return_value = [
            {
                "season": 1,
                "episode": 1,
                "episode_rating_key": 901,
                "show_rating_key": 555,
            },
            {
                "season": 1,
                "episode": 2,
                "episode_rating_key": 902,
                "show_rating_key": 555,
            },
        ]
        context = _DummyContext(plex)

        result = _backfill_episode_rating_keys(context, manager)

        self.assertEqual(result.get("updated"), 1)
        plex.expand_rating_key_to_episodes.assert_called_once_with(555)

        data = manager.load()
        mappings = data["series"]["Example (2024)"]["episode_rating_keys"]
        self.assertEqual(
            mappings["555"],
            {
                "S1E1": "901",
                "S1E2": "902",
            },
        )


class StartMonitorBackfillTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.tv_file = Path(self.tempdir.name) / "tv.yml"
        self.tv_file.write_text(
            """
libraries: {}
series:
  "Example (2024)":
    rating_key: 555
""",
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        _monitor_stop_event.set()
        tautulli._monitor_thread = None
        self.tempdir.cleanup()

    def test_monitor_initialization_runs_episode_backfill(self) -> None:
        manager = TvYamlManager(self.tv_file)
        plex = MagicMock()
        context = _DummyContext(plex)

        settings = TautulliSettings(url="http://localhost", api_key="abc123")

        with patch(
            "webui.tautulli.TautulliSettings.from_settings", return_value=settings
        ), patch(
            "webui.tautulli._monitor_recent_activity", side_effect=lambda *_: None
        ), patch(
            "webui.tautulli._backfill_episode_rating_keys"
        ) as backfill_mock:
            thread = start_recent_activity_monitor(context, manager, interval_seconds=0)

        backfill_mock.assert_called_once_with(context, manager)

        if thread:
            thread.join(timeout=1)
