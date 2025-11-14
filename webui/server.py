from __future__ import annotations

import json
import mimetypes
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .config import AppContext, create_app_context
from .options import build_series_fields
from .services import generate_preview, search_plex
from .tv_data import TvYamlManager

STATIC_ROOT = Path(__file__).resolve().parent / "static"
TEMPLATE_ROOT = Path(__file__).resolve().parent / "templates"
DEFAULT_FONT_DIRECTORY = Path("/config/fonts")


class WebRequestHandler(BaseHTTPRequestHandler):
    context: AppContext
    tv_manager: TvYamlManager

    # Silence default logging
    def log_message(self, format: str, *args) -> None:  # type: ignore[override]
        return

    # Utility helpers -------------------------------------------------
    def _json_response(self, payload: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _error(self, message: str, status: HTTPStatus = HTTPStatus.BAD_REQUEST) -> None:
        self._json_response({"error": message}, status=status)

    def _serve_file(self, file_path: Path) -> None:
        if not file_path.exists() or not file_path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND.value)
            return

        mime, _ = mimetypes.guess_type(file_path.as_posix())
        data = file_path.read_bytes()

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", mime or "application/octet-stream")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _parse_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError("Invalid JSON payload") from exc

    # HTTP verb handlers ----------------------------------------------
    def do_GET(self) -> None:  # type: ignore[override]
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self._serve_file(TEMPLATE_ROOT / "index.html")
            return

        if parsed.path.startswith("/static/"):
            rel = parsed.path[len("/static/") :]
            target = (STATIC_ROOT / rel).resolve()
            if not str(target).startswith(str(STATIC_ROOT.resolve())):
                self.send_error(HTTPStatus.NOT_FOUND.value)
                return
            self._serve_file(target)
            return

        if parsed.path == "/api/config":
            payload = self.tv_manager.as_payload()
            self._json_response(payload)
            return

        if parsed.path == "/api/meta":
            tv_payload = self.tv_manager.as_payload()
            libraries = tv_payload.get("libraries", {})
            fields = build_series_fields(libraries)
            card_types = next(
                (field.get("choices", []) for field in fields if field.get("id") == "card_type"),
                [],
            )
            self._json_response(
                {
                    "fields": fields,
                    "cardTypes": card_types,
                    "fontDirectory": DEFAULT_FONT_DIRECTORY.as_posix(),
                }
            )
            return

        if parsed.path == "/api/fonts":
            params = parse_qs(parsed.query)
            requested = Path(params.get("path", [DEFAULT_FONT_DIRECTORY.as_posix()])[0])
            entries = []
            if requested.exists():
                for item in sorted(requested.iterdir(), key=lambda p: (p.is_file(), p.name.lower())):
                    entries.append(
                        {
                            "name": item.name,
                            "path": item.as_posix(),
                            "type": "file" if item.is_file() else "directory",
                        }
                    )
            self._json_response({"path": requested.as_posix(), "entries": entries})
            return

        if parsed.path == "/api/plex/search":
            params = parse_qs(parsed.query)
            query = params.get("q") or params.get("query")
            if not query or not query[0].strip():
                self._error("Missing search query")
                return
            try:
                results = search_plex(self.context, query[0], limit=15)
            except Exception as exc:  # pylint: disable=broad-except
                self._error(str(exc), status=HTTPStatus.INTERNAL_SERVER_ERROR)
                return
            self._json_response({"results": results})
            return

        self.send_error(HTTPStatus.NOT_FOUND.value)

    def do_POST(self) -> None:  # type: ignore[override]
        parsed = urlparse(self.path)

        if parsed.path == "/api/config":
            try:
                payload = self._parse_json()
            except ValueError as exc:
                self._error(str(exc))
                return

            try:
                self.tv_manager.write(payload)
            except Exception as exc:  # pylint: disable=broad-except
                self._error(str(exc), status=HTTPStatus.INTERNAL_SERVER_ERROR)
                return

            self._json_response({"status": "ok"})
            return

        if parsed.path == "/api/preview":
            try:
                payload = self._parse_json()
            except ValueError as exc:
                self._error(str(exc))
                return

            show_name = payload.get("name")
            config = payload.get("config")
            if not show_name or not isinstance(config, dict):
                self._error("Preview requires a series name and configuration")
                return

            try:
                mime, data = generate_preview(
                    self.context,
                    self.tv_manager,
                    show_name,
                    config,
                )
            except Exception as exc:  # pylint: disable=broad-except
                self._error(str(exc), status=HTTPStatus.INTERNAL_SERVER_ERROR)
                return

            self._json_response({"mime": mime, "data": data})
            return

        self.send_error(HTTPStatus.NOT_FOUND.value)


def run(port: int = 4343) -> None:
    context = create_app_context()
    tv_manager = TvYamlManager(context.default_tv_file)

    WebRequestHandler.context = context
    WebRequestHandler.tv_manager = tv_manager

    with ThreadingHTTPServer(("0.0.0.0", port), WebRequestHandler) as server:
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    run()
