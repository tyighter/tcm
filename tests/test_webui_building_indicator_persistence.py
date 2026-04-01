import json
import shutil
import subprocess
from pathlib import Path

import pytest


APP_JS_PATH = Path(__file__).resolve().parents[1] / 'webui' / 'static' / 'app.js'

FUNCTIONS_UNDER_TEST = [
    'normalizeBuildingSeriesName',
    'pruneStaleBuildingSeries',
    'persistBuildingSeriesState',
    'loadBuildingSeriesState',
    'setSeriesBuildingState',
    'isSeriesBuilding',
    'moveBuildingSeriesState',
]


def _node_path():
    return shutil.which('node')


def _extract_function(source: str, name: str) -> str:
    sentinels = [f'async function {name}(', f'function {name}(']
    start = -1
    for sentinel in sentinels:
        start = source.find(sentinel)
        if start != -1:
            break
    assert start != -1, f'{name} definition not found'
    body_start = source.find('{', start)
    assert body_start != -1, f'{name} body not found'
    brace_count = 0
    end = None
    for index in range(body_start, len(source)):
        char = source[index]
        if char == '{':
            brace_count += 1
        elif char == '}':
            brace_count -= 1
            if brace_count == 0:
                end = index
                break
    assert end is not None, f'could not isolate {name} body'
    return source[start : end + 1]


def _run_js_scenario(scenario_js: str) -> dict:
    node = _node_path()
    if not node:
        pytest.skip('node is required for building-indicator harness')

    app_js_source = APP_JS_PATH.read_text(encoding='utf-8')
    constants = []
    for name in ('BUILDING_SERIES_STORAGE_KEY', 'BUILDING_SERIES_MAX_AGE_MS'):
        marker = f'const {name} ='
        start = app_js_source.find(marker)
        assert start != -1, f'{name} constant not found'
        end = app_js_source.find(';', start)
        assert end != -1, f'{name} semicolon not found'
        constants.append(app_js_source[start : end + 1])

    extracted = '\n\n'.join(_extract_function(app_js_source, name) for name in FUNCTIONS_UNDER_TEST)

    harness = f"""
    const state = {{ buildingSeries: {{}} }};
    const storage = new Map();
    const localStorage = {{
      getItem(key) {{
        return storage.has(key) ? storage.get(key) : null;
      }},
      setItem(key, value) {{
        storage.set(key, String(value));
      }},
    }};

    {''.join(constants)}

    {extracted}

    function getStoredSeries() {{
      const payload = localStorage.getItem(BUILDING_SERIES_STORAGE_KEY);
      return payload ? JSON.parse(payload) : {{}};
    }}

    function runScenario() {{
      {scenario_js}
    }}

    const result = runScenario();
    console.log(JSON.stringify(result));
    """

    completed = subprocess.run(
        [node, '-e', harness],
        check=True,
        capture_output=True,
        text=True,
    )
    output = completed.stdout.strip().splitlines()[-1]
    return json.loads(output)


def test_building_state_is_persisted_and_case_normalized():
    result = _run_js_scenario(
        """
        setSeriesBuildingState(' Example Show ', true);
        return {
          inMemory: state.buildingSeries,
          stored: getStoredSeries(),
          isBuilding: isSeriesBuilding('example show'),
        };
        """
    )

    assert 'example show' in result['inMemory']
    assert 'example show' in result['stored']
    assert result['isBuilding'] is True


def test_stale_building_state_is_pruned_on_load():
    result = _run_js_scenario(
        """
        const staleTime = Date.now() - BUILDING_SERIES_MAX_AGE_MS - 1000;
        localStorage.setItem(
          BUILDING_SERIES_STORAGE_KEY,
          JSON.stringify({ 'old show': staleTime, 'new show': Date.now() })
        );
        loadBuildingSeriesState();
        return {
          inMemory: state.buildingSeries,
          oldBuilding: isSeriesBuilding('old show'),
          newBuilding: isSeriesBuilding('new show'),
        };
        """
    )

    assert 'old show' not in result['inMemory']
    assert result['oldBuilding'] is False
    assert result['newBuilding'] is True


def test_building_state_moves_when_series_is_renamed():
    result = _run_js_scenario(
        """
        setSeriesBuildingState('Before Name', true);
        moveBuildingSeriesState('Before Name', 'After Name');
        return {
          before: isSeriesBuilding('Before Name'),
          after: isSeriesBuilding('After Name'),
          keys: Object.keys(state.buildingSeries),
        };
        """
    )

    assert result['before'] is False
    assert result['after'] is True
    assert result['keys'] == ['after name']
