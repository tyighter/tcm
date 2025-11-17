from __future__ import annotations

import argparse
import json
import logging
import re
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse

import requests
from PIL import Image, ImageOps

logger = logging.getLogger(__name__)

CARD_TYPE_MARKDOWN_URL = (
    "https://raw.githubusercontent.com/wiki/CollinHeist/TitleCardMaker/Custom-Card-Types.md"
)
CARD_TYPE_STATIC_ROOT = Path(__file__).resolve().parent / "static" / "card-types"
REPO_THUMBNAIL_ROOT = Path(__file__).resolve().parent.parent / "config" / "thumbnails"
DOCKER_THUMBNAIL_ROOT = Path("/config/thumbnails")
MANIFEST_FILENAME = "manifest.json"
THUMBNAIL_SIZE = (150, 84)

# Mapping of card type names to their expected thumbnail filenames in /config/thumbnails.
DEFAULT_THUMBNAIL_MAP = {
    "Anime": "anime.jpg",
    "Banner": "banner.jpg",
    "Calligraphy": "calligraphy.jpg",
    "Comic Book": "comicbook.jpg",
    "Cutout": "cutout.jpg",
    "Divider": "divider.jpg",
    "Fade": "fade.jpg",
    "Formula 1": "formula1.jpg",
    "Frame": "frame.jpg",
    "Graph": "graph.jpg",
    "Inset": "inset.jpg",
    "Landscape": "landscape.jpg",
    "Logo": "logo.jpg",
    "Marvel": "marvel.jpg",
    "Music": "music.jpg",
    "Notification": "notification.jpg",
    "Olivier": "olivier.jpg",
    "Overline": "overline.jpg",
    "Poster": "poster.jpg",
    "Roman Numeral": "roman.jpg",
    "Shape": "shape.jpg",
    "Standard": "standard.jpg",
    "Star Wars": "starwars.jpg",
    "Striped": "striped.jpg",
    "Textless": "textless.jpg",
    "Tinted Frame": "tintedframe.jpg",
    "Tinted Glass": "tintedglass.jpg",
    "White Border": "whiteborder.jpg",
}


_slug_regex = re.compile(r"[^a-z0-9]+")
_image_regex = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")


def slugify_card_type(name: str) -> str:
    """Normalize a card type name for consistent matching."""

    slug = _slug_regex.sub("-", name.strip().lower()).strip("-")
    slug = re.sub(r"([a-z])([0-9])", r"\1-\2", slug)
    slug = re.sub(r"([0-9])([a-z])", r"\1-\2", slug)
    return re.sub(r"-+", "-", slug).strip("-")


def _thumbnail_api_url(slug: str) -> str:
    return f"/api/card-types/thumbnail?slug={slug}"


# Precomputed mapping of normalized slugs to their expected filenames. Using a
# deterministic mapping avoids guessing at alternative extensions or file
# naming conventions.
DEFAULT_THUMBNAIL_SLUG_MAP = {
    slugify_card_type(name): filename for name, filename in DEFAULT_THUMBNAIL_MAP.items()
}


def _iter_image_urls(markdown: str) -> Iterable[str]:
    for match in _image_regex.finditer(markdown):
        url = match.group(1)
        if url.startswith("http") and "/card-types" in url:
            yield url


def _download(url: str, destination: Path) -> None:
    response = requests.get(url, timeout=20)
    response.raise_for_status()
    destination.write_bytes(response.content)


def cache_card_type_images(
    markdown_url: str = CARD_TYPE_MARKDOWN_URL,
    destination: Path = DOCKER_THUMBNAIL_ROOT,
) -> dict[str, str]:
    """Download example images for built-in card types and return a manifest."""

    destination.mkdir(parents=True, exist_ok=True)

    response = requests.get(markdown_url, timeout=20)
    response.raise_for_status()

    manifest: dict[str, str] = {}
    for url in _iter_image_urls(response.text):
        filename = Path(urlparse(url).path).name
        if not filename:
            continue

        target = destination / filename
        _download(url, target)

        slug = slugify_card_type(Path(filename).stem)
        manifest[slug] = _thumbnail_api_url(slug)

    (destination / MANIFEST_FILENAME).write_text(
        json.dumps(manifest, indent=2, sort_keys=True)
    )

    return manifest


def load_card_type_thumbnails(
    manifest_path: Path | None = None,
) -> dict[str, str]:
    """Load cached card type thumbnails from the manifest file."""

    from modules.TitleCard import TitleCard

    known_slugs = {
        slugify_card_type(name) for name in TitleCard.BUILTIN_CARD_TYPES.keys()
    }

    logger.debug("Loading card type thumbnails; manifest_path=%s", manifest_path)

    thumbnails: dict[str, str] = {}
    local_thumbnails = _load_local_thumbnails(known_slugs)
    for slug, source in local_thumbnails.items():
        prepared = _prepare_resized_thumbnail(slug, source)
        if prepared:
            thumbnails[slug] = _thumbnail_api_url(slug)

    manifest_path = manifest_path or DOCKER_THUMBNAIL_ROOT / MANIFEST_FILENAME
    try:
        raw = manifest_path.read_text()
    except FileNotFoundError:
        logger.info("Thumbnail manifest not found at %s", manifest_path)
        manifest = {}
    else:
        try:
            manifest = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning(
                "Thumbnail manifest file is not valid JSON: %s", manifest_path
            )
            manifest = {}

    for key, value in manifest.items():
        if not isinstance(value, str):
            continue

        slug = slugify_card_type(key)
        normalized = _normalize_thumbnail_url(slug, value)
        thumbnails.setdefault(slug, normalized)
    logger.debug(
        "Loaded %d thumbnails (%d from manifest, %d from local files)",
        len(thumbnails),
        len(manifest),
        len(thumbnails) - len(manifest),
    )

    # If a thumbnail exists for an alias but not its canonical card type,
    # reuse the alias image so every selectable card type shows a thumbnail.
    for alias, target in TitleCard.CARD_TYPE_ALIASES.items():
        alias_slug = slugify_card_type(alias)
        target_slug = slugify_card_type(target)
        if alias_slug in thumbnails and target_slug not in thumbnails:
            thumbnails[target_slug] = thumbnails[alias_slug]
            logger.debug(
                "Mapped alias thumbnail %s -> %s", alias_slug, target_slug
            )

    return thumbnails


def _normalize_thumbnail_url(slug: str, url: str) -> str:
    if url.startswith("/static/card-types/"):
        return _thumbnail_api_url(slug)
    return url


def prepare_thumbnail_from_config(slug: str) -> Path | None:
    """Ensure a resized thumbnail exists for the requested slug.

    The function looks for a JPG in `/config/thumbnails` (or the repository
    fallback) using the default mapping, resizes it to the UI slot, and stores
    the prepared image under the static card-type directory.
    """

    filename = DEFAULT_THUMBNAIL_SLUG_MAP.get(slug)
    logger.debug("Preparing thumbnail for slug=%s; filename=%s", slug, filename)
    if not filename:
        logger.debug("No thumbnail filename mapping for slug %s", slug)
        return None

    source_paths = []
    for root in (DOCKER_THUMBNAIL_ROOT, REPO_THUMBNAIL_ROOT):
        path = root / filename
        try:
            if path.exists():
                source_paths.append(path)
        except OSError as exc:
            logger.debug("Unable to inspect thumbnail candidate %s: %s", path, exc)
            continue

    if not source_paths:
        logger.debug(
            "No source thumbnails found for slug %s in %s", slug, DOCKER_THUMBNAIL_ROOT
        )
        return None

    source = source_paths[0]
    logger.debug("Selected source thumbnail %s for slug %s", source, slug)
    prepared = _prepare_resized_thumbnail(slug, source)
    if prepared:
        logger.debug(
            "Prepared resized thumbnail for slug %s at %s (source=%s)",
            slug,
            prepared,
            source,
        )
    else:
        logger.debug("Failed to prepare resized thumbnail for slug %s", slug)

    return prepared


def _load_local_thumbnails(known_slugs: set[str]) -> dict[str, Path]:
    """Return thumbnail files present on disk keyed by slug."""

    thumbnails: dict[str, Path] = {}

    for slug, filename in DEFAULT_THUMBNAIL_SLUG_MAP.items():
        if slug not in known_slugs:
            continue

        for root in (DOCKER_THUMBNAIL_ROOT, REPO_THUMBNAIL_ROOT):
            path = root / filename
            try:
                if not path.exists():
                    continue
            except OSError:
                continue

            thumbnails[slug] = path
            logger.debug("Found thumbnail for %s at %s", slug, path)
            break

    return thumbnails


def _copy_and_resize_thumbnail(source: Path, destination: Path) -> bool:
    """Copy a thumbnail image and resize it to fit the UI slot."""

    try:
        with Image.open(source) as img:
            img = img.convert("RGB")
            resized = ImageOps.fit(
                img,
                THUMBNAIL_SIZE,
                method=Image.Resampling.LANCZOS,
                bleed=0.0,
                centering=(0.5, 0.5),
            )

            format_hint = {
                ".jpg": "JPEG",
                ".jpeg": "JPEG",
                ".png": "PNG",
                ".webp": "WEBP",
            }.get(destination.suffix.lower(), "JPEG")

            resized.save(destination, format=format_hint)
    
        return True
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning(
            "Failed to prepare thumbnail %s -> %s: %s", source, destination, exc
        )
        try:
            destination.write_bytes(source.read_bytes())
        except OSError:
            return False

        return True


def _prepare_resized_thumbnail(slug: str, source: Path) -> Path | None:
    """Create (or reuse) a resized thumbnail suitable for the UI."""

    suffix = source.suffix.lower() or ".jpg"
    destination = CARD_TYPE_STATIC_ROOT / f"{slug}{suffix}"

    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        logger.warning(
            "Unable to ensure thumbnail directory %s: %s", destination.parent, exc
        )
        return None

    try:
        if destination.exists() and destination.stat().st_mtime >= source.stat().st_mtime:
            logger.debug("Using cached resized thumbnail for %s at %s", slug, destination)
            return destination
    except OSError:
        # Fall through to attempt regenerating the thumbnail
        pass

    if _copy_and_resize_thumbnail(source, destination):
        logger.debug("Prepared resized thumbnail %s -> %s", source, destination)
        return destination

    return None


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Cache example images for built-in card types."
    )
    parser.add_argument(
        "--dest",
        type=Path,
        default=CARD_TYPE_STATIC_ROOT,
        help="Destination directory for cached images.",
    )
    parser.add_argument(
        "--markdown-url",
        default=CARD_TYPE_MARKDOWN_URL,
        help="Custom URL for the card type markdown source.",
    )

    args = parser.parse_args()
    manifest = cache_card_type_images(args.markdown_url, args.dest)
    print(
        f"Cached {len(manifest)} card type example images to {args.dest.resolve()}"
    )


if __name__ == "__main__":
    main()
