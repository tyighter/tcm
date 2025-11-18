import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from webui.card_type_images import (
    DEFAULT_THUMBNAIL_SLUG_MAP,
    load_card_type_thumbnails,
    prepare_thumbnail_from_config,
)
from webui.server import WebRequestHandler


class PrepareThumbnailFromConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        base_path = Path(self.tempdir.name)

        self.thumbnail_root = base_path / "thumbnails"
        self.static_root = base_path / "static"
        self.card_type_static_root = self.static_root / "card-types"

        self.thumbnail_root.mkdir(parents=True)

        self.patches = [
            patch("webui.card_type_images.DOCKER_THUMBNAIL_ROOT", self.thumbnail_root),
            patch("webui.card_type_images.REPO_THUMBNAIL_ROOT", self.thumbnail_root),
            patch("webui.card_type_images.CARD_TYPE_STATIC_ROOT", self.card_type_static_root),
            patch("webui.server.CONFIG_THUMBNAIL_ROOT", self.thumbnail_root),
            patch("webui.server.REPO_THUMBNAIL_ROOT", self.thumbnail_root),
            patch("webui.server.STATIC_ROOT", self.static_root),
        ]

        for mocker in self.patches:
            mocker.start()

    def tearDown(self) -> None:
        for mocker in reversed(self.patches):
            mocker.stop()
        self.tempdir.cleanup()

    def _write_image(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (200, 200), color=(0, 128, 255)).save(path)

    def test_slug_matched_thumbnail_served_via_api(self) -> None:
        slug = "marvel"
        default_filename = DEFAULT_THUMBNAIL_SLUG_MAP[slug]
        slug_matched_source = self.thumbnail_root / "marvel.png"

        # Create only the slug-matched file with a non-default name/extension.
        self._write_image(slug_matched_source)
        self.assertNotEqual(slug_matched_source.name, default_filename)

        prepared = prepare_thumbnail_from_config(slug)

        self.assertIsNotNone(prepared)
        assert prepared is not None  # Helps type checkers
        self.assertTrue(prepared.exists())
        self.assertEqual(prepared.suffix.lower(), slug_matched_source.suffix.lower())

        handler = WebRequestHandler.__new__(WebRequestHandler)
        resolved = WebRequestHandler._resolve_card_type_thumbnail(handler, slug)
        self.assertEqual(resolved, prepared)

    def test_load_card_type_thumbnails_finds_slug_matched_jpeg(self) -> None:
        slug = "marvel"
        slug_matched_source = self.thumbnail_root / "marvel.jpeg"

        self._write_image(slug_matched_source)

        with patch.dict(
            "modules.TitleCard.TitleCard.BUILTIN_CARD_TYPES", {slug: object()}, clear=True
        ), patch.dict("modules.TitleCard.TitleCard.CARD_TYPE_ALIASES", {}, clear=True):
            thumbnails = load_card_type_thumbnails()

        prepared = self.card_type_static_root / f"{slug}{slug_matched_source.suffix.lower()}"

        self.assertIn(slug, thumbnails)
        self.assertEqual(thumbnails[slug], f"/api/card-types/thumbnail?slug={slug}")
        self.assertTrue(prepared.exists())


if __name__ == "__main__":
    unittest.main()
