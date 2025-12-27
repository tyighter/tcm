from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock, patch

from modules.Show import Show


class SelectSourceImagesTests(TestCase):

    def test_tmdb_miss_falls_back_to_plex(self) -> None:
        show = Show.__new__(Show)
        show.card_class = SimpleNamespace(USES_UNIQUE_SOURCES=True)
        show.tmdb_skip_localized_images = False
        show.image_source_priority = ['tmdb', 'plex']
        show.library_name = 'Library'
        show.series_info = SimpleNamespace(full_name='Example Show')

        show.emby_interface = None
        show.jellyfin_interface = None

        tmdb_interface = MagicMock()
        tmdb_interface.get_source_image.return_value = None
        tmdb_interface.is_permanently_blacklisted.return_value = False
        show.tmdb_interface = tmdb_interface

        plex_interface = MagicMock()
        plex_interface.has_series.return_value = True
        plex_interface.get_source_image.return_value = 'plex-image-url'
        show.plex_interface = plex_interface

        with TemporaryDirectory() as tmpdir:
            source_path = Path(tmpdir) / '1-1.png'
            episode_info = SimpleNamespace(season_number=1, episode_number=1)
            episode = SimpleNamespace(
                episode_info=episode_info,
                downloadable_source=True,
                source=source_path,
            )
            show.episodes = {'1-1': episode}

            with (
                patch.object(Show, '_Show__apply_styles', return_value=False),
                patch(
                    'modules.Show.WebInterface.download_image',
                    return_value=True,
                ) as download_image,
            ):
                show.select_source_images()

        tmdb_interface.get_source_image.assert_called_once_with(
            show.series_info, episode_info, skip_localized_images=False
        )
        plex_interface.get_source_image.assert_called_once_with(
            show.library_name, show.series_info, episode_info
        )
        download_image.assert_called_once_with('plex-image-url', source_path)
