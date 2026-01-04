import os
import time
from types import SimpleNamespace

import pytest

from webui import server, services


def _cache_preview_payload(key: str, payload: services.PreviewPayload) -> None:
    with services._preview_cache_lock:
        services._preview_cache[key] = payload


class _StubEpisodeInfo:
    def __init__(self, season: int, episode: int) -> None:
        self.season_number = season
        self.episode_number = episode
        self.key = f"{season}-{episode}"


class _StubEpisode:
    def __init__(self, season: int, episode: int, destination):
        self.episode_info = _StubEpisodeInfo(season, episode)
        self.destination = destination


class _StubShow:
    def __init__(self, episodes):
        self.episodes = {episode.episode_info.key: episode for episode in episodes}


def _bind_preview_resolver():
    handler = SimpleNamespace(context=None, tv_manager=None)
    handler._select_episode_for_preview = server.WebRequestHandler._select_episode_for_preview.__get__(  # type: ignore[attr-defined]
        handler
    )
    handler._resolve_preview_path = server.WebRequestHandler._resolve_preview_path.__get__(  # type: ignore[attr-defined]
        handler
    )
    return handler


def test_resolve_preview_path_uses_episode_key(monkeypatch, tmp_path) -> None:
    preview_file = tmp_path / "card.png"
    preview_file.write_bytes(b"demo")

    monkeypatch.setattr(
        server,
        "_load_show_for_preview",
        lambda *_args, **_kwargs: _StubShow([_StubEpisode(1, 1, preview_file)]),
    )

    handler = _bind_preview_resolver()

    path = handler._resolve_preview_path(
        series_name="Demo",
        series_config={},
        preview_episode_key="1-1",
        season=None,
        episode=None,
    )

    assert path == preview_file


def test_resolve_preview_path_matches_season_and_episode(monkeypatch, tmp_path) -> None:
    preview_file = tmp_path / "season2-card.png"
    preview_file.write_bytes(b"demo")

    monkeypatch.setattr(
        server,
        "_load_show_for_preview",
        lambda *_args, **_kwargs: _StubShow(
            [
                _StubEpisode(1, 1, tmp_path / "missing.png"),
                _StubEpisode(2, 3, preview_file),
            ]
        ),
    )

    handler = _bind_preview_resolver()

    path = handler._resolve_preview_path(
        series_name="Demo",
        series_config={},
        preview_episode_key=None,
        season="2",
        episode="3",
    )

    assert path == preview_file


def test_preview_from_existing_sources_sets_cache_timestamp(monkeypatch, tmp_path) -> None:
    card = tmp_path / "card.jpg"
    card.write_bytes(b"demo")
    source_mtime = time.time() - 100
    os.utime(card, (source_mtime, source_mtime))

    monkeypatch.setattr(services, "_select_existing_card", lambda *_args, **_kwargs: card)
    cached_at = source_mtime + 50
    monkeypatch.setattr(services.time, "time", lambda: cached_at)

    payload = services._preview_from_existing_sources(SimpleNamespace(), None)

    assert payload is not None
    assert payload.cached_at == cached_at
    assert payload.source_mtime == pytest.approx(source_mtime)


def test_preview_cache_freshness_depends_on_source_mtime_and_age(monkeypatch, tmp_path) -> None:
    card = tmp_path / "card.jpg"
    card.write_bytes(b"demo")
    source_mtime = time.time() - 50
    os.utime(card, (source_mtime, source_mtime))

    holder = {
        "payload": services.PreviewPayload(
            mime="image/jpeg",
            data="data",
            source_path=card,
            cached_at=time.time(),
            source_mtime=source_mtime,
        )
    }
    cache_key = services.preview_cache_key("Show", {"library": "TV"})
    _cache_preview_payload(cache_key, holder["payload"])

    assert services.preview_cache_is_fresh("Show", {"library": "TV"}, max_age_ms=100_000)

    updated_mtime = source_mtime + 100
    os.utime(card, (updated_mtime, updated_mtime))

    assert not services.preview_cache_is_fresh(
        "Show", {"library": "TV"}, max_age_ms=100_000
    )

    holder["payload"] = services.PreviewPayload(
        mime="image/jpeg",
        data="data",
        source_path=card,
        cached_at=time.time() - 2,
        source_mtime=updated_mtime,
    )
    _cache_preview_payload(cache_key, holder["payload"])

    assert not services.preview_cache_is_fresh("Show", {"library": "TV"}, max_age_ms=1000)
    services.invalidate_preview_cache("Show")
