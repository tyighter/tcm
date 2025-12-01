from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock, Mock

from modules.PlexInterface import PlexInterface


def make_stub_episode(season: int, episode: int) -> SimpleNamespace:
    episode_info = SimpleNamespace(
        season_number=season, episode_number=episode
    )
    return SimpleNamespace(
        episode_info=episode_info,
        update_statuses=Mock(),
        spoil_type=None,
        delete_card=Mock(),
    )


class PlexEpisodeWatchedHelperTests(TestCase):
    def setUp(self) -> None:
        self.interface = PlexInterface.__new__(PlexInterface)

    def test_view_count_marks_watched(self) -> None:
        plex_episode = SimpleNamespace(viewCount=1)

        self.assertTrue(self.interface._is_episode_watched(plex_episode))

    def test_near_end_offset_marks_watched(self) -> None:
        plex_episode = SimpleNamespace(viewCount=0, duration=20000, viewOffset=19000)

        self.assertTrue(self.interface._is_episode_watched(plex_episode))

    def test_history_marks_watched(self) -> None:
        plex_episode = SimpleNamespace(viewCount=0, duration=20000, viewOffset=1000)
        plex_episode.history = lambda: ["play"]

        self.assertTrue(self.interface._is_episode_watched(plex_episode))

    def test_otherwise_unwatched(self) -> None:
        plex_episode = SimpleNamespace(viewCount=0, duration=20000, viewOffset=1000)
        plex_episode.history = lambda: []

        self.assertFalse(self.interface._is_episode_watched(plex_episode))


class UpdateWatchedStatusesTests(TestCase):
    def setUp(self) -> None:
        self.interface = PlexInterface.__new__(PlexInterface)
        self.interface.loaded_db = MagicMock()
        self.interface.loaded_db.search.return_value = []

        # Keep helper logic out of the way for this test
        self.interface._is_episode_watched = Mock(side_effect=[True, False])

        self.interface._get_condition = Mock()
        self.interface._get_loaded_episode = Mock(return_value=None)

        self.style_set = MagicMock()

        self.series_info = SimpleNamespace(full_name="Example")

        episodes = [SimpleNamespace(parentIndex=1, index=1), SimpleNamespace(parentIndex=1, index=2)]
        self.series = SimpleNamespace(episodes=lambda: episodes)

        self.interface._PlexInterface__get_library = Mock(return_value="Library")
        self.interface._PlexInterface__get_series = Mock(return_value=self.series)

        self.episode_map = {
            "1-1": make_stub_episode(1, 1),
            "1-2": make_stub_episode(1, 2),
        }

    def test_helper_used_for_each_episode(self) -> None:
        self.interface.update_watched_statuses(
            "Library", self.series_info, self.episode_map, self.style_set
        )

        self.assertEqual(self.interface._is_episode_watched.call_count, 2)
        self.episode_map["1-1"].update_statuses.assert_called_once_with(
            True, self.style_set
        )
        self.episode_map["1-2"].update_statuses.assert_called_once_with(
            False, self.style_set
        )

    def test_watched_to_unwatched_triggers_reload(self) -> None:
        episode = make_stub_episode(1, 1)
        episodes = [SimpleNamespace(parentIndex=1, index=1)]
        series = SimpleNamespace(episodes=lambda: episodes)
        self.interface._PlexInterface__get_series.return_value = series

        self.interface._is_episode_watched = Mock(return_value=False)
        self.interface._get_loaded_episode = Mock(
            return_value={'spoiler': None, 'watched': True}
        )
        self.interface._get_condition = Mock(return_value="condition")

        self.interface.update_watched_statuses(
            "Library", self.series_info, {"1-1": episode}, self.style_set
        )

        episode.delete_card.assert_called_once()
        self.interface.loaded_db.update.assert_called_once_with(
            {'filesize': 0}, "condition"
        )

    def test_unwatched_to_watched_triggers_reload(self) -> None:
        episode = make_stub_episode(1, 1)
        episodes = [SimpleNamespace(parentIndex=1, index=1)]
        series = SimpleNamespace(episodes=lambda: episodes)
        self.interface._PlexInterface__get_series.return_value = series

        self.interface._is_episode_watched = Mock(return_value=True)
        self.interface._get_loaded_episode = Mock(
            return_value={'spoiler': None, 'watched': False}
        )
        self.interface._get_condition = Mock(return_value="condition")

        self.interface.update_watched_statuses(
            "Library", self.series_info, {"1-1": episode}, self.style_set
        )

        episode.delete_card.assert_called_once()
        self.interface.loaded_db.update.assert_called_once_with(
            {'filesize': 0}, "condition"
        )
