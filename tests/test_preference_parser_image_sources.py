from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

import yaml

from modules.PreferenceParser import PreferenceParser


class PreferenceParserImageSourceTests(TestCase):

    def test_tvdb_is_valid_image_source(self) -> None:
        with TemporaryDirectory() as tmpdir:
            preference_file = Path(tmpdir) / 'preferences.yml'
            preference_file.write_text(
                yaml.safe_dump({
                    'options': {
                        'source': str(Path(tmpdir) / 'source'),
                        'image_source_priority': 'tvdb, tmdb',
                    },
                    'tvdb': {
                        'api_key': 'tvdb-key',
                    },
                    'tmdb': {
                        'api_key': 'tmdb-key',
                    },
                })
            )

            with patch.object(
                PreferenceParser,
                '_PreferenceParser__determine_imagemagick_prefix',
                return_value=None,
            ):
                parser = PreferenceParser(preference_file)

        self.assertTrue(parser.valid)
        self.assertEqual(parser.image_source_priority, ('tvdb', 'tmdb'))
