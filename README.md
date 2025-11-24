# TitleCardMaker

TitleCardMaker is a Python 3.11 tool for creating and managing custom title cards for personal media libraries. It supports fully automated card generation for Plex, Jellyfin, and Emby, plus a built-in Web UI for interactive workflows.

> The project currently ships with the new Web UI enabled by default in Docker images. The classic CLI remains available for automation-heavy setups.

## Features
- **Automated pipelines**: Pull series and episode metadata from Plex, Jellyfin/Emby, Sonarr, or The Movie Database and render cards on a schedule (`main.py --run`).
- **Web UI**: Start the bundled server to review sources, preview cards, and trigger jobs without the CLI (`TCM_WEBUI=true`, port `4343` by default).
- **Spoiler-aware rendering**: Combine watch status with downloaded artwork to produce blurred/unblurred cards automatically.
- **Extensible card types**: Dozens of built-in templates plus optional community card packs from the companion `TitleCardMaker-CardTypes` repository.
- **Mini maker utilities**: Use `mini_maker.py` to generate collection posters, genre cards, or movie/season artwork on demand.
- **Docker-first**: Containers include ImageMagick and seed default configuration files so you can start with no manual host setup.

## Requirements
- Python 3.11+ with ImageMagick available on your `PATH` (Docker users get this preinstalled).
- Dependencies from `Pipfile` / `Pipfile.lock` (install with `pipenv install`).

## Getting Started
### Docker
The official image runs as a non-root user and seeds `/config/preferences.yml` and `/config/tv.yml` on first start. A minimal `docker-compose.yml` looks like:

```yaml
services:
  titlecardmaker:
    image: collinheist/titlecardmaker:latest
    container_name: titlecardmaker
    environment:
      PUID: 99
      PGID: 100
      UMASK: 002
      TCM_WEBUI: true          # set to false/no/0 to disable the Web UI
      TCM_WEBUI_PORT: 4343     # optional override
    volumes:
      - /path/to/config:/config
      - /path/to/titlecardmaker/source:/config/source
    ports:
      - "4343:4343"
    restart: unless-stopped
```

### Local development
```bash
pipenv install
pipenv run python main.py --run --no-color
```
Use `--preferences` to point at a custom preferences file and `--missing` to write missing assets to a separate path. Command-line options mirror the environment variables documented in `start.sh`.

## Usage
- **Web UI**: Starts automatically in Docker unless `TCM_WEBUI` is disabled. The server runs from `webui.server` and listens on `TCM_WEBUI_PORT`.
- **CLI / scheduler**: `main.py` accepts scheduling flags such as `--runtime` and `--frequency` and supports watch-status updates via Tautulli input files (`--tautulli-list`).
- **Mini maker**: Run `python mini_maker.py --help` for options to produce posters and cards outside the main automation loop.

Sample configurations for preferences, TV sources, fonts, and thumbnails live in the `config/` directory. The container copies these into `/config` when they are missing so you can edit them in place.

## Support and contributions
Open issues or pull requests on GitHub, or join the community Discord. Sponsorship via GitHub Sponsors or BuyMeACoffee helps keep the project maintained.
