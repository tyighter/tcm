import os
import time
import logging
import re
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


def test_preview_logs_are_written_to_per_show_files(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(services, "SHOW_LOG_DIR", tmp_path)
    services._show_loggers.clear()

    services._log_preview_event(
        "Demo Show (2024)",
        "generated-preview.jpg",
        status="success",
        origin="generated",
        episode_key="1-2",
    )
    services._log_preview_cache_decision(
        "Demo Show (2024)",
        "demo-key",
        preview_episode_key="1-2",
        decision="cache-hit",
    )

    safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", "Demo Show (2024)").strip("._-")
    log_path = tmp_path / f"{safe_name}.log"
    assert log_path.exists()
    log_output = log_path.read_text()
    assert "Preview success | origin=generated | show=Demo Show (2024)" in log_output
    assert "Preview cache decision | show=Demo Show (2024)" in log_output


def test_preview_request_logs_top_level_show_message(caplog, monkeypatch) -> None:
    cache_key = services.preview_cache_key("Demo Show", {"library": "TV"})
    _cache_preview_payload(
        cache_key,
        services.PreviewPayload(
            mime="image/jpeg",
            data="cached",
            source_path=None,
            existing_source=True,
            cached_at=time.time(),
            source_mtime=None,
        ),
    )
    monkeypatch.setattr(services, "_show_logger", lambda *_args, **_kwargs: None)
    caplog.set_level(logging.INFO, logger=services.logger.name)

    mime, data = services.get_or_generate_preview(
        context=SimpleNamespace(),
        tv_manager=SimpleNamespace(),
        show_name="Demo Show",
        series_config={"library": "TV"},
    )

    assert (mime, data) == ("image/jpeg", "cached")
    assert "Working on show Demo Show (web UI preview request)" in caplog.text
    services.invalidate_preview_cache("Demo Show")


def test_show_log_scope_forwards_non_preview_activity(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(services, "SHOW_LOG_DIR", tmp_path)
    services._show_loggers.clear()
    services.logger.setLevel(logging.INFO)

    with services._show_log_scope("Demo Show"):
        services.logger.info("Manager step complete")

    safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", "Demo Show").strip("._-")
    log_path = tmp_path / f"{safe_name}.log"
    assert log_path.exists()
    assert "Manager step complete" in log_path.read_text()


def test_show_log_scope_captures_debug_activity(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(services, "SHOW_LOG_DIR", tmp_path)
    services._show_loggers.clear()

    show_logger = services._show_logger("Demo Show")
    assert show_logger is not None
    assert show_logger.level == logging.DEBUG
    assert any(handler.level == logging.DEBUG for handler in show_logger.handlers)


def test_show_log_file_is_overwritten_on_start(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(services, "SHOW_LOG_DIR", tmp_path)
    services._show_loggers.clear()
    services.logger.setLevel(logging.INFO)

    safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", "Demo Show").strip("._-")
    log_path = tmp_path / f"{safe_name}.log"
    log_path.write_text("old log line")

    with services._show_log_scope("Demo Show"):
        services.logger.info("new log line")

    contents = log_path.read_text()
    assert "new log line" in contents
    assert "old log line" not in contents


def test_main_logs_only_keep_top_level_messages_in_show_scope(caplog, monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(services, "SHOW_LOG_DIR", tmp_path)
    services._show_loggers.clear()
    services.logger.setLevel(logging.INFO)
    caplog.set_level(logging.INFO)

    with services._show_log_scope("Demo Show"):
        services.logger.info("nested detail")
        services.logger.info("top level", extra={"show_top_level": True})

    assert "top level" in caplog.text
    assert "nested detail" not in caplog.text


def test_show_scope_suppresses_nested_messages_from_tcm_handlers(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(services, "SHOW_LOG_DIR", tmp_path)
    services._show_loggers.clear()

    tcm_logger = logging.getLogger("tcm")
    original_level = tcm_logger.level

    captured: list[str] = []

    class _CaptureHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            captured.append(record.getMessage())

    handler = _CaptureHandler()
    handler.setLevel(logging.INFO)
    tcm_logger.addHandler(handler)
    tcm_logger.setLevel(logging.INFO)

    try:
        with services._show_log_scope("Demo Show"):
            tcm_logger.info("nested tcm detail")
            tcm_logger.info("top level tcm", extra={"show_top_level": True})
    finally:
        tcm_logger.removeHandler(handler)
        tcm_logger.setLevel(original_level)

    assert "top level tcm" in captured
    assert "nested tcm detail" not in captured


class _StubPreviewEpisodeInfo:
    def __init__(self, key: str) -> None:
        self.key = key


class _StubPreviewEpisode:
    def __init__(self, key: str, source, destination) -> None:
        self.episode_info = _StubPreviewEpisodeInfo(key)
        self.source = source
        self.destination = destination
        self.extra_characteristics = {}


class _StubPreviewFont:
    attributes = {}

    @staticmethod
    def validate_title(title: str) -> tuple[str, bool]:
        return title, True


class _StubPreviewProfile:
    font = _StubPreviewFont()


class _StubPreviewCardClass:
    TITLE_CHARACTERISTICS = {}


class _StubPreviewTitleCard:
    def __init__(self, episode, *_args, **_kwargs) -> None:
        self.episode = episode
        self.converted_title = "Preview Title"

    def create(self, overwrite: bool = True) -> bool:
        _ = overwrite
        self.episode.destination.write_bytes(b"preview")
        return True


class _SelectSourceRecorder:
    def __init__(self, fallback_episode, available_source) -> None:
        self.fallback_episode = fallback_episode
        self.available_source = available_source
        self.calls: list[str] = []

    def __call__(self, select_only=None) -> None:
        if select_only is None:
            self.calls.append("all")
            self.fallback_episode.source = self.available_source
            return
        key = getattr(getattr(select_only, "episode_info", None), "key", "unknown")
        self.calls.append(key)


def test_generate_preview_falls_back_when_preferred_episode_source_is_missing(monkeypatch, tmp_path) -> None:
    missing_source = tmp_path / "missing-source.jpg"
    available_source = tmp_path / "available-source.jpg"
    available_source.write_bytes(b"src")
    destination = tmp_path / "preview.jpg"

    preferred = _StubPreviewEpisode("1-1", missing_source, destination)
    fallback = _StubPreviewEpisode("1-2", available_source, destination)

    show = SimpleNamespace(
        episodes={preferred.episode_info.key: preferred, fallback.episode_info.key: fallback},
        extras={},
        profile=_StubPreviewProfile(),
        card_class=_StubPreviewCardClass(),
        image_magick=SimpleNamespace(),
        font=_StubPreviewFont(),
        select_source_images=lambda select_only: None,
    )

    monkeypatch.setattr(services, "TitleCard", _StubPreviewTitleCard)

    payload = services.generate_preview(
        context=SimpleNamespace(),
        tv_manager=SimpleNamespace(),
        show_name="Demo",
        series_config={},
        preferred_episode_key=preferred.episode_info.key,
        preloaded_show=show,
    )

    assert payload.mime == "image/jpeg"
    assert destination.exists()


def test_generate_preview_runs_full_sync_before_failing_or_succeeding(monkeypatch, tmp_path) -> None:
    missing_source = tmp_path / "missing-source.jpg"
    delayed_source = tmp_path / "delayed-source.jpg"
    delayed_source.write_bytes(b"src")
    destination = tmp_path / "preview.jpg"

    preferred = _StubPreviewEpisode("1-1", missing_source, destination)
    fallback = _StubPreviewEpisode("1-2", missing_source, destination)
    recorder = _SelectSourceRecorder(fallback, delayed_source)

    show = SimpleNamespace(
        episodes={preferred.episode_info.key: preferred, fallback.episode_info.key: fallback},
        extras={},
        profile=_StubPreviewProfile(),
        card_class=_StubPreviewCardClass(),
        image_magick=SimpleNamespace(),
        font=_StubPreviewFont(),
        select_source_images=recorder,
    )

    monkeypatch.setattr(services, "TitleCard", _StubPreviewTitleCard)

    payload = services.generate_preview(
        context=SimpleNamespace(),
        tv_manager=SimpleNamespace(),
        show_name="Demo",
        series_config={},
        preferred_episode_key=preferred.episode_info.key,
        preloaded_show=show,
    )

    assert payload.mime == "image/jpeg"
    assert "all" in recorder.calls


def test_generate_preview_raises_when_no_episode_sources_exist(tmp_path) -> None:
    missing_source = tmp_path / "missing-source.jpg"
    destination = tmp_path / "preview.jpg"
    episode = _StubPreviewEpisode("1-1", missing_source, destination)

    show = SimpleNamespace(
        episodes={episode.episode_info.key: episode},
        select_source_images=lambda select_only=None: None,
    )

    with pytest.raises(
        RuntimeError,
        match="Episode source image is missing after sync; online sources may not provide artwork",
    ):
        services.generate_preview(
            context=SimpleNamespace(),
            tv_manager=SimpleNamespace(),
            show_name="Demo",
            series_config={},
            preferred_episode_key=episode.episode_info.key,
            preloaded_show=show,
        )
