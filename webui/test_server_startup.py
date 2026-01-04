import base64
import io
import json
import logging
from contextlib import contextmanager
from copy import deepcopy
from http import HTTPStatus
from pathlib import Path
from threading import Event
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


def _build_post_handler(path: str, tv_manager: object, payload: dict) -> server.WebRequestHandler:
    handler = _build_handler(path, tv_manager)
    body = json.dumps(payload).encode("utf-8")
    handler.headers = {"Content-Length": str(len(body))}
    handler.rfile = io.BytesIO(body)
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


def test_save_config_backfills_episode_keys_async(monkeypatch) -> None:
    update_complete = Event()
    backfill_started = Event()
    allow_backfill = Event()

    class _RecordingTvManager:
        def __init__(self) -> None:
            self.payload = {
                "libraries": {},
                "series": [{"name": "Example (2024)", "config": {"rating_key": 555}}],
            }
            self.write_calls = 0
            self.backup_calls = 0
            self.updated = None

        @contextmanager
        def priority_write(self):
            yield

        def backup_on_save(self) -> None:
            self.backup_calls += 1

        def write(self, payload: dict) -> None:
            self.write_calls += 1
            self.payload = payload

        def as_payload(self) -> dict:
            return deepcopy(self.payload)

        def update_episode_rating_keys(self, series_name: str, show_rating_key, mapping) -> bool:
            self.updated = (series_name, str(show_rating_key), mapping)
            update_complete.set()
            return True

    def _ensure_episode_rating_keys(context, payload, *_args, **_kwargs):
        backfill_started.set()
        allow_backfill.wait(timeout=1)
        updated = deepcopy(payload)
        updated["series"][0]["config"]["episode_rating_keys"] = {"555": {"S1E1": "123"}}
        return updated, 1, 1

    monkeypatch.setattr(server, "ensure_episode_rating_keys_in_payload", _ensure_episode_rating_keys)

    tv_manager = _RecordingTvManager()
    handler = _build_post_handler("/api/config", tv_manager, tv_manager.payload)

    handler.do_POST()

    assert handler.status == HTTPStatus.OK
    assert tv_manager.write_calls == 1
    assert tv_manager.backup_calls == 1

    assert backfill_started.wait(timeout=1)
    assert not update_complete.is_set()

    allow_backfill.set()
    assert update_complete.wait(timeout=1)
    assert tv_manager.updated == ("Example (2024)", "555", {"S1E1": "123"})


def test_api_preview_generates_card(monkeypatch) -> None:
    generated: dict[str, object] = {}

    def _mock_generate(context, tv_manager, name, config, *, force, preview_episode_key, prefer_existing):
        generated.update(
            {
                "context": context,
                "tv_manager": tv_manager,
                "name": name,
                "config": config,
                "force": force,
                "preview_episode_key": preview_episode_key,
                "prefer_existing": prefer_existing,
            }
        )
        return "image/png", base64.b64encode(b"demo").decode("ascii")

    monkeypatch.setattr(server, "get_or_generate_preview", _mock_generate)

    payload = {
        "name": "Demo Show",
        "config": {"library": "TV"},
        "previewEpisode": "1-2",
        "season": 1,
        "episode": 2,
    }
    handler = _build_post_handler("/api/preview", SimpleNamespace(), payload)

    handler.do_POST()

    response_body = handler.wfile.getvalue()
    assert response_body, "Expected preview response body"

    response = json.loads(response_body)
    assert response["mime"] == "image/png"
    assert response["data"]
    assert handler.status == HTTPStatus.OK
    assert ("Content-Type", "application/json") in handler._headers

    assert generated["name"] == payload["name"]
    assert generated["config"] == payload["config"]
    assert generated["preview_episode_key"] == "1-2"
    assert generated["force"] is True
    assert generated["prefer_existing"] is False
