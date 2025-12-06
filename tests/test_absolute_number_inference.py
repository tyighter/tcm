from modules.EpisodeInfo import EpisodeInfo
from modules.Show import Show


def test_infers_missing_absolute_numbers_between_known_values():
    episodes = [
        EpisodeInfo('One', 1, 1, abs_number=1),
        EpisodeInfo('Two', 1, 2),
        EpisodeInfo('Three', 1, 3, abs_number=3),
    ]

    Show._infer_absolute_numbers_for_infos(episodes)

    assert [episode.abs_number for episode in episodes] == [1, 2, 3]


def test_infers_leading_and_trailing_absolute_numbers():
    episodes = [
        EpisodeInfo('One', 1, 1),
        EpisodeInfo('Two', 1, 2, abs_number=5),
        EpisodeInfo('Three', 1, 3),
    ]

    Show._infer_absolute_numbers_for_infos(episodes)

    assert [episode.abs_number for episode in episodes] == [4, 5, 6]


def test_does_not_infer_when_no_absolute_numbers_available():
    episodes = [
        EpisodeInfo('One', 1, 1),
        EpisodeInfo('Two', 1, 2),
    ]

    Show._infer_absolute_numbers_for_infos(episodes)

    assert episodes[0].abs_number is None
    assert episodes[1].abs_number is None
