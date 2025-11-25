#!/bin/bash

set -euo pipefail

PUID=${PUID:-99}
PGID=${PGID:-100}
UMASK=${UMASK:-002}

umask "$UMASK"

groupmod -o -g "$PGID" titlecardmaker
usermod -o -u "$PUID" titlecardmaker

mkdir -p /config

for config_dir in source fonts thumbnails; do
  mkdir -p "/config/${config_dir}"
done

# Ensure the Tautulli log starts fresh on each container start.
rm -f /config/tautulli.log

if [ ! -d "/config/thumbnails" ] && [ -d "/maker/config/thumbnails" ]; then
  cp -r "/maker/config/thumbnails" /config/
fi

default_files=(
  preferences.yml
  tv.yml
)

for default_file in "${default_files[@]}"; do
  if [ ! -e "/config/${default_file}" ] && [ -e "/maker/config/${default_file}" ]; then
    cp "/maker/config/${default_file}" "/config/${default_file}"
  fi
done

python3 - <<'PY'
from webui.card_type_images import bake_card_type_thumbnails

try:
    baked = bake_card_type_thumbnails(force=True)
    print(f"Prepared {len(baked)} card type thumbnails for the Web UI cache.")
except Exception as exc:  # pylint: disable=broad-except
    print(f"Warning: unable to prepare card type thumbnails: {exc}")
PY

if [ "$#" -eq 0 ]; then
  set -- python3 main.py --run --no-color
fi

lower_webui=${TCM_WEBUI:-true}
lower_webui=${lower_webui,,}
case "$lower_webui" in
  0|false|no|off)
    ;;
  1|true|yes|on)
    webui_port=${TCM_WEBUI_PORT:-4343}
    if ! [[ "$webui_port" =~ ^[0-9]+$ ]]; then
      echo "Invalid TCM_WEBUI_PORT value '$webui_port', defaulting to 4343" >&2
      webui_port=4343
    fi
    set -- python3 -c "from webui.server import run; run(port=${webui_port})"
    ;;
  *)
    echo "Invalid TCM_WEBUI value '${TCM_WEBUI:-}' provided, defaulting to enabled" >&2
    webui_port=${TCM_WEBUI_PORT:-4343}
    if ! [[ "$webui_port" =~ ^[0-9]+$ ]]; then
      echo "Invalid TCM_WEBUI_PORT value '$webui_port', defaulting to 4343" >&2
      webui_port=4343
    fi
    set -- python3 -c "from webui.server import run; run(port=${webui_port})"
    ;;
esac

chown -R titlecardmaker:titlecardmaker /maker /config

exec runuser -u titlecardmaker -g titlecardmaker -- "$@"

