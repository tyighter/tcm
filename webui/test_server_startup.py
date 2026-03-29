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
from webui.config import ensure_preference_file, preference_setup_required


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
    handler.context = SimpleNamespace(
        preference_parser=SimpleNamespace(use_tmdb=True, use_plex=True),
        preference_file=Path("/tmp/preferences.yml"),
        preference_file_generated=False,
    )
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


def test_api_services_status_reports_connected(monkeypatch) -> None:
    handler = _build_handler("/api/services/status", SimpleNamespace())
    handler.context.get_plex_interface = lambda: SimpleNamespace(get_libraries=lambda: ["TV"])

    monkeypatch.setattr(server.TautulliSettings, "from_settings", lambda: object())
    monkeypatch.setattr(server, "fetch_users", lambda _settings: [{"id": "1", "name": "User"}])

    handler.do_GET()

    payload = json.loads(handler.wfile.getvalue())
    assert handler.status == HTTPStatus.OK
    assert payload["plex"]["connected"] is True
    assert payload["tautulli"]["connected"] is True


def test_api_config_includes_fingerprint() -> None:
    class _TvManager:
        def as_payload(self) -> dict:
            return {
                "libraries": {"TV": "/library/tv"},
                "series": [{"name": "Demo Show (2024)", "config": {"library": "TV"}}],
            }

    handler = _build_handler("/api/config", _TvManager())

    handler.do_GET()

    assert handler.status == HTTPStatus.OK
    payload = json.loads(handler.wfile.getvalue())
    assert isinstance(payload.get("fingerprint"), str)
    assert len(payload["fingerprint"]) == 64


def test_api_config_fingerprint_endpoint_matches_config_response() -> None:
    class _TvManager:
        def as_payload(self) -> dict:
            return {
                "libraries": {"TV": "/library/tv"},
                "series": [{"name": "Demo Show (2024)", "config": {"library": "TV"}}],
            }

    config_handler = _build_handler("/api/config", _TvManager())
    config_handler.do_GET()
    config_payload = json.loads(config_handler.wfile.getvalue())

    fingerprint_handler = _build_handler("/api/config/fingerprint", _TvManager())
    fingerprint_handler.do_GET()
    fingerprint_payload = json.loads(fingerprint_handler.wfile.getvalue())

    assert fingerprint_handler.status == HTTPStatus.OK
    assert fingerprint_payload["fingerprint"] == config_payload["fingerprint"]


def test_api_services_status_reports_disconnected(monkeypatch) -> None:
    handler = _build_handler("/api/services/status", SimpleNamespace())
    handler.context.preference_parser.use_plex = True
    handler.context.get_plex_interface = lambda: (_ for _ in ()).throw(RuntimeError("Plex down"))

    monkeypatch.setattr(server.TautulliSettings, "from_settings", lambda: object())

    def _raise_tautulli(_settings):
        raise RuntimeError("Tautulli down")

    monkeypatch.setattr(server, "fetch_users", _raise_tautulli)

    handler.do_GET()

    payload = json.loads(handler.wfile.getvalue())
    assert handler.status == HTTPStatus.OK
    assert payload["plex"]["connected"] is False
    assert "Plex down" in payload["plex"]["message"]
    assert payload["tautulli"]["connected"] is False
    assert "Tautulli down" in payload["tautulli"]["message"]


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


def test_api_settings_returns_non_2xx_when_settings_persistence_fails(monkeypatch) -> None:
    handler = _build_post_handler("/api/settings", SimpleNamespace(), {"preferences": {}})

    def _raise_persistence(*_args, **_kwargs):
        raise server.SettingsPersistenceError(
            "Unable to write UI settings file",
            remediation="Ensure /config is writable and has free space, then retry.",
        )

    monkeypatch.setattr(server, "save_settings", _raise_persistence)

    handler.do_POST()

    assert handler.status == HTTPStatus.INTERNAL_SERVER_ERROR
    payload = json.loads(handler.wfile.getvalue())
    assert payload["persisted"] is False
    assert "Unable to write UI settings file" in payload["error"]
    assert "Ensure /config is writable" in payload["remediation"]


def test_api_config_rejects_hard_validation_errors() -> None:
    class _RecordingTvManager:
        def __init__(self) -> None:
            self.write_calls = 0

        @contextmanager
        def priority_write(self):
            yield

        def backup_on_save(self) -> None:
            return

        def write(self, payload: dict) -> None:
            self.write_calls += 1

    payload = {
        "series": [
            {
                "name": "Example (99)",
                "config": {
                    "tmdb_id": "abc",
                    "imdb_id": "bad",
                    "media_directory": "bad\u0000path",
                },
            }
        ]
    }
    tv_manager = _RecordingTvManager()
    handler = _build_post_handler("/api/config", tv_manager, payload)

    handler.do_POST()

    assert handler.status == HTTPStatus.BAD_REQUEST
    body = json.loads(handler.wfile.getvalue())
    assert body["status"] == "error"
    assert body["details"]["has_errors"] is True
    assert body["details"]["validation_errors"]
    assert tv_manager.write_calls == 0


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


def test_api_preview_static_falls_back_to_generated_preview(monkeypatch) -> None:
    handler = _build_handler("/api/preview/static?name=Demo%20Show", SimpleNamespace())

    monkeypatch.setattr(
        handler,
        "_find_series_entry",
        lambda **_kwargs: ("Demo Show", {"library": "TV"}),
    )
    monkeypatch.setattr(handler, "_resolve_preview_path", lambda **_kwargs: None)

    generated: dict[str, object] = {}

    def _mock_get_or_generate(context, tv_manager, name, config, *, force, preview_episode_key, prefer_existing):
        generated.update(
            {
                "name": name,
                "config": config,
                "force": force,
                "preview_episode_key": preview_episode_key,
                "prefer_existing": prefer_existing,
            }
        )
        return "image/png", base64.b64encode(b"demo-static").decode("ascii")

    monkeypatch.setattr(server, "get_or_generate_preview", _mock_get_or_generate)

    handler.do_GET()

    assert handler.status == HTTPStatus.OK
    assert ("Content-Type", "image/png") in handler._headers
    assert handler.wfile.getvalue() == b"demo-static"
    assert generated["name"] == "Demo Show"
    assert generated["config"] == {"library": "TV"}
    assert generated["force"] is False
    assert generated["preview_episode_key"] is None
    assert generated["prefer_existing"] is True


def test_api_convert_legacy_tv_yaml_returns_backup_and_config() -> None:
    class _RecordingTvManager:
        def backup_and_convert_legacy_keys(self):
            return Path("/config/tv-backup.yml"), 2

        def as_payload(self) -> dict:
            return {"libraries": {}, "series": [{"name": "Demo Show (2024)", "config": {}}]}

    handler = _build_post_handler("/api/tv/convert-legacy", _RecordingTvManager(), {})

    handler.do_POST()

    assert handler.status == HTTPStatus.OK
    payload = json.loads(handler.wfile.getvalue())
    assert payload["status"] == "ok"
    assert payload["backupPath"] == "/config/tv-backup.yml"
    assert payload["updatedSeries"] == 2
    assert "config" in payload


def test_api_meta_includes_canonical_extras_and_field_descriptions() -> None:
    class _TvManager:
        def as_payload(self) -> dict:
            return {
                "libraries": {"TV Shows": "/library/tv"},
                "series": [{"name": "Demo Show (2024)", "config": {}}],
            }

    handler = _build_handler("/api/meta", _TvManager())

    handler.do_GET()

    assert handler.status == HTTPStatus.OK
    payload = json.loads(handler.wfile.getvalue())

    fields = payload["fields"]
    assert fields
    assert all(field.get("description") for field in fields)

    card_type_field = next(field for field in fields if field["id"] == "card_type")
    assert "card design template" in card_type_field["description"].lower()

    extras = payload["cardTypeExtras"]
    assert extras
    flattened = [entry for definitions in extras.values() for entry in definitions]
    episode_case = next(entry for entry in flattened if entry["key"] == "episode_text_case")
    assert episode_case["canonicalKey"] == "episode_number_text_case"
    assert episode_case["description"]


def test_ensure_preference_file_generates_defaults(tmp_path) -> None:
    preference_file = tmp_path / "preferences.yml"

    generated = ensure_preference_file(preference_file)

    assert generated is True
    assert preference_file.exists()
    assert preference_setup_required(preference_file) is True


def test_preference_setup_required_false_when_values_and_setup_complete(tmp_path) -> None:
    preference_file = tmp_path / "preferences.yml"
    preference_file.write_text(
        """
options:
  source: /config/source/
  series: /config/tv.yml
webui:
  setup_complete: true
""".strip()
    )

    assert preference_setup_required(preference_file) is False
