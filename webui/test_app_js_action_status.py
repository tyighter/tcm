import json
import shutil
import subprocess
from pathlib import Path

import pytest


APP_JS_PATH = Path(__file__).resolve().parent / "static" / "app.js"
FUNCTIONS_UNDER_TEST = [
    "normalizeBuildingSeriesName",
    "pruneStaleBuildingSeries",
    "persistBuildingSeriesState",
    "rebuildBuildingSeriesFromActionContexts",
    "applyServerActionStatus",
]


def _node_path():
    return shutil.which("node")


def _extract_function(source: str, name: str) -> str:
    sentinels = [f"async function {name}(", f"function {name}("]
    start = -1
    for sentinel in sentinels:
        start = source.find(sentinel)
        if start != -1:
            break
    assert start != -1, f"{name} definition not found"
    body_start = source.find("{", start)
    assert body_start != -1, f"{name} body not found"
    brace_count = 0
    end = None
    for index in range(body_start, len(source)):
        char = source[index]
        if char == "{":
            brace_count += 1
        elif char == "}":
            brace_count -= 1
            if brace_count == 0:
                end = index
                break
    assert end is not None, f"could not isolate {name} body"
    return source[start : end + 1]


def _run_js_scenario(scenario_js: str) -> dict:
    node = _node_path()
    if not node:
        pytest.skip("node is required for app.js action status harness")

    app_js_source = APP_JS_PATH.read_text(encoding="utf-8")
    extracted = "\n\n".join(_extract_function(app_js_source, name) for name in FUNCTIONS_UNDER_TEST)

    harness = f"""
    const BUILDING_SERIES_STORAGE_KEY = 'tcm-building-series';
    const BUILDING_SERIES_MAX_AGE_MS = 1000 * 60 * 60 * 6;
    const storage = new Map();
    const state = {{ buildingSeries: {{}} }};
    const localStorage = {{
      getItem(key) {{
        return storage.has(key) ? storage.get(key) : null;
      }},
      setItem(key, value) {{
        storage.set(key, String(value));
      }},
      removeItem(key) {{
        storage.delete(key);
      }},
    }};
    let renderCount = 0;
    function renderEntries() {{
      renderCount += 1;
    }}

    {extracted}

    function getStoredBuildingSeries() {{
      const raw = localStorage.getItem(BUILDING_SERIES_STORAGE_KEY);
      return raw ? JSON.parse(raw) : null;
    }}

    function runScenario() {{
      {scenario_js}
    }}

    const result = runScenario();
    console.log(JSON.stringify(result));
    """

    completed = subprocess.run(
        [node, "-e", harness],
        check=True,
        capture_output=True,
        text=True,
    )
    output = completed.stdout.strip().splitlines()[-1]
    return json.loads(output)


def test_apply_server_action_status_clears_stale_building_state():
    result = _run_js_scenario(
        """
        state.buildingSeries = { 'demo show': Date.now() - 1000 };
        persistBuildingSeriesState();
        applyServerActionStatus({ contexts: [] });
        return {
          state: state.buildingSeries,
          stored: getStoredBuildingSeries(),
          renderCount,
        };
        """
    )

    assert result["state"] == {}
    assert result["stored"] == {}
    assert result["renderCount"] == 1


def test_apply_server_action_status_rebuilds_from_active_series_contexts():
    result = _run_js_scenario(
        """
        applyServerActionStatus({
          contexts: [
            { context: 'build-series:Demo Show' },
            { context: 'fresh-build-series:Other Show' },
            { context: 'metadata-sync' },
          ],
        });
        return {
          keys: Object.keys(state.buildingSeries).sort(),
          renderCount,
        };
        """
    )

    assert result["keys"] == ["demo show", "other show"]
    assert result["renderCount"] == 1
