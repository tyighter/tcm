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
MANIFEST_FILENAME = "manifest.json"


_slug_regex = re.compile(r"[^a-z0-9]+")
_image_regex = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")


def slugify_card_type(name: str) -> str:
    """Normalize a card type name for consistent matching."""

    return _slug_regex.sub("-", name.strip().lower()).strip("-")


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

    manifest_path = manifest_path or CARD_TYPE_STATIC_ROOT / MANIFEST_FILENAME
    try:
        raw = manifest_path.read_text()
    except FileNotFoundError:
        return {}

    try:
        manifest = json.loads(raw)
    except json.JSONDecodeError:
        return {}

    return {
        slugify_card_type(key): value
        for key, value in manifest.items()
        if isinstance(value, str)
    }


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
