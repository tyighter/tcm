from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

import webui.tautulli as tautulli
from webui.tautulli import (
    _plex_watched_changes,
    _reset_plex_watch_state_cache,
    _series_lookup,
    _trigger_builds_for_recent_changes,
)


class DummyTvManager:
    def __init__(self) -> None:
        self.data = {
            "series": {
                "Example": {
                    "rating_key": 101,
                    "library": "TV",
                    "watched_style": "style",
                }
            }
        }

    def load(self):  # pragma: no cover - trivial data access
        return self.data


class DummyPlex:
    def __init__(self, show_rating_key: str) -> None:
        self.episodes = [
            {
                "episode_rating_key": f"{show_rating_key}-1",
                "show_rating_key": show_rating_key,
                "title": "Pilot",
                "season": 1,
                "watched": False,
            }
        ]

    def expand_rating_key_to_episodes(self, rating_key):  # pragma: no cover - trivial passthrough
        return [dict(item) for item in self.episodes]

    def set_watched(self, watched: bool) -> None:
        for episode in self.episodes:
            episode["watched"] = watched


class DummyContext:
    def __init__(self, plex: DummyPlex, use_fallback: bool) -> None:
        self.preference_parser = SimpleNamespace(
            tautulli_use_plex_fallback=use_fallback, use_plex=True
        )
        self._plex = plex

    def get_plex_interface(self) -> DummyPlex:  # pragma: no cover - trivial accessor
        return self._plex


class PlexWatchStateTests(TestCase):
    def _run_watch_toggle_flow(self, use_fallback: bool) -> None:
        tv_manager = DummyTvManager()
        plex = DummyPlex("show-1")
        context = DummyContext(plex, use_fallback)
        lookup = _series_lookup(tv_manager)

        _reset_plex_watch_state_cache()

        initial = _plex_watched_changes(context, lookup)
        self.assertEqual(initial, [])

        plex.set_watched(True)
        synthetic = _plex_watched_changes(context, lookup)

        self.assertEqual(len(synthetic), 1)
        self.assertEqual(synthetic[0]["series"], "Example")
        self.assertFalse(synthetic[0].get("unwatch", False))

        previous_payload = {"watched": [], "added": []}
        current_payload = {"watched": synthetic, "added": []}

        with patch("webui.tautulli.run_builder_for_series") as run_builder:
            _trigger_builds_for_recent_changes(
                context, tv_manager, previous_payload, current_payload
            )
            run_builder.assert_called_once_with(context, tv_manager, "Example")

        plex.set_watched(False)
        unwatched = _plex_watched_changes(context, lookup, recent_watches=synthetic)

        self.assertEqual(len(unwatched), 1)
        self.assertEqual(unwatched[0]["series"], "Example")
        self.assertTrue(unwatched[0].get("unwatch"))

        previous_payload = current_payload
        current_payload = {"watched": synthetic + unwatched, "added": []}

        with patch("webui.tautulli.run_builder_for_series") as run_builder:
            _trigger_builds_for_recent_changes(
                context, tv_manager, previous_payload, current_payload
            )
            run_builder.assert_called_once_with(context, tv_manager, "Example")

    def test_watch_toggle_triggers_build_with_fallback_enabled(self) -> None:
        self._run_watch_toggle_flow(use_fallback=True)

    def test_watch_toggle_triggers_build_with_fallback_disabled(self) -> None:
        self._run_watch_toggle_flow(use_fallback=False)

    def test_unwatch_inferred_from_history_after_quick_toggle(self) -> None:
        tv_manager = DummyTvManager()
        plex = DummyPlex("show-1")
        context = DummyContext(plex, use_fallback=True)
        lookup = _series_lookup(tv_manager)

        _reset_plex_watch_state_cache()

        # Seed the cache with an initial poll
        _plex_watched_changes(context, lookup)

        watch_timestamp = tautulli._plex_watch_state_last_polled or 0  # type: ignore[attr-defined]

        recent_watch_entry = {
            "series": "Example",
            "episode": "Pilot",
            "season": "Season 1",
            "timestamp": watch_timestamp + 1000,
            "showRatingKey": "show-1",
            "episodeRatingKey": "show-1-1",
        }

        # Plex reports the episode as unwatched, but we observed a watch event after the last poll.
        unwatched = _plex_watched_changes(
            context, lookup, recent_watches=[recent_watch_entry]
        )

        self.assertEqual(len(unwatched), 1)
        self.assertTrue(unwatched[0].get("unwatch"))


class ActivityDeduplicationTests(TestCase):
    def test_repeated_watch_events_are_treated_as_new_entries(self) -> None:
        tv_manager = DummyTvManager()
        plex = DummyPlex("show-1")
        context = DummyContext(plex, use_fallback=True)

        previous_entry = {
            "series": "Example",
            "episode": "Pilot",
            "season": "Season 1",
            "timestamp": 1000,
            "showRatingKey": "show-1",
            "episodeRatingKey": "show-1-1",
        }
        new_entry = dict(previous_entry)
        new_entry["timestamp"] = previous_entry["timestamp"] + 1

        previous_payload = {"watched": [previous_entry], "added": []}
        current_payload = {"watched": [previous_entry, new_entry], "added": []}

        with patch("webui.tautulli.run_builder_for_series") as run_builder:
            _trigger_builds_for_recent_changes(
                context, tv_manager, previous_payload, current_payload
            )
            run_builder.assert_called_once_with(context, tv_manager, "Example")
