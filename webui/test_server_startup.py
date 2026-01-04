import io
import json
import logging
from http import HTTPStatus
from pathlib import Path
from types import MethodType, SimpleNamespace

from webui import server


class _FailingTvManager:
    def __init__(self, exc: Exception) -> None:
        self.exc = exc
        self.load_calls = 0

    def load(self) -> None:
        self.load_calls += 1
        raise self.exc


class _FailingPayloadTvManager:
    def __init__(self, exc: Exception) -> None:
        self.exc = exc

    def as_payload(self) -> dict:
        raise self.exc


def test_startup_tasks_skip_when_tv_yaml_invalid(monkeypatch, caplog) -> None:
    context = SimpleNamespace(preference_parser=SimpleNamespace(use_tmdb=True, use_plex=True))
    tv_manager = _FailingTvManager(ValueError("bad yaml"))

    called = []

    def _unexpected_call(*_args, **_kwargs) -> None:
        called.append("called")

    monkeypatch.setattr(server, "backfill_tmdb_ids", _unexpected_call)
    monkeypatch.setattr(server, "backfill_rating_keys", _unexpected_call)
    monkeypatch.setattr(server, "backfill_episode_rating_keys", _unexpected_call)

    caplog.set_level(logging.WARNING, logger=server.logger.name)

    thread = server._run_startup_tasks_async(context, tv_manager)
    thread.join(timeout=1)

    assert not thread.is_alive()
    assert tv_manager.load_calls == 1
    assert called == []
    assert "tv.yml is invalid" in caplog.text


def _build_handler(path: str, tv_manager: object) -> server.WebRequestHandler:
    handler = server.WebRequestHandler.__new__(server.WebRequestHandler)
    handler.path = path
    handler.tv_manager = tv_manager
    handler.context = SimpleNamespace(preference_parser=SimpleNamespace(use_tmdb=True, use_plex=True))
    handler.font_directory = Path("/fonts")

    handler._headers = []  # type: ignore[attr-defined]
    handler.wfile = io.BytesIO()
    handler.send_response = MethodType(lambda self, status: setattr(self, "status", status), handler)
    handler.send_header = MethodType(
        lambda self, key, value: self._headers.append((key, value)), handler
    )
    handler.end_headers = MethodType(lambda self: None, handler)
    return handler


def test_api_config_and_meta_return_error_on_invalid_tv_yaml(caplog) -> None:
    tv_manager = _FailingPayloadTvManager(ValueError("bad yaml"))

    caplog.set_level(logging.ERROR, logger=server.logger.name)

    for path in ("/api/config", "/api/meta"):
        handler = _build_handler(path, tv_manager)

        handler.do_GET()

        body = handler.wfile.getvalue()
        assert body, f"Expected response body for {path}"

        payload = json.loads(body)
        assert payload["error"].startswith("Unable to load tv.yml")
        assert handler.status == HTTPStatus.BAD_REQUEST
        assert ("Content-Type", "application/json") in handler._headers
        assert "bad yaml" in caplog.text
