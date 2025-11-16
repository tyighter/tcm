from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse

import requests

CARD_TYPE_MARKDOWN_URL = (
    "https://raw.githubusercontent.com/wiki/CollinHeist/TitleCardMaker/Custom-Card-Types.md"
)
CARD_TYPE_STATIC_ROOT = Path(__file__).resolve().parent / "static" / "card-types"
REPO_THUMBNAIL_ROOT = Path(__file__).resolve().parent.parent / "config" / "thumbnails"
DOCKER_THUMBNAIL_ROOT = Path("/config/thumbnails")
MANIFEST_FILENAME = "manifest.json"
THUMBNAIL_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}


_slug_regex = re.compile(r"[^a-z0-9]+")
_image_regex = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")


def slugify_card_type(name: str) -> str:
    """Normalize a card type name for consistent matching."""

    slug = _slug_regex.sub("-", name.strip().lower()).strip("-")
    slug = re.sub(r"([a-z])([0-9])", r"\1-\2", slug)
    slug = re.sub(r"([0-9])([a-z])", r"\1-\2", slug)
    return re.sub(r"-+", "-", slug).strip("-")


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
    destination: Path = CARD_TYPE_STATIC_ROOT,
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
        manifest[slug] = f"/static/card-types/{filename}"

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

    thumbnails = _load_local_thumbnails(known_slugs)
    manifest_path = manifest_path or CARD_TYPE_STATIC_ROOT / MANIFEST_FILENAME
    try:
        raw = manifest_path.read_text()
    except FileNotFoundError:
        manifest = {}
    else:
        try:
            manifest = json.loads(raw)
        except json.JSONDecodeError:
            manifest = {}

    for key, value in manifest.items():
        if not isinstance(value, str):
            continue

        slug = slugify_card_type(key)
        thumbnails.setdefault(slug, value)

    # If a thumbnail exists for an alias but not its canonical card type,
    # reuse the alias image so every selectable card type shows a thumbnail.
    for alias, target in TitleCard.CARD_TYPE_ALIASES.items():
        alias_slug = slugify_card_type(alias)
        target_slug = slugify_card_type(target)
        if alias_slug in thumbnails and target_slug not in thumbnails:
            thumbnails[target_slug] = thumbnails[alias_slug]

    return thumbnails


def _iter_thumbnail_paths() -> Iterable[Path]:
    """Yield thumbnail files from known configuration directories."""

    roots = set()
    for root in (REPO_THUMBNAIL_ROOT, DOCKER_THUMBNAIL_ROOT):
        try:
            resolved = root.resolve()
        except OSError:
            continue
        if resolved in roots:
            continue
        roots.add(resolved)

        if not root.exists():
            continue

        for path in root.iterdir():
            if path.is_file() and path.suffix.lower() in THUMBNAIL_EXTENSIONS:
                yield path


def _match_thumbnail_slug(slug: str, known_slugs: set[str]) -> str | None:
    """Return the card type slug that best matches the thumbnail file name."""

    if not slug:
        return None

    if slug in known_slugs:
        return slug

    for candidate in sorted(known_slugs, key=len, reverse=True):
        if slug.startswith(f"{candidate}-") or slug.endswith(f"-{candidate}"):
            return candidate

    return None


def _load_local_thumbnails(known_slugs: set[str]) -> dict[str, str]:
    """Copy bundled thumbnails into the static folder and return their URLs."""

    thumbnails: dict[str, str] = {}

    for path in _iter_thumbnail_paths():
        source_slug = slugify_card_type(path.stem)
        target_slug = _match_thumbnail_slug(source_slug, known_slugs) or source_slug
        if not target_slug:
            continue

        CARD_TYPE_STATIC_ROOT.mkdir(parents=True, exist_ok=True)

        target_name = f"{target_slug}{path.suffix.lower()}"
        target = CARD_TYPE_STATIC_ROOT / target_name

        try:
            if not target.exists() or path.stat().st_mtime > target.stat().st_mtime:
                target.write_bytes(path.read_bytes())
        except OSError:
            continue

        thumbnails[target_slug] = f"/static/card-types/{target_name}"

    return thumbnails


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
