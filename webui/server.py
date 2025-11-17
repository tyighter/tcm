from __future__ import annotations

import json
import logging
import mimetypes
from cgi import FieldStorage
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qs, urlparse

from .card_type_images import (
    DEFAULT_THUMBNAIL_SLUG_MAP,
    REPO_THUMBNAIL_ROOT,
    prepare_thumbnail_from_config,
    slugify_card_type,
)
from .config import AppContext, create_app_context
from .options import build_series_fields
from .services import (
    ActionInProgressError,
    forget_series_cards,
    generate_preview,
    run_builder,
    run_builder_for_series,
    run_metadata_sync,
    revert_series_cards,
    search_plex,
)
from .tv_data import TvYamlManager

logger = logging.getLogger(__name__)

STATIC_ROOT = Path(__file__).resolve().parent / "static"
CONFIG_THUMBNAIL_ROOT = Path("/config/thumbnails")
TEMPLATE_ROOT = Path(__file__).resolve().parent / "templates"
LOG_FILE = Path("/config/webui.log")


def _configure_logging() -> None:
    """Configure logging to stdout and a fresh log file in /config."""

    log_format = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"

    handlers: list[logging.Handler] = []

    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(logging.INFO)
    stream_handler.setFormatter(logging.Formatter(log_format))
    handlers.append(stream_handler)

    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(LOG_FILE, mode="w")
    except OSError as exc:
        print(f"Unable to create log file {LOG_FILE}: {exc}")
    else:
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(logging.Formatter(log_format))
        handlers.append(file_handler)

    logging.basicConfig(level=logging.DEBUG, handlers=handlers, force=True)

    if any(isinstance(handler, logging.FileHandler) for handler in handlers):
        logger.info("Writing web UI logs to %s", LOG_FILE)


def _resolve_font_directory(context: AppContext) -> Path:
    """Determine the base directory to browse for fonts."""

    base = Path("/config/fonts")

    try:
        base.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        logger.warning("Unable to ensure font directory %s: %s", base, exc)

    return base


class WebRequestHandler(BaseHTTPRequestHandler):
    context: AppContext
    tv_manager: TvYamlManager
    font_directory: Path

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

    def _resolve_card_type_thumbnail(self, requested_name: str) -> Path | None:
        """Return a thumbnail file matching the requested card type image."""

        requested_slug = slugify_card_type(Path(requested_name).stem)
        logger.debug(
            "Resolving thumbnail for %s (slug=%s)", requested_name, requested_slug
        )

        prepared = prepare_thumbnail_from_config(requested_slug)
        if prepared:
            logger.debug(
                "Using prepared thumbnail for slug %s at %s", requested_slug, prepared
            )
            return prepared

        filename = DEFAULT_THUMBNAIL_SLUG_MAP.get(requested_slug)
        if not filename:
            logger.debug("No thumbnail mapping found for slug %s", requested_slug)
            return None

        suffix = Path(filename).suffix.lower()
        candidate_paths = []
        try:
            candidate_paths.append((CONFIG_THUMBNAIL_ROOT / filename).resolve())
        except OSError:
            pass
        try:
            candidate_paths.append((REPO_THUMBNAIL_ROOT / filename).resolve())
        except OSError:
            pass
        try:
            candidate_paths.append((STATIC_ROOT / "card-types" / f"{requested_slug}{suffix}").resolve())
        except OSError:
            pass

        for path in candidate_paths:
            if path.exists() and path.is_file():
                logger.debug("Matched thumbnail %s for slug %s", path, requested_slug)
                return path

        logger.debug("No thumbnail found for slug %s", requested_slug)
        return None

    def _parse_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError("Invalid JSON payload") from exc

    def _run_manager_action(self, action: Callable[[], None], *, context: str | None = None) -> None:
        if context:
            logger.info("Running action: %s", context)
        try:
            action()
        except ActionInProgressError as exc:
            self._error(str(exc), status=HTTPStatus.CONFLICT)
            return
        except Exception as exc:  # pylint: disable=broad-except
            logger.exception("Action %s failed", context or action)
            self._error(str(exc), status=HTTPStatus.INTERNAL_SERVER_ERROR)
            return

        self.tv_manager.invalidate()
        self._json_response({"status": "ok"})

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
            if target.exists() and target.is_file():
                self._serve_file(target)
                return

            if rel.startswith("card-types/"):
                fallback = self._resolve_card_type_thumbnail(Path(rel).name)
                if fallback is not None:
                    self._serve_file(fallback)
                    return

            self.send_error(HTTPStatus.NOT_FOUND.value)
            return

        if parsed.path == "/api/card-types/thumbnail":
            params = parse_qs(parsed.query)
            slug = params.get("slug", [""])[0].strip()
            if not slug:
                logger.debug("Thumbnail API request missing slug: %s", self.path)
                self._error("Missing card type slug")
                return

            logger.debug("Thumbnail API request for slug=%s", slug)
            match = self._resolve_card_type_thumbnail(slug)
            if match is None:
                logger.info("Thumbnail not found for slug %s", slug)
                self.send_error(HTTPStatus.NOT_FOUND.value)
                return

            logger.debug("Serving thumbnail %s for slug %s", match, slug)
            self._serve_file(match)
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
                    "fontDirectory": self.font_directory.as_posix(),
                }
            )
            return

        if parsed.path == "/api/fonts":
            params = parse_qs(parsed.query)
            requested = self._resolve_font_path(
                params.get("path", [self.font_directory.as_posix()])[0]
            )
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

        if parsed.path == "/api/client-log":
            try:
                payload = self._parse_json()
            except ValueError as exc:
                self._error(str(exc))
                return

            message = payload.get("message") or payload.get("event")
            level = payload.get("level", "DEBUG").upper()
            context = payload.get("context", {})

            if not message:
                self._error("Client log entries must include a message")
                return

            numeric_level = logging.getLevelName(level)
            if not isinstance(numeric_level, int):
                numeric_level = logging.DEBUG

            logger.log(
                numeric_level,
                "Client log: %s | context=%s",
                message,
                context,
            )

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

        if parsed.path == "/api/actions/sync":
            self._run_manager_action(run_metadata_sync, context="metadata-sync")
            return

        if parsed.path == "/api/actions/build":
            self._run_manager_action(run_builder, context="build-all")
            return

        if parsed.path == "/api/actions/build-series":
            try:
                payload = self._parse_json()
            except ValueError as exc:
                self._error(str(exc))
                return

            series_name = payload.get("name")
            if not series_name:
                self._error("Missing series name")
                return

            series_config = payload.get("config") if isinstance(payload, dict) else None
            logger.info("Build requested for %s", series_name)
            logger.debug("Series config: %s", series_config)
            self._run_manager_action(
                lambda: run_builder_for_series(
                    self.context, self.tv_manager, series_name, series_config
                ),
                context=f"build-series:{series_name}",
            )
            return

        if parsed.path == "/api/actions/revert-series":
            try:
                payload = self._parse_json()
            except ValueError as exc:
                self._error(str(exc))
                return

            series_name = payload.get("name")
            if not series_name:
                self._error("Missing series name")
                return

            series_config = payload.get("config") if isinstance(payload, dict) else None
            logger.info("Revert requested for %s", series_name)
            logger.debug("Series config: %s", series_config)
            self._run_manager_action(
                lambda: revert_series_cards(self.tv_manager, series_name, series_config),
                context=f"revert-series:{series_name}",
            )
            return

        if parsed.path == "/api/actions/forget-cards":
            try:
                payload = self._parse_json()
            except ValueError as exc:
                self._error(str(exc))
                return

            series_name = payload.get("name")
            if not series_name:
                self._error("Missing series name")
                return

            series_config = payload.get("config") if isinstance(payload, dict) else None
            logger.info("Forget cards requested for %s", series_name)
            logger.debug("Series config: %s", series_config)
            self._run_manager_action(
                lambda: forget_series_cards(self.tv_manager, series_name, series_config),
                context=f"forget-cards:{series_name}",
            )
            return

        if parsed.path == "/api/fonts/upload":
            content_type = self.headers.get("Content-Type", "")
            if "multipart/form-data" not in content_type:
                self._error(
                    "Uploads must be sent as multipart form data",
                    status=HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
                )
                return

            form = FieldStorage(
                fp=self.rfile,
                headers=self.headers,
                environ={
                    "REQUEST_METHOD": "POST",
                    "CONTENT_TYPE": content_type,
                    "CONTENT_LENGTH": self.headers.get("Content-Length", "0"),
                },
                keep_blank_values=True,
            )

            file_field = form.get("file")
            if not file_field or not getattr(file_field, "filename", None):
                self._error("Missing font file")
                return

            filename = Path(file_field.filename).name
            target_directory = self._resolve_font_path(
                form.getfirst("path", self.font_directory.as_posix())
            )

            try:
                target_directory.mkdir(parents=True, exist_ok=True)
            except OSError as exc:  # pylint: disable=broad-except
                self._error(str(exc), status=HTTPStatus.INTERNAL_SERVER_ERROR)
                return

            destination = (target_directory / filename).resolve(strict=False)
            try:
                destination.write_bytes(file_field.file.read())
            except OSError as exc:  # pylint: disable=broad-except
                self._error(str(exc), status=HTTPStatus.INTERNAL_SERVER_ERROR)
                return

            self._json_response({"status": "ok", "path": destination.as_posix()})
            return

        self.send_error(HTTPStatus.NOT_FOUND.value)

    def _resolve_font_path(self, raw_path: str) -> Path:
        """Clamp the requested font browser path to the configured directory."""

        base = self.font_directory.resolve(strict=False)
        candidate = Path(raw_path) if raw_path else base

        if not candidate.is_absolute():
            candidate = (base / candidate).resolve(strict=False)
        else:
            candidate = candidate.resolve(strict=False)

        try:
            candidate.relative_to(base)
        except ValueError:
            return base

        if not candidate.exists() or not candidate.is_dir():
            return base

        return candidate


def run(port: int = 4343) -> None:
    _configure_logging()

    context = create_app_context()
    tv_manager = TvYamlManager(context.default_tv_file)

    WebRequestHandler.context = context
    WebRequestHandler.tv_manager = tv_manager
    WebRequestHandler.font_directory = _resolve_font_directory(context)

    with ThreadingHTTPServer(("0.0.0.0", port), WebRequestHandler) as server:
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    run()
