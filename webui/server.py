from __future__ import annotations

import json
import logging
import mimetypes
import random
import re
from cgi import FieldStorage
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
import time
from typing import Callable
from urllib.parse import parse_qs, urlparse

from modules.CleanPath import CleanPath
from .card_type_images import (
    DEFAULT_THUMBNAIL_SLUG_MAP,
    REPO_THUMBNAIL_ROOT,
    get_static_thumbnail,
    load_card_type_thumbnails,
    prepare_thumbnail_from_config,
    slugify_card_type,
    static_thumbnail_cache_complete,
)
from .config import AppContext, create_app_context
from .options import build_card_type_extras, build_series_fields
from .services import (
    ActionInProgressError,
    download_logo_for_series,
    forget_series_cards,
    get_or_generate_preview,
    invalidate_preview_cache,
    list_preview_episodes,
    run_asset_downloads,
    backfill_tmdb_ids,
    backfill_rating_keys,
    run_builder,
    run_builder_for_series,
    run_metadata_sync,
    revert_series_cards,
    search_plex,
)
from .tv_data import TvYamlManager, _to_builtin
from .user_settings import load_settings, save_settings
from .tautulli import (
    TautulliSettings,
    fetch_users,
    get_or_fetch_recent_activity,
    start_recent_activity_monitor,
)

logger = logging.getLogger(__name__)

STATIC_ROOT = Path(__file__).resolve().parent / "static"
CONFIG_THUMBNAIL_ROOT = Path("/config/thumbnails")
TV_SHOWS_ROOT = Path("/config/TV_Shows")
TEMPLATE_ROOT = Path(__file__).resolve().parent / "templates"
LOG_FILE = Path("/config/webui.log")


_TRAILING_YEAR_PATTERNS = (
    re.compile(r"\s*\(\d{4}\)\s*$"),
    re.compile(r"\s+\d{4}\s*$"),
)


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


def _series_aliases(title: str) -> list[str]:
    aliases: list[str] = []
    try:
        normalized = str(title)
    except Exception:
        return aliases

    normalized = normalized.strip()
    if not normalized:
        return aliases

    aliases.append(normalized.casefold())
    stripped = normalized
    for pattern in _TRAILING_YEAR_PATTERNS:
        stripped = pattern.sub("", stripped)
    stripped = stripped.strip()
    if stripped and stripped.casefold() not in aliases:
        aliases.append(stripped.casefold())

    return aliases


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
        try:
            self.wfile.write(body)
        except BrokenPipeError:
            logger.warning(
                "Client disconnected before JSON response could be sent for %s",
                self.path,
            )
        except ConnectionResetError:
            logger.warning(
                "Client connection reset before JSON response could be sent for %s",
                self.path,
            )

    def _error(self, message: str, status: HTTPStatus = HTTPStatus.BAD_REQUEST) -> None:
        self._json_response({"error": message}, status=status)

    def _serve_file(self, file_path: Path) -> None:
        if not file_path.exists() or not file_path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND.value)
            return

        mime, _ = mimetypes.guess_type(file_path.as_posix())
        if mime is None:
            font_mimes = {
                ".ttf": "font/ttf",
                ".otf": "font/otf",
                ".woff": "font/woff",
                ".woff2": "font/woff2",
                ".ttc": "font/collection",
            }
            mime = font_mimes.get(file_path.suffix.lower())
        data = file_path.read_bytes()

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", mime or "application/octet-stream")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _wait_for_logo(self, logo_path: Path, attempts: int = 6, delay: float = 0.5) -> Path | None:
        """Wait briefly for a logo file to appear on disk."""

        for _ in range(attempts):
            if logo_path.exists() and logo_path.is_file():
                return logo_path

            time.sleep(delay)

        return None

    def _resolve_series_logo(self, series_name: str) -> Path | None:
        """Return the logo.png for a given series if it exists."""

        base = Path("/config/source").resolve()
        safe_series_name = CleanPath.sanitize_name(series_name)

        try:
            series_dir = (base / safe_series_name).resolve()
        except OSError:
            return None

        if not str(series_dir).startswith(str(base)):
            logger.warning("Attempted logo access outside of source directory: %s", series_dir)
            return None

        logo_path = series_dir / "logo.png"
        if logo_path.exists() and logo_path.is_file():
            return logo_path

        logger.info("Logo not found for series %s; attempting download", series_name)

        try:
            download_logo_for_series(
                self.context,
                self.tv_manager,
                series_name,
            )
        except ActionInProgressError:
            logger.info(
                "Logo download already in progress; waiting for completion for %s",
                series_name,
            )
            waited_logo = self._wait_for_logo(logo_path)
            if waited_logo:
                return waited_logo

            try:
                download_logo_for_series(
                    self.context,
                    self.tv_manager,
                    series_name,
                    max_wait_attempts=2,
                    wait_interval=0.5,
                )
            except ActionInProgressError:
                logger.info(
                    "Logo download still in progress after waiting; skipping %s",
                    series_name,
                )
                return None
        except ValueError:
            logger.warning(
                "Unable to resolve configuration for series %s when downloading logo",
                series_name,
            )
            return None
        except Exception:  # pylint: disable=broad-except
            logger.exception("Failed to download logo for series %s", series_name)
            return None

        waited_logo = self._wait_for_logo(logo_path)
        if waited_logo:
            return waited_logo

        logger.info("Logo download completed but file still missing for series %s", series_name)
        return None

    def _resolve_card_type_thumbnail(self, requested_name: str) -> Path | None:
        """Return a thumbnail file matching the requested card type image."""

        requested_slug = slugify_card_type(Path(requested_name).stem)
        logger.debug(
            "Resolving thumbnail for %s (slug=%s)", requested_name, requested_slug
        )
        logger.debug("Resolving thumbnail for %s (slug=%s)", requested_name, requested_slug)

        cached = get_static_thumbnail(requested_slug)
        if cached:
            logger.debug(
                "Using cached static thumbnail for slug %s at %s",
                requested_slug,
                cached,
            )
            return cached

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

    def _resolve_card_type_original(self, requested_name: str) -> Path | None:
        """Return the original image file for the requested card type if available."""

        requested_slug = slugify_card_type(Path(requested_name).stem)
        if not requested_slug:
            return None

        logger.debug(
            "Resolving original thumbnail for %s (slug=%s)", requested_name, requested_slug
        )

        filename = DEFAULT_THUMBNAIL_SLUG_MAP.get(requested_slug)
        candidate_paths: list[Path] = []
        for root in (CONFIG_THUMBNAIL_ROOT, REPO_THUMBNAIL_ROOT):
            try:
                root_resolved = root.resolve()
            except OSError:
                continue

            if filename:
                candidate = (root / filename).resolve()
                if str(candidate).startswith(str(root_resolved)):
                    candidate_paths.append(candidate)

            try:
                for entry in root.iterdir():
                    try:
                        if not entry.is_file():
                            continue
                    except OSError:
                        continue

                    if slugify_card_type(entry.stem) != requested_slug:
                        continue

                    resolved_entry = entry.resolve()
                    if not str(resolved_entry).startswith(str(root_resolved)):
                        continue

                    if resolved_entry not in candidate_paths:
                        candidate_paths.append(resolved_entry)
            except FileNotFoundError:
                continue
            except OSError:
                continue

        for path in candidate_paths:
            try:
                if path.exists() and path.is_file():
                    logger.debug(
                        "Matched original thumbnail %s for slug %s", path, requested_slug
                    )
                    return path
            except OSError:
                continue

        logger.debug("No original thumbnail found for slug %s", requested_slug)
        return None

    def _series_directory_candidates(
        self, *, slug: str | None, name: str | None, season: str | None
    ) -> list[Path]:
        """Return possible directories for static previews."""

        try:
            base = TV_SHOWS_ROOT.resolve()
        except OSError:
            return []

        season_dirname = f"Season {season}" if season else None
        raw_candidates = []
        for value in (slug, name):
            if not value:
                continue
            safe_value = CleanPath.sanitize_name(value.strip())
            try:
                series_dir = (base / safe_value).resolve()
            except OSError:
                continue

            if not str(series_dir).startswith(str(base)):
                logger.warning(
                    "Attempted preview access outside TV shows directory: %s", series_dir
                )
                continue

            if season_dirname:
                try:
                    season_dir = (series_dir / season_dirname).resolve()
                except OSError:
                    season_dir = None

                if season_dir and str(season_dir).startswith(str(series_dir)):
                    raw_candidates.append(season_dir)

            raw_candidates.append(series_dir)

        candidates: list[Path] = []
        seen: set[Path] = set()
        for directory in raw_candidates:
            try:
                resolved = directory.resolve()
            except OSError:
                continue

            if resolved in seen:
                continue

            seen.add(resolved)
            candidates.append(resolved)

        return candidates

    def _resolve_static_preview(
        self, *, slug: str | None, name: str | None, season: str | None
    ) -> Path | None:
        """Return a random static preview image for the requested series."""

        candidates = self._series_directory_candidates(
            slug=slug or None, name=name or None, season=season or None
        )
        valid_suffixes = {".png", ".jpg", ".jpeg", ".webp"}

        for directory in candidates:
            try:
                files = [
                    entry
                    for entry in directory.iterdir()
                    if entry.is_file() and entry.suffix.lower() in valid_suffixes
                ]
            except OSError:
                continue

            if not files:
                continue

            return random.choice(files)

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

        if parsed.path == "/api/series-logo":
            params = parse_qs(parsed.query)
            name = params.get("name", [""])[0].strip()
            if not name:
                self._error("Missing series name")
                return

            match = self._resolve_series_logo(name)
            if match is None:
                self.send_error(HTTPStatus.NOT_FOUND.value)
                return

            self._serve_file(match)
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

        if parsed.path == "/api/card-types/preview":
            params = parse_qs(parsed.query)
            slug = params.get("slug", [""])[0].strip()
            if not slug:
                logger.debug("Preview API request missing slug: %s", self.path)
                self._error("Missing card type slug")
                return

            logger.debug("Preview API request for slug=%s", slug)
            match = self._resolve_card_type_original(slug)
            if match is None:
                logger.info("Original preview not found for slug %s", slug)
                match = self._resolve_card_type_thumbnail(slug)
            if match is None:
                self.send_error(HTTPStatus.NOT_FOUND.value)
                return

            logger.debug("Serving preview %s for slug %s", match, slug)
            self._serve_file(match)
            return

        if parsed.path == "/api/preview/static":
            params = parse_qs(parsed.query)
            slug = params.get("slug", [""])[0].strip() or None
            name = params.get("name", [""])[0].strip() or None
            season = params.get("season", [""])[0].strip() or None

            match = self._resolve_static_preview(slug=slug, name=name, season=season)
            if match is None:
                self.send_error(HTTPStatus.NOT_FOUND.value)
                return

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
                    "cardTypeExtras": build_card_type_extras(),
                    "fontDirectory": self.font_directory.as_posix(),
                    "services": {
                        "tmdbEnabled": self.context.preference_parser.use_tmdb,
                        "plexEnabled": self.context.preference_parser.use_plex,
                    },
                }
            )
            return

        if parsed.path == "/api/settings":
            self._json_response(load_settings(self.context.preference_file))
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

        if parsed.path == "/api/fonts/file":
            params = parse_qs(parsed.query)
            requested = self._resolve_font_file(params.get("path", [""])[0])
            if not requested:
                self._error("Font not found", status=HTTPStatus.NOT_FOUND)
                return
            self._serve_file(requested)
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

        if parsed.path == "/api/tautulli/users":
            try:
                settings = TautulliSettings.from_settings()
                if not settings:
                    raise RuntimeError("Tautulli is not configured. Set the URL and API key in settings.")
                self._json_response({"users": fetch_users(settings)})
            except Exception as exc:  # pylint: disable=broad-except
                self._error(str(exc), status=HTTPStatus.BAD_REQUEST)
                return

        if parsed.path == "/api/tautulli/recents":
            try:
                payload = get_or_fetch_recent_activity(self.context, self.tv_manager)
            except Exception as exc:  # pylint: disable=broad-except
                self._error(str(exc), status=HTTPStatus.BAD_REQUEST)
                return

            self._json_response(payload)
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

        if parsed.path == "/api/settings":
            try:
                payload = self._parse_json()
            except ValueError as exc:
                self._error(str(exc))
                return

            updated = save_settings(payload, self.context.preference_file)
            self._json_response(updated)
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
            force_refresh = bool(payload.get("force"))
            preview_episode_key = payload.get("previewEpisode")
            if not show_name or not isinstance(config, dict):
                self._error("Preview requires a series name and configuration")
                return

            try:
                mime, data = get_or_generate_preview(
                    self.context,
                    self.tv_manager,
                    show_name,
                    config,
                    force=force_refresh,
                    preview_episode_key=preview_episode_key,
                    prefer_existing=payload.get("preferExisting", True),
                )
            except Exception as exc:  # pylint: disable=broad-except
                self._error(str(exc), status=HTTPStatus.INTERNAL_SERVER_ERROR)
                return

            self._json_response({"mime": mime, "data": data})
            return

        if parsed.path == "/api/preview/episodes":
            try:
                payload = self._parse_json()
            except ValueError as exc:
                self._error(str(exc))
                return

            show_name = payload.get("name")
            config = payload.get("config")
            if not show_name or not isinstance(config, dict):
                self._error("Series name and configuration are required")
                return

            try:
                episodes = list_preview_episodes(
                    self.context, self.tv_manager, show_name, config
                )
            except Exception as exc:  # pylint: disable=broad-except
                self._error(str(exc), status=HTTPStatus.INTERNAL_SERVER_ERROR)
                return

            self._json_response({"episodes": episodes})
            return

        if parsed.path == "/api/actions/sync":
            self._run_manager_action(run_metadata_sync, context="metadata-sync")
            return

        if parsed.path == "/api/actions/build":
            invalidate_preview_cache()
            self._run_manager_action(run_builder, context="build-all")
            return

        if parsed.path == "/api/actions/download-sources":
            self._run_manager_action(run_asset_downloads, context="download-sources")
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
            invalidate_preview_cache(series_name)
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

            try:
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
            except Exception as exc:  # pylint: disable=broad-except
                logger.exception("Unable to parse uploaded font data")
                self._error(str(exc), status=HTTPStatus.BAD_REQUEST)
                return

            try:
                try:
                    file_field = form["file"]
                except KeyError:
                    file_field = None
            except Exception as exc:  # pylint: disable=broad-except
                logger.exception("Unable to read uploaded font data")
                self._error(str(exc), status=HTTPStatus.BAD_REQUEST)
                return

            # cgi.FieldStorage cannot be evaluated for truthiness, so explicitly
            # check for the missing field and an empty filename.
            if file_field is None or not getattr(file_field, "filename", None):
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

def _resolve_font_file(self, raw_path: str) -> Path | None:
        """Resolve a font file path ensuring it stays within the font directory."""

        if not raw_path:
            return None

        base = self.font_directory.resolve(strict=False)
        candidate = Path(raw_path)

        if not candidate.is_absolute():
            candidate = (base / candidate).resolve(strict=False)
        else:
            candidate = candidate.resolve(strict=False)

        try:
            candidate.relative_to(base)
        except ValueError:
            return None

        if not candidate.exists() or not candidate.is_file():
            return None

        return candidate


def _run_startup_tasks_async(context: AppContext, tv_manager: TvYamlManager) -> Thread:
    """Launch background work that should not block server startup."""

    def _task() -> None:
        if context.preference_parser.use_tmdb:
            try:
                result = backfill_tmdb_ids(context, tv_manager)
            except Exception as exc:  # pylint: disable=broad-except
                logger.warning("Unable to backfill TMDb IDs on startup: %s", exc)
            else:
                updated = result.get("updated", 0)
                total = result.get("total", 0)
                if updated:
                    logger.info("Updated TMDb IDs for %s of %s series", updated, total)

        if context.preference_parser.use_plex:
            try:
                result = backfill_rating_keys(context, tv_manager)
            except Exception as exc:  # pylint: disable=broad-except
                logger.warning("Unable to backfill Plex rating keys on startup: %s", exc)
            else:
                updated = result.get("updated", 0)
                total = result.get("total", 0)
                if updated:
                    logger.info("Updated Plex rating keys for %s of %s series", updated, total)

        if static_thumbnail_cache_complete():
            logger.info("Card type thumbnail cache already prepared; skipping refresh")
        else:
            try:
                thumbnails = load_card_type_thumbnails(force=True)
            except Exception as exc:  # pylint: disable=broad-except
                logger.warning("Unable to prefetch card type thumbnails: %s", exc)
            else:
                logger.info("Prefetched %d card type thumbnails", len(thumbnails))

    thread = Thread(target=_task, name="startup-tasks", daemon=True)
    thread.start()
    return thread


def run(port: int = 4343) -> None:
    _configure_logging()

    context = create_app_context()
    tv_manager = TvYamlManager(context.default_tv_file)

    _run_startup_tasks_async(context, tv_manager)

    start_recent_activity_monitor(context, tv_manager)

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
