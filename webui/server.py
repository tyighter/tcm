from __future__ import annotations

import base64
import hashlib
import json
import logging
import mimetypes
import os
import re
from cgi import FieldStorage
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
import time
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

from modules.CleanPath import CleanPath
from modules.SeriesInfo import SeriesInfo
from .card_type_images import (
    DEFAULT_THUMBNAIL_SLUG_MAP,
    REPO_THUMBNAIL_ROOT,
    get_static_thumbnail,
    load_card_type_thumbnails,
    prepare_thumbnail_from_config,
    slugify_card_type,
    static_thumbnail_cache_complete,
)
from .config import AppContext, create_app_context, preference_setup_required
from .options import build_card_type_extras, build_series_fields
from .services import (
    ActionInProgressError,
    active_action_status,
    backfill_episode_rating_keys,
    backfill_rating_keys,
    backfill_tmdb_ids,
    delete_series_cards,
    download_logo_for_series,
    ensure_episode_rating_keys_in_payload,
    forget_series_cards,
    get_or_generate_preview,
    invalidate_preview_cache,
    list_preview_episodes,
    preview_logger,
    run_asset_downloads,
    run_asset_downloads_for_series,
    run_builder,
    run_builder_for_series,
    run_fresh_build_for_series,
    run_metadata_sync,
    revert_series_cards,
    register_action_context,
    search_plex,
    _load_show_for_preview,
)
from .tv_data import TvYamlManager, _to_builtin, start_daily_tv_yaml_backup
from .user_settings import SettingsPersistenceError, load_settings, save_settings
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

_PREWARM_ENABLED_ENV = "TCM_WEBUI_PREWARM_PREVIEWS"
_PREWARM_LIMIT_ENV = "TCM_WEBUI_PREWARM_LIMIT"
_PREWARM_DEFAULT_LIMIT = 200
_PREWARM_MIN_LIMIT = 1
_PREWARM_MAX_LIMIT = 200


def _env_flag_enabled(name: str, default: bool = False) -> bool:
    """Parse a boolean-style environment variable."""

    raw = os.getenv(name)
    if raw is None:
        return default

    normalized = str(raw).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False

    logger.warning("Invalid boolean for %s=%r; using default=%s", name, raw, default)
    return default


def _env_int(name: str, default: int, *, minimum: int | None = None, maximum: int | None = None) -> int:
    """Parse and clamp an integer environment variable."""

    raw = os.getenv(name)
    if raw is None:
        return default

    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        logger.warning("Invalid integer for %s=%r; using default=%s", name, raw, default)
        return default

    if minimum is not None and value < minimum:
        logger.info("Clamping %s from %s to minimum=%s", name, value, minimum)
        value = minimum
    if maximum is not None and value > maximum:
        logger.info("Clamping %s from %s to maximum=%s", name, value, maximum)
        value = maximum
    return value


def _prewarm_preview_cache(context: AppContext, tv_manager: TvYamlManager) -> None:
    """Generate preview cache entries for a small initial set of series."""

    settings = load_settings(context.preference_file)
    default_enabled = bool(settings.get("prewarm_previews", True))
    if not _env_flag_enabled(_PREWARM_ENABLED_ENV, default=default_enabled):
        logger.info(
            "Preview prewarm disabled; set settings.prewarm_previews=true or %s=true to enable",
            _PREWARM_ENABLED_ENV,
        )
        return

    settings_default_limit = settings.get("prewarm_preview_limit", _PREWARM_DEFAULT_LIMIT)
    if not isinstance(settings_default_limit, int):
        settings_default_limit = _PREWARM_DEFAULT_LIMIT

    limit = _env_int(
        _PREWARM_LIMIT_ENV,
        settings_default_limit,
        minimum=_PREWARM_MIN_LIMIT,
        maximum=_PREWARM_MAX_LIMIT,
    )

    started_at = time.perf_counter()
    try:
        payload = tv_manager.as_payload()
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning("Preview prewarm aborted; unable to read tv.yml payload: %s", exc)
        return

    series_entries = payload.get("series")
    if not isinstance(series_entries, list) or not series_entries:
        logger.info("Preview prewarm skipped; no series found")
        return

    selected_entries: list[tuple[str, dict[str, Any]]] = []
    for entry in series_entries:
        if len(selected_entries) >= limit:
            break
        if not isinstance(entry, dict):
            continue
        show_name = str(entry.get("name") or "").strip()
        config = entry.get("config")
        if not show_name or not isinstance(config, dict):
            continue
        selected_entries.append((show_name, config))

    if not selected_entries:
        logger.info("Preview prewarm skipped; no valid series entries found")
        return

    logger.info(
        "Starting preview prewarm for %d series (limit=%d, configured=%s)",
        len(selected_entries),
        limit,
        _PREWARM_LIMIT_ENV,
    )

    failures = 0
    for show_name, series_config in selected_entries:
        series_started_at = time.perf_counter()
        try:
            get_or_generate_preview(
                context,
                tv_manager,
                show_name,
                series_config,
                force=False,
                prefer_existing=True,
            )
        except Exception as exc:  # pylint: disable=broad-except
            failures += 1
            logger.warning("Preview prewarm failed for %s: %s", show_name, exc)
            continue

        logger.info(
            "Preview prewarm completed for %s in %.2fs",
            show_name,
            time.perf_counter() - series_started_at,
        )

    duration = time.perf_counter() - started_at
    logger.info(
        "Preview prewarm finished in %.2fs (%d attempted, %d failed)",
        duration,
        len(selected_entries),
        failures,
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

    def _tv_payload_or_error(self) -> dict | None:
        try:
            return self.tv_manager.as_payload()
        except Exception as exc:  # pylint: disable=broad-except
            logger.error("Unable to load tv.yml for %s: %s", self.path, exc)
            self._error(f"Unable to load tv.yml: {exc}", status=HTTPStatus.BAD_REQUEST)
            return None

    def _payload_fingerprint(self, payload: dict[str, Any]) -> str:
        serialized = json.dumps(
            _to_builtin(payload),
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    def _annotate_plex_lookup_status(self, payload: dict) -> None:
        if not self.context.preference_parser.use_plex:
            return

        try:
            plex = self.context.get_plex_interface()
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning("Unable to check Plex match status: %s", exc)
            return

        entries = payload.get("series")
        if not isinstance(entries, list):
            return

        for entry in entries:
            if not isinstance(entry, dict):
                continue
            config = entry.get("config")
            if not isinstance(config, dict):
                continue
            library = config.get("library")
            if not library:
                entry["plex_lookup_failed"] = False
                continue

            try:
                series_info = SeriesInfo(entry.get("name", ""), config.get("year"))
            except Exception:
                entry["plex_lookup_failed"] = True
                continue

            rating_key = plex.get_series_rating_key(library, series_info, config)
            entry["plex_lookup_failed"] = rating_key is None

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

        try:
            self.wfile.write(data)
        except BrokenPipeError:
            logger.warning(
                "Client disconnected before file response could be sent for %s",
                self.path,
            )
        except ConnectionResetError:
            logger.warning(
                "Client connection reset before file response could be sent for %s",
                self.path,
            )

    def _serve_binary(self, data: bytes, mime: str = "application/octet-stream") -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", mime or "application/octet-stream")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()

        try:
            self.wfile.write(data)
        except BrokenPipeError:
            logger.warning(
                "Client disconnected before binary response could be sent for %s",
                self.path,
            )
        except ConnectionResetError:
            logger.warning(
                "Client connection reset before binary response could be sent for %s",
                self.path,
            )

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

    def _find_series_entry(self, *, slug: str | None, name: str | None) -> tuple[str, dict] | None:
        """Return the series name and config for a slug or name."""

        try:
            payload = self.tv_manager.as_payload()
        except Exception as exc:  # pylint: disable=broad-except
            logger.error("Unable to load tv.yml for preview lookup: %s", exc)
            return None

        entries = payload.get("series", []) if isinstance(payload, dict) else []
        normalized_name = name.strip().casefold() if isinstance(name, str) else None

        for entry in entries:
            entry_name = entry.get("name")
            entry_slug = entry.get("slug")

            if slug and entry_slug and slug == entry_slug:
                return entry_name or slug, entry.get("config") or {}

            if normalized_name and isinstance(entry_name, str):
                if entry_name.strip().casefold() == normalized_name:
                    return entry_name, entry.get("config") or {}

        return None

    def _select_episode_for_preview(
        self,
        show,
        *,
        preview_episode_key: str | None,
        season: str | None,
        episode: str | None,
    ):
        """Select the episode to preview."""

        def _as_int(value: object) -> int | None:
            try:
                return int(value)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                return None

        if preview_episode_key and preview_episode_key in show.episodes:
            return show.episodes[preview_episode_key]

        season_number = _as_int(season)
        episode_number = _as_int(episode)

        for candidate in show.episodes.values():
            info = getattr(candidate, "episode_info", None)
            if info is None:
                continue

            candidate_season = _as_int(getattr(info, "season_number", None))
            candidate_episode = _as_int(getattr(info, "episode_number", None))

            if season_number is not None and season_number != candidate_season:
                continue

            if episode_number is not None and episode_number != candidate_episode:
                continue

            return candidate

        return None

    def _resolve_preview_path(
        self,
        *,
        series_name: str,
        series_config: dict,
        preview_episode_key: str | None,
        season: str | None,
        episode: str | None,
    ) -> Path | None:
        """Resolve the path to a generated card for the requested episode."""

        try:
            show = _load_show_for_preview(
                self.context,
                self.tv_manager,
                series_name,
                series_config,
            )
        except Exception as exc:  # pylint: disable=broad-except
            logger.error("Unable to load show for preview %s: %s", series_name, exc)
            return None

        candidate_episode = self._select_episode_for_preview(
            show,
            preview_episode_key=preview_episode_key,
            season=season,
            episode=episode,
        )

        destination = getattr(candidate_episode, "destination", None)
        if destination and isinstance(destination, Path):
            try:
                if destination.exists() and destination.is_file():
                    return destination
            except OSError:
                return None

        return None

    def _parse_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError("Invalid JSON payload") from exc

    def _validate_preferences_path(self, raw_value: Any, *, expect_file: bool) -> dict[str, Any]:
        value = str(raw_value or "")
        trimmed = value.strip()
        messages: list[str] = []
        path: Path | None = None

        if not trimmed:
            messages.append("This path is required.")
            return {"value": value, "normalized": "", "valid": False, "messages": messages}

        if value != trimmed:
            messages.append("Remove leading/trailing spaces from the path.")

        if re.search(r"[\r\n\t]", trimmed):
            messages.append("Path cannot include tabs or line breaks.")

        if "://" in trimmed:
            messages.append("Use a local filesystem path, not a URL.")

        if re.search(r'[<>|*"\\0]', trimmed):
            messages.append("Path includes characters that are usually invalid in filesystem paths.")

        try:
            path = Path(trimmed).expanduser()
        except (RuntimeError, OSError, ValueError):
            messages.append("Unable to parse this path.")

        if path is not None:
            exists = path.exists()
            if not exists:
                messages.append("Path does not exist on the server.")
            elif expect_file and not path.is_file():
                messages.append("Path must point to a file.")
            elif not expect_file and not path.is_dir():
                messages.append("Path must point to a directory.")

            if exists:
                readable = os.access(path, os.R_OK)
                if not readable:
                    messages.append("Path is not readable by the application user.")

                if not expect_file and not os.access(path, os.X_OK):
                    messages.append("Directory is not accessible (missing execute permission).")

        return {
            "value": value,
            "normalized": path.as_posix() if path else trimmed,
            "valid": len(messages) == 0,
            "messages": messages,
        }

    def _validate_preferences_paths_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        source_result = self._validate_preferences_path(payload.get("source"), expect_file=False)
        series_result = self._validate_preferences_path(payload.get("series"), expect_file=True)
        valid = source_result["valid"] and series_result["valid"]
        response: dict[str, Any] = {
            "valid": valid,
            "fields": {
                "source": source_result,
                "series": series_result,
            },
            "messages": [],
        }

        if not valid:
            response["messages"] = [
                "Update the highlighted paths so they exist and are readable, then try again."
            ]

        return response

    def _plex_connection_status(self) -> dict[str, Any]:
        if not self.context.preference_parser.use_plex:
            return {"connected": False, "configured": False, "message": "Plex is disabled in preferences."}

        try:
            plex = self.context.get_plex_interface()
            plex.get_libraries()
        except Exception as exc:  # pylint: disable=broad-except
            return {"connected": False, "configured": True, "message": str(exc)}

        return {"connected": True, "configured": True, "message": "Connected."}

    def _tautulli_connection_status(self) -> dict[str, Any]:
        settings = TautulliSettings.from_settings()
        if settings is None:
            return {
                "connected": False,
                "configured": False,
                "message": "Tautulli URL/API key are not configured.",
            }

        try:
            fetch_users(settings)
        except Exception as exc:  # pylint: disable=broad-except
            return {"connected": False, "configured": True, "message": str(exc)}

        return {"connected": True, "configured": True, "message": "Connected."}

    def _run_manager_action(self, action: Callable[[], None], *, context: str | None = None) -> None:
        if context:
            logger.info("Running action: %s", context)
        try:
            with register_action_context(context):
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

    def _should_backfill_episode_rating_keys(self, payload: dict[str, Any]) -> bool:
        if not getattr(self.context.preference_parser, "use_plex", False):
            return False

        series_entries = payload.get("series")
        if not isinstance(series_entries, list):
            return False

        for entry in series_entries:
            config = entry.get("config") if isinstance(entry, dict) else None
            if not isinstance(config, dict):
                continue
            if config.get("rating_key") not in (None, ""):
                return True

        return False

    def _build_config_save_details(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Build structured save diagnostics for /api/config responses."""

        series_entries = payload.get("series") if isinstance(payload, dict) else None
        entries = series_entries if isinstance(series_entries, list) else []

        warnings: list[str] = []
        failed_entries: list[dict[str, Any]] = []
        validation_errors: list[dict[str, Any]] = []
        validation_warnings: list[dict[str, Any]] = []
        seen_names: set[str] = set()

        for index, entry in enumerate(entries):
            if not isinstance(entry, dict):
                failed_entries.append(
                    {
                        "index": index,
                        "name": None,
                        "reason": "Entry is not an object.",
                    }
                )
                continue

            name = str(entry.get("name") or "").strip()
            if not name:
                failed_entries.append(
                    {
                        "index": index,
                        "name": None,
                        "reason": "Entry name is missing.",
                    }
                )
            else:
                key = name.casefold()
                if key in seen_names:
                    warnings.append(f"Duplicate series name detected: {name}")
                seen_names.add(key)

            config = entry.get("config")
            if not isinstance(config, dict):
                failed_entries.append(
                    {
                        "index": index,
                        "name": name or None,
                        "reason": "Entry config must be an object.",
                    }
                )
                continue

            media_directory = str(config.get("media_directory") or "").strip()
            if "\0" in media_directory:
                validation_errors.append(
                    {
                        "index": index,
                        "name": name or None,
                        "field": "library_override",
                        "message": "Path cannot include null characters.",
                        "severity": "error",
                    }
                )

            font_file = str((config.get("font") or {}).get("file") or "").strip()
            if "\0" in font_file:
                validation_errors.append(
                    {
                        "index": index,
                        "name": name or None,
                        "field": "font.file",
                        "message": "Path cannot include null characters.",
                        "severity": "error",
                    }
                )

            archive_name = str(config.get("archive_name") or "")
            if archive_name and archive_name.strip() == "":
                validation_errors.append(
                    {
                        "index": index,
                        "name": name or None,
                        "field": "archive_name",
                        "message": "Archive name is required.",
                        "severity": "error",
                    }
                )

            for numeric_id_field in ("tmdb_id", "tvdb_id", "tvrage_id", "sonarr_id"):
                numeric_id_value = str(config.get(numeric_id_field) or "").strip()
                if not numeric_id_value:
                    continue
                if not numeric_id_value.isdigit() or int(numeric_id_value) <= 0:
                    validation_errors.append(
                        {
                            "index": index,
                            "name": name or None,
                            "field": numeric_id_field,
                            "message": "ID must be a positive integer.",
                            "severity": "error",
                        }
                    )

            imdb_id = str(config.get("imdb_id") or "").strip()
            if imdb_id and not re.fullmatch(r"tt\d{5,}", imdb_id):
                validation_errors.append(
                    {
                        "index": index,
                        "name": name or None,
                        "field": "imdb_id",
                        "message": "IMDb IDs should look like tt1234567.",
                        "severity": "error",
                    }
                )

            for field_name, field_value in config.items():
                if not isinstance(field_name, str):
                    continue
                if not (field_name.endswith("_url") or field_name == "url"):
                    continue
                url_value = str(field_value or "").strip()
                if not url_value:
                    continue
                if not re.match(r"^https?://", url_value):
                    validation_warnings.append(
                        {
                            "index": index,
                            "name": name or None,
                            "field": field_name,
                            "message": "Prefer an http:// or https:// URL.",
                            "severity": "warning",
                        }
                    )

            if re.search(r"\(\d+\)\s*$", name) and not re.search(r"\((19|20)\d{2}\)\s*$", name):
                validation_warnings.append(
                    {
                        "index": index,
                        "name": name or None,
                        "field": "name",
                        "message": "Use a 4-digit year like “Series Name (2024)”.",
                        "severity": "warning",
                    }
                )

        unique_failed_entry_indexes = {
            int(item["index"])
            for item in failed_entries
            if isinstance(item.get("index"), int)
        }

        details: dict[str, Any] = {
            "saved_entries_count": max(len(entries) - len(unique_failed_entry_indexes), 0),
            "requested_entries_count": len(entries),
            "validation_warnings": warnings,
            "validation_errors": validation_errors,
            "field_validation_warnings": validation_warnings,
            "failed_entries": failed_entries,
            "has_warnings": bool(warnings) or bool(validation_warnings),
            "has_errors": bool(validation_errors),
            "has_failures": bool(failed_entries) or bool(validation_errors),
            "saved_at": time.time(),
        }

        return details

    def _backfill_episode_rating_keys_async(self) -> None:
        def _task() -> None:
            try:
                latest_payload = self.tv_manager.as_payload()
            except Exception as exc:  # pylint: disable=broad-except
                logger.warning("Unable to load tv.yml for async episode backfill: %s", exc)
                return

            try:
                updated_payload, updated, processed = ensure_episode_rating_keys_in_payload(
                    self.context, latest_payload
                )
            except Exception as exc:  # pylint: disable=broad-except
                logger.warning("Unable to backfill episode rating keys asynchronously: %s", exc)
                return

            if not updated:
                return

            total_series = processed or len(updated_payload.get("series") or [])
            logger.info(
                "Backfilled episode rating keys asynchronously for %s of %s series",
                updated,
                total_series,
            )

            original_by_name = {
                entry.get("name"): entry
                for entry in (latest_payload.get("series") or [])
                if isinstance(entry, dict) and entry.get("name")
            }

            for entry in updated_payload.get("series") or []:
                name = entry.get("name")
                if not name:
                    continue

                updated_config = entry.get("config") or {}
                if not isinstance(updated_config, dict):
                    continue

                updated_mappings = updated_config.get("episode_rating_keys")
                if not isinstance(updated_mappings, dict):
                    continue

                existing_config = (original_by_name.get(name, {}) or {}).get("config") or {}
                existing_mappings = (
                    existing_config.get("episode_rating_keys")
                    if isinstance(existing_config, dict)
                    else {}
                )

                for show_key, episodes in updated_mappings.items():
                    if not isinstance(episodes, dict) or not episodes:
                        continue

                    previous = (
                        existing_mappings.get(show_key, {})
                        if isinstance(existing_mappings, dict)
                        else {}
                    )
                    changes = {
                        label: key
                        for label, key in episodes.items()
                        if str(previous.get(label)) != str(key)
                    }
                    if not changes:
                        continue

                    try:
                        self.tv_manager.update_episode_rating_keys(name, show_key, changes)
                    except Exception as exc:  # pylint: disable=broad-except
                        logger.warning(
                            "Unable to persist episode rating keys for %s (%s): %s",
                            name,
                            show_key,
                            exc,
                        )

        Thread(target=_task, name="episode-rating-key-backfill", daemon=True).start()

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
            episode = params.get("episode", [""])[0].strip() or None
            preview_episode_key = params.get("previewEpisode", [""])[0].strip() or None

            series_entry = self._find_series_entry(slug=slug, name=name)
            if series_entry is None:
                self.send_error(HTTPStatus.NOT_FOUND.value)
                return

            series_name, series_config = series_entry
            preview_path = self._resolve_preview_path(
                series_name=series_name,
                series_config=series_config,
                preview_episode_key=preview_episode_key,
                season=season,
                episode=episode,
            )
            if preview_path is None:
                if preview_episode_key is None and season is not None and episode is not None:
                    preview_episode_key = f"{season}-{episode}"

                try:
                    mime, data = get_or_generate_preview(
                        self.context,
                        self.tv_manager,
                        series_name,
                        series_config,
                        force=False,
                        preview_episode_key=preview_episode_key,
                        prefer_existing=True,
                    )
                except Exception:
                    logger.exception("Unable to generate static preview for %s", series_name)
                    self.send_error(HTTPStatus.NOT_FOUND.value)
                    return

                try:
                    self._serve_binary(base64.b64decode(data), mime)
                except Exception:
                    logger.exception(
                        "Unable to decode generated static preview for %s",
                        series_name,
                    )
                    self.send_error(HTTPStatus.NOT_FOUND.value)
                return

            self._serve_file(preview_path)
            return

        if parsed.path == "/api/config":
            payload = self._tv_payload_or_error()
            if payload is None:
                return

            self._annotate_plex_lookup_status(payload)
            payload["fingerprint"] = self._payload_fingerprint(payload)
            self._json_response(payload)
            return

        if parsed.path == "/api/config/fingerprint":
            payload = self._tv_payload_or_error()
            if payload is None:
                return
            self._json_response({"fingerprint": self._payload_fingerprint(payload)})
            return

        if parsed.path == "/api/meta":
            tv_payload = self._tv_payload_or_error()
            if tv_payload is None:
                return

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
            settings = load_settings(self.context.preference_file)
            settings["preference_setup_required"] = preference_setup_required(
                self.context.preference_file
            )
            settings["preference_file_generated"] = self.context.preference_file_generated
            self._json_response(settings)
            return

        if parsed.path == "/api/services/status":
            self._json_response(
                {
                    "plex": self._plex_connection_status(),
                    "tautulli": self._tautulli_connection_status(),
                }
            )
            return

        if parsed.path == "/api/actions/status":
            self._json_response(active_action_status())
            return

        if parsed.path == "/api/backups":
            params = parse_qs(parsed.query)
            requested = self._resolve_backup_path(params.get("path", [""])[0])

            entries = []
            if requested.exists():
                for item in sorted(requested.iterdir(), key=lambda p: (p.is_file(), p.name.lower())):
                    entries.append(
                        {
                            "name": item.name,
                            "path": item.as_posix(),
                            "type": "file" if item.is_file() else "directory",
                            "modified": item.stat().st_mtime,
                        }
                    )

            self._json_response({"path": requested.as_posix(), "entries": entries})
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

            validation_details = self._build_config_save_details(payload)
            if validation_details.get("has_errors") is True:
                self._json_response(
                    {
                        "status": "error",
                        "error": "Configuration validation failed.",
                        "details": validation_details,
                    },
                    status=HTTPStatus.BAD_REQUEST,
                )
                return

            backfill_episode_keys = self._should_backfill_episode_rating_keys(payload)

            try:
                with self.tv_manager.priority_write():
                    try:
                        self.tv_manager.backup_on_save()
                    except Exception as exc:  # pylint: disable=broad-except
                        logger.warning("Unable to create backup prior to save: %s", exc)

                    self.tv_manager.write(payload)
            except Exception as exc:  # pylint: disable=broad-except
                self._error(str(exc), status=HTTPStatus.INTERNAL_SERVER_ERROR)
                return

            self._json_response(
                {
                    "status": "ok",
                    "details": validation_details,
                }
            )
            if backfill_episode_keys:
                self._backfill_episode_rating_keys_async()
            return

        if parsed.path == "/api/settings":
            try:
                payload = self._parse_json()
            except ValueError as exc:
                self._error(str(exc))
                return

            if isinstance(payload, dict):
                preferences_payload = payload.get("preferences")
                if isinstance(preferences_payload, dict):
                    webui_payload = preferences_payload.get("webui")
                    setup_complete_requested = (
                        isinstance(webui_payload, dict)
                        and bool(webui_payload.get("setup_complete"))
                    )
                    if setup_complete_requested:
                        options_payload = preferences_payload.get("options")
                        if not isinstance(options_payload, dict):
                            self._json_response(
                                {
                                    "valid": False,
                                    "messages": [
                                        "Cannot complete setup until source and series paths are provided."
                                    ],
                                    "fields": {
                                        "source": {
                                            "valid": False,
                                            "messages": ["This path is required."],
                                        },
                                        "series": {
                                            "valid": False,
                                            "messages": ["This path is required."],
                                        },
                                    },
                                },
                                status=HTTPStatus.BAD_REQUEST,
                            )
                            return

                        path_validation = self._validate_preferences_paths_payload(
                            {
                                "source": options_payload.get("source"),
                                "series": options_payload.get("series"),
                            }
                        )
                        if not path_validation["valid"]:
                            self._json_response(path_validation, status=HTTPStatus.BAD_REQUEST)
                            return

            try:
                updated = save_settings(payload, self.context.preference_file)
            except SettingsPersistenceError as exc:
                self._json_response(
                    {
                        "error": str(exc),
                        "remediation": exc.remediation,
                        "persisted": False,
                    },
                    status=HTTPStatus.INTERNAL_SERVER_ERROR,
                )
                return
            self._json_response(updated)
            return

        if parsed.path == "/api/validate/preferences-paths":
            try:
                payload = self._parse_json()
            except ValueError as exc:
                self._error(str(exc))
                return

            if not isinstance(payload, dict):
                self._error("Invalid payload", status=HTTPStatus.BAD_REQUEST)
                return

            result = self._validate_preferences_paths_payload(payload)
            status = HTTPStatus.OK if result["valid"] else HTTPStatus.BAD_REQUEST
            self._json_response(result, status=status)
            return

        if parsed.path == "/api/backups/restore":
            try:
                payload = self._parse_json()
            except ValueError as exc:
                self._error(str(exc))
                return

            backup_path = payload.get("path") if isinstance(payload, dict) else None
            if not backup_path:
                self._error("Missing backup path")
                return

            try:
                restored = self.tv_manager.restore_from_backup(Path(backup_path))
                config = self.tv_manager.as_payload()
            except Exception as exc:  # pylint: disable=broad-except
                self._error(str(exc), status=HTTPStatus.BAD_REQUEST)
                return

            self._json_response(
                {
                    "status": "ok",
                    "path": restored.as_posix(),
                    "config": config,
                }
            )
            return

        if parsed.path == "/api/tv/convert-legacy":
            try:
                backup_path, updated_series = self.tv_manager.backup_and_convert_legacy_keys()
                config = self.tv_manager.as_payload()
            except Exception as exc:  # pylint: disable=broad-except
                self._error(str(exc), status=HTTPStatus.BAD_REQUEST)
                return

            self._json_response(
                {
                    "status": "ok",
                    "backupPath": backup_path.as_posix(),
                    "updatedSeries": updated_series,
                    "config": config,
                }
            )
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
            preview_log = preview_logger()
            if preview_log:
                preview_log.log(
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

            preview_episode_key = payload.get("previewEpisode") or None
            preview_season = payload.get("season")
            preview_episode_number = payload.get("episode")

            if preview_episode_key == "random":
                preview_episode_key = None

            if preview_episode_key is None and preview_season is not None and preview_episode_number is not None:
                preview_episode_key = f"{preview_season}-{preview_episode_number}"

            try:
                mime, data = get_or_generate_preview(
                    self.context,
                    self.tv_manager,
                    show_name,
                    config,
                    force=True,
                    preview_episode_key=preview_episode_key,
                    prefer_existing=False,
                )
            except Exception as exc:  # pylint: disable=broad-except
                logger.exception("Unable to generate preview for %s", show_name)
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

        if parsed.path == "/api/actions/download-series-sources":
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
            logger.info("Source download requested for %s", series_name)
            logger.debug("Series config: %s", series_config)
            invalidate_preview_cache(series_name)
            self._run_manager_action(
                lambda: run_asset_downloads_for_series(
                    self.context, self.tv_manager, series_name, series_config
                ),
                context=f"download-series-sources:{series_name}",
            )
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

        if parsed.path == "/api/actions/fresh-build-series":
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
            logger.info("Fresh build requested for %s", series_name)
            logger.debug("Series config: %s", series_config)
            invalidate_preview_cache(series_name)
            self._run_manager_action(
                lambda: run_fresh_build_for_series(
                    self.context, self.tv_manager, series_name, series_config
                ),
                context=f"fresh-build-series:{series_name}",
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

        if parsed.path == "/api/actions/delete-series-cards":
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
            logger.info("Delete cards requested for %s", series_name)
            logger.debug("Series config: %s", series_config)
            self._run_manager_action(
                lambda: delete_series_cards(
                    self.context, self.tv_manager, series_name, series_config
                ),
                context=f"delete-cards:{series_name}",
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

    def _resolve_backup_path(self, raw_path: str) -> Path:
        """Clamp the requested backup browser path to the backup directory."""

        base = self.tv_manager.backup_directory().resolve(strict=False)
        base.mkdir(parents=True, exist_ok=True)
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



def _run_startup_tasks_async(context: AppContext, tv_manager: TvYamlManager) -> Thread:
    """Launch background work that should not block server startup."""

    def _task() -> None:
        try:
            tv_manager.load()
        except ValueError as exc:
            logger.warning("Skipping startup background tasks; tv.yml is invalid: %s", exc)
            return

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
            try:
                result = backfill_episode_rating_keys(context, tv_manager)
            except Exception as exc:  # pylint: disable=broad-except
                logger.warning("Unable to backfill episode rating keys on startup: %s", exc)
            else:
                updated = result.get("updated", 0)
                total = result.get("total", 0)
                if updated:
                    logger.info(
                        "Updated episode rating keys for %s of %s series", updated, total
                    )

        if static_thumbnail_cache_complete():
            logger.info("Card type thumbnail cache already prepared; skipping refresh")
        else:
            try:
                thumbnails = load_card_type_thumbnails(force=True)
            except Exception as exc:  # pylint: disable=broad-except
                logger.warning("Unable to prefetch card type thumbnails: %s", exc)
            else:
                logger.info("Prefetched %d card type thumbnails", len(thumbnails))

        _prewarm_preview_cache(context, tv_manager)

    thread = Thread(target=_task, name="startup-tasks", daemon=True)
    thread.start()
    return thread


def run(port: int = 4343) -> None:
    _configure_logging()

    context = create_app_context()
    tv_manager = TvYamlManager(context.default_tv_file)

    _run_startup_tasks_async(context, tv_manager)

    start_recent_activity_monitor(context, tv_manager)
    start_daily_tv_yaml_backup(tv_manager)

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
