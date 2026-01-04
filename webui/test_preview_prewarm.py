import os
import time
from types import SimpleNamespace

import pytest

from webui import server, services


def _cache_preview_payload(key: str, payload: services.PreviewPayload) -> None:
    with services._preview_cache_lock:
        services._preview_cache[key] = payload


def test_preview_cache_is_fresh(tmp_path) -> None:
    card = tmp_path / "card.jpg"
    card.write_bytes(b"demo")
    cache_key = services.preview_cache_key("Show", {"library": "TV"})

    recent_payload = services.PreviewPayload(
        mime="image/jpeg",
        data="data",
        source_path=card,
        cached_at=time.time(),
        source_mtime=card.stat().st_mtime,
    )
    _cache_preview_payload(cache_key, recent_payload)

    assert services.preview_cache_is_fresh("Show", {"library": "TV"}, max_age_ms=1000)

    stale_payload = services.PreviewPayload(
        mime="image/jpeg",
        data="data",
        source_path=card,
        cached_at=time.time() - 10,
        source_mtime=card.stat().st_mtime,
    )
    _cache_preview_payload(cache_key, stale_payload)

    assert not services.preview_cache_is_fresh("Show", {"library": "TV"}, max_age_ms=1000)
    services.invalidate_preview_cache("Show")


def test_preview_cache_is_fresh_uses_configured_episode(monkeypatch, tmp_path) -> None:
    captured: list[str] = []
    preview_episode = "episode-1"
    cache_key = services.preview_cache_key("Show", {"library": "TV"}, preview_episode_key=preview_episode)
    card = tmp_path / "card.jpg"
    card.write_bytes(b"demo")

    original_cache_key = services.preview_cache_key

    def _preview_cache_key(*args, **kwargs):
        key = original_cache_key(*args, **kwargs)
        captured.append(key)
        return key

    monkeypatch.setattr(services, "preview_cache_key", _preview_cache_key)

    _cache_preview_payload(
        cache_key,
        services.PreviewPayload(
            mime="image/jpeg",
            data="data",
            source_path=card,
            cached_at=time.time(),
            source_mtime=card.stat().st_mtime,
        ),
    )

    assert services.preview_cache_is_fresh(
        "Show",
        {"library": "TV"},
        preview_episode_key=preview_episode,
        max_age_ms=1000,
    )

    assert captured == [cache_key]
    services.invalidate_preview_cache("Show")


def test_preview_prewarmer_uses_cache(monkeypatch) -> None:
    monkeypatch.setattr(server, "_preview_log", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(server, "preview_cache_is_fresh", lambda *_args, **_kwargs: True)

    calls: list[str] = []

    def _get_or_generate_preview(_context, _tv_manager, name, _config, **_kwargs) -> None:
        calls.append(name)

    monkeypatch.setattr(server, "get_or_generate_preview", _get_or_generate_preview)

    tv_manager = SimpleNamespace(
        as_payload=lambda: {"series": [{"name": "Demo", "config": {"library": "TV"}}]}
    )
    prewarmer = server.PreviewPrewarmer(
        SimpleNamespace(),
        tv_manager,
        batch_size=1,
        batch_interval=0.0,
        enabled=True,
    )

    result = prewarmer.run_once()

    assert calls == []
    assert result["skipped"] == 1


def test_preview_prewarmer_refreshes_when_stale(monkeypatch) -> None:
    monkeypatch.setattr(server, "_preview_log", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(server, "preview_cache_is_fresh", lambda *_args, **_kwargs: False)

    calls: list[tuple[str, str | None]] = []

    def _get_or_generate_preview(_context, _tv_manager, name, _config, **kwargs) -> None:
        calls.append((name, kwargs.get("preview_episode_key")))

    monkeypatch.setattr(server, "get_or_generate_preview", _get_or_generate_preview)

    tv_manager = SimpleNamespace(
        as_payload=lambda: {
            "series": [
                {"name": "Demo", "config": {"library": "TV", "previewEpisode": "episode-1"}}
            ]
        }
    )
    prewarmer = server.PreviewPrewarmer(
        SimpleNamespace(),
        tv_manager,
        batch_size=1,
        batch_interval=0.0,
        enabled=True,
    )

    result = prewarmer.run_once()

    assert ("Demo", None) in calls
    assert ("Demo", "episode-1") in calls
    assert result["refreshed"] == 2


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
