from __future__ import annotations

import random
import re
from pathlib import Path
from typing import Any


def existing_card_path(show: Any, episode: Any | None) -> Path | None:
    """Locate an existing card on disk for an episode."""

    if episode is None:
        return None

    destination = getattr(episode, "destination", None)
    if destination is not None and destination.exists():
        return destination

    media_directory = getattr(show, "media_directory", None)
    if not media_directory:
        return None

    info = getattr(episode, "episode_info", None)
    if info is None:
        return None
    season_number = getattr(info, "season_number", None)
    episode_number = getattr(info, "episode_number", None)
    if season_number is None or episode_number is None:
        return None

    search_roots: list[Path] = []
    season_dir = Path(media_directory) / f"Season {season_number}"
    search_roots.append(season_dir)
    search_roots.append(Path(media_directory))

    candidates: list[Path] = []
    for root in search_roots:
        try:
            if not root.exists() or not root.is_dir():
                continue
        except OSError:
            continue

        for pattern in ("*.jpg", "*.jpeg", "*.png", "*.webp"):
            candidates.extend(sorted(root.rglob(pattern)))

    if not candidates:
        return None

    episode_pattern = re.compile(
        rf"(?i)(s0*{season_number}e0*{episode_number}|{season_number}x0*{episode_number})"
    )
    matching = [candidate for candidate in candidates if episode_pattern.search(candidate.name)]

    return (matching or candidates)[0]


def select_existing_card(show: Any, preferred_episode_key: str | None) -> Path | None:
    """Select an existing card, prioritizing the preferred episode when possible."""

    episodes = getattr(show, "episodes", {}) or {}
    preferred_episode = episodes.get(preferred_episode_key) if preferred_episode_key else None
    preferred_card = existing_card_path(show, preferred_episode)

    available_cards = [
        (episode, existing_card_path(show, episode))
        for episode in episodes.values()
    ]
    available_cards = [item for item in available_cards if item[1] is not None]

    if preferred_card is not None:
        return preferred_card
    if available_cards:
        _, selected_card = random.choice(available_cards)
        return selected_card
    return None
