import os
import time
from types import SimpleNamespace

import pytest

from webui import server, services


def test_preview_cache_is_fresh(monkeypatch) -> None:
    recent_payload = services.PreviewPayload(
        mime="image/jpeg",
        data="data",
        source_path=None,
        cached_at=time.time(),
    )
    monkeypatch.setattr(
        services,
        "_load_persistent_preview",
        lambda _key: recent_payload,
    )

    assert services.preview_cache_is_fresh("Show", {"library": "TV"}, max_age_ms=1000)

    stale_payload = services.PreviewPayload(
        mime="image/jpeg",
        data="data",
        source_path=None,
        cached_at=time.time() - 10,
    )
    monkeypatch.setattr(
        services,
        "_load_persistent_preview",
        lambda _key: stale_payload,
    )

    assert not services.preview_cache_is_fresh("Show", {"library": "TV"}, max_age_ms=1000)


def test_preview_cache_is_fresh_uses_configured_episode(monkeypatch) -> None:
    captured: list[str] = []

    def _load(key: str) -> services.PreviewPayload:
        captured.append(key)
        return services.PreviewPayload(
            mime="image/jpeg",
            data="data",
            source_path=None,
            cached_at=time.time(),
        )

    monkeypatch.setattr(services, "_load_persistent_preview", _load)

    preview_episode = "episode-1"
    assert services.preview_cache_is_fresh(
        "Show",
        {"library": "TV"},
        preview_episode_key=preview_episode,
        max_age_ms=1000,
    )

    expected_key = services.preview_cache_key(
        "Show", {"library": "TV"}, preview_episode_key=preview_episode
    )
    assert captured == [expected_key]


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
    monkeypatch.setattr(
        services, "_load_persistent_preview", lambda _key: holder["payload"]
    )

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

    assert not services.preview_cache_is_fresh("Show", {"library": "TV"}, max_age_ms=1000)
