import json
import shutil
import subprocess
from pathlib import Path

import pytest


APP_JS_PATH = Path(__file__).resolve().parent / "static" / "app.js"


FUNCTIONS_UNDER_TEST = [
    "normalizePreviewEpisode",
    "configuredPreviewEpisode",
    "resolvePreviewEpisode",
    "syncPreviewEpisodeConfig",
    "cloneData",
    "stableStringify",
    "snapshotEntry",
    "normalizePersistedPayload",
    "baselineFingerprintFromPayload",
    "buildCurrentNormalizedPayload",
    "persistedEntryOrderFromPayload",
    "assignPersistedBaseline",
    "currentEntryOrderForDirtyCheck",
    "computeDirtyState",
    "normalizeObjectForDiff",
    "listChangedObjectPaths",
    "collectUnsavedChangeDetails",
    "updateDirtyIndicatorDetails",
    "setDirtyState",
    "refreshDirtyState",
    "fetchPersistedConfigFingerprint",
    "reconcilePersistedBaselineFingerprint",
    "hashString",
    "saveConfiguration",
    "normalizeHideSeasonsValue",
    "hideSeasonsSelect",
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
        pytest.skip("node is required for app.js dirty-state harness")

    app_js_source = APP_JS_PATH.read_text(encoding="utf-8")
    extracted = "\n\n".join(_extract_function(app_js_source, name) for name in FUNCTIONS_UNDER_TEST)

    harness = f"""
    const state = {{
      libraries: {{}},
      entries: [],
      persistedBaselineFingerprint: null,
      persistedBaselinePayload: null,
      persistedBaselineEntryOrder: [],
      isDirty: false,
    }};
    const dom = {{
      dirtyIndicator: {{
        hidden: true,
        title: '',
        ariaLabel: '',
        setAttribute(name, value) {{
          if (name === 'aria-label') {{
            this.ariaLabel = value;
          }} else {{
            this[name] = value;
          }}
        }},
        removeAttribute(name) {{
          if (name === 'title') {{
            this.title = '';
          }}
          if (name === 'aria-label') {{
            this.ariaLabel = '';
          }}
        }},
      }},
      runBuilder: {{ disabled: false, title: '' }},
    }};

    let saveInProgress = false;
    let persistedFingerprintPollInFlight = false;

    const calls = {{
      toasts: [],
      savePanels: [],
      setSaveButtonState: [],
    }};

    const hasHardValidationErrors = () => false;
    const setSaveButtonState = (flag) => calls.setSaveButtonState.push(Boolean(flag));
    const showToast = (message, level) => {{
      calls.toasts.push({{ message, level }});
      return {{ remove() {{}} }};
    }};
    const sortEntries = () => {{}};
    const renderEntries = () => {{}};
    const normalizeSaveDetails = () => ({{
      requestedEntriesCount: state.entries.length,
      savedEntriesCount: state.entries.length,
      validationWarnings: [],
      failedEntries: [],
      hasFailures: false,
      hasWarnings: false,
      timestamp: Math.floor(Date.now() / 1000),
    }});
    const summarizeSave = () => 'Saved';
    const formatSaveTimestamp = () => 'now';
    const renderSaveStatusPanel = (payload) => calls.savePanels.push(payload);
    const markOnboardingStepComplete = () => {{}};
    const loadConfiguration = async () => {{}};

    {extracted}

    async function runScenario() {{
      {scenario_js}
    }}

    runScenario()
      .then((result) => {{
        console.log(JSON.stringify(result));
      }})
      .catch((error) => {{
        console.error(error && error.stack ? error.stack : String(error));
        process.exit(1);
      }});
    """

    completed = subprocess.run(
      [node, "-e", harness],
      check=True,
      capture_output=True,
      text=True,
    )
    output = completed.stdout.strip().splitlines()[-1]
    return json.loads(output)


def test_initial_load_from_api_config_starts_clean():
    result = _run_js_scenario(
        """
        const payload = {
          libraries: { 'TV Shows': '/mnt/tv' },
          series: [{ name: 'Example Show', config: { card_type: 'standard' } }],
        };
        payload.fingerprint = baselineFingerprintFromPayload(payload);
        state.libraries = payload.libraries;
        state.entries = payload.series.map((entry) => ({ name: entry.name, config: { ...entry.config } }));
        assignPersistedBaseline(payload, payload.fingerprint);
        refreshDirtyState();
        return {
          isDirty: state.isDirty,
          dirtyHidden: dom.dirtyIndicator.hidden,
          dirtyTitle: dom.dirtyIndicator.title,
        };
        """
    )

    assert result["isDirty"] is False
    assert result["dirtyHidden"] is True


def test_save_success_without_additional_edits_clears_dirty_state():
    result = _run_js_scenario(
        """
        const payload = {
          fingerprint: 'remote-before',
          libraries: { 'TV Shows': '/mnt/tv' },
          series: [{ name: 'Example Show', config: { card_type: 'standard' } }],
        };
        state.libraries = payload.libraries;
        state.entries = payload.series.map((entry) => ({ name: entry.name, config: { ...entry.config } }));
        assignPersistedBaseline(payload, payload.fingerprint);

        state.entries[0].config.card_type = 'banner';
        refreshDirtyState();
        const dirtyBeforeSave = state.isDirty;

        const persistedAfterSave = buildCurrentNormalizedPayload();
        assignPersistedBaseline(persistedAfterSave, baselineFingerprintFromPayload(persistedAfterSave));
        refreshDirtyState();

        return {
          dirtyBeforeSave,
          dirtyAfterSave: state.isDirty,
          dirtyHiddenAfterSave: dom.dirtyIndicator.hidden,
        };
        """
    )

    assert result["dirtyBeforeSave"] is True
    assert result["dirtyAfterSave"] is False
    assert result["dirtyHiddenAfterSave"] is True


def test_user_edit_after_load_marks_dirty():
    result = _run_js_scenario(
        """
        const payload = {
          fingerprint: 'remote-abc',
          libraries: { 'TV Shows': '/mnt/tv' },
          series: [{ name: 'Example Show', config: { card_type: 'standard' } }],
        };
        state.libraries = payload.libraries;
        state.entries = payload.series.map((entry) => ({ name: entry.name, config: { ...entry.config } }));
        assignPersistedBaseline(payload, payload.fingerprint);
        refreshDirtyState();

        state.entries[0].config.card_type = 'landscape';
        refreshDirtyState();

        return {
          isDirty: state.isDirty,
          dirtyHidden: dom.dirtyIndicator.hidden,
          dirtyTitle: dom.dirtyIndicator.title,
        };
        """
    )

    assert result["isDirty"] is True
    assert result["dirtyHidden"] is False
    assert "Example Show: card_type" in result["dirtyTitle"]


def test_fingerprint_match_stays_clean_even_if_entry_order_cache_drifts():
    result = _run_js_scenario(
        """
        const payload = {
          fingerprint: 'remote-abc',
          libraries: { 'TV Shows': '/mnt/tv' },
          series: [{ name: 'Example Show', config: { card_type: 'standard' } }],
        };
        state.libraries = payload.libraries;
        state.entries = payload.series.map((entry) => ({ name: entry.name, config: { ...entry.config } }));
        assignPersistedBaseline(payload, payload.fingerprint);
        state.persistedBaselineEntryOrder = ['0:Drifted Name'];
        refreshDirtyState();

        return {
          isDirty: state.isDirty,
          dirtyHidden: dom.dirtyIndicator.hidden,
        };
        """
    )

    assert result["isDirty"] is False
    assert result["dirtyHidden"] is True


def test_external_persisted_fingerprint_change_reconciles_dirty_state():
    result = _run_js_scenario(
        """
        const payload = {
          fingerprint: 'remote-v1',
          libraries: { 'TV Shows': '/mnt/tv' },
          series: [{ name: 'Example Show', config: { card_type: 'standard' } }],
        };
        state.libraries = payload.libraries;
        state.entries = payload.series.map((entry) => ({ name: entry.name, config: { ...entry.config } }));
        assignPersistedBaseline(payload, payload.fingerprint);

        state.entries[0].config.card_type = 'striped';
        refreshDirtyState();
        const dirtyBeforeExternalChange = state.isDirty;

        const remoteMatchingFingerprint = baselineFingerprintFromPayload(buildCurrentNormalizedPayload());
        globalThis.fetch = async () => ({
          ok: true,
          json: async () => ({ fingerprint: remoteMatchingFingerprint }),
        });

        await reconcilePersistedBaselineFingerprint();

        return {
          dirtyBeforeExternalChange,
          dirtyAfterExternalChange: state.isDirty,
          dirtyHiddenAfterExternalChange: dom.dirtyIndicator.hidden,
        };
        """
    )

    assert result["dirtyBeforeExternalChange"] is True
    assert result["dirtyAfterExternalChange"] is False
    assert result["dirtyHiddenAfterExternalChange"] is True


def test_hide_seasons_select_does_not_mark_entry_dirty_when_value_missing():
    result = _run_js_scenario(
        """
        globalThis.document = {
          createElement: () => ({
            options: [],
            appendChild(option) { this.options.push(option); },
            addEventListener() {},
          }),
        };

        const payload = {
          libraries: { 'TV Shows': '/mnt/tv' },
          series: [{ name: 'Example Show', config: { card_type: 'standard' } }],
        };
        state.libraries = payload.libraries;
        state.entries = payload.series.map((entry) => ({ name: entry.name, config: { ...entry.config } }));
        assignPersistedBaseline(payload, baselineFingerprintFromPayload(payload));
        refreshDirtyState();

        const field = { id: 'hide_seasons', path: ['hide_seasons'] };
        hideSeasonsSelect(state.entries[0], field, undefined);

        return {
          isDirty: state.isDirty,
          hasHideSeasons: Object.prototype.hasOwnProperty.call(
            state.entries[0].config,
            'hide_seasons'
          ),
        };
        """
    )

    assert result["isDirty"] is False
    assert result["hasHideSeasons"] is False


def test_hide_seasons_select_defaults_to_false_when_value_missing():
    result = _run_js_scenario(
        """
        globalThis.document = {
          createElement: () => ({
            options: [],
            appendChild(option) { this.options.push(option); },
            addEventListener() {},
          }),
        };

        const entry = { name: 'Example Show', config: { card_type: 'standard' } };
        const field = { id: 'seasons.hide', path: ['seasons', 'hide'] };
        const select = hideSeasonsSelect(entry, field, undefined);
        const selected = select.options.find((option) => option.selected)?.value || null;

        return { selected };
        """
    )

    assert result["selected"] == "false"


def test_normalization_parity_preview_episode_keys_do_not_trigger_dirty():
    result = _run_js_scenario(
        """
        const baselinePayload = {
          libraries: { 'TV Shows': '/mnt/tv' },
          series: [{ name: 'Example Show', config: { card_type: 'standard', previewEpisode: '1-03' } }],
        };
        baselinePayload.fingerprint = baselineFingerprintFromPayload(baselinePayload);
        state.libraries = baselinePayload.libraries;
        state.entries = [{
          name: 'Example Show',
          config: { card_type: 'standard', preview_episode: '1-03' },
        }];

        assignPersistedBaseline(baselinePayload, baselinePayload.fingerprint);
        refreshDirtyState();

        return {
          isDirty: state.isDirty,
          dirtyHidden: dom.dirtyIndicator.hidden,
        };
        """
    )

    assert result["isDirty"] is False
    assert result["dirtyHidden"] is True



def test_dirty_indicator_tooltip_clears_after_reverting_changes():
    result = _run_js_scenario(
        """
        const payload = {
          fingerprint: 'remote-v1',
          libraries: { 'TV Shows': '/mnt/tv' },
          series: [{ name: 'Example Show', config: { card_type: 'standard' } }],
        };
        state.libraries = payload.libraries;
        state.entries = payload.series.map((entry) => ({ name: entry.name, config: { ...entry.config } }));
        assignPersistedBaseline(payload, payload.fingerprint);

        state.entries[0].config.card_type = 'banner';
        refreshDirtyState();
        const dirtyTitle = dom.dirtyIndicator.title;

        state.entries[0].config.card_type = 'standard';
        refreshDirtyState();

        return {
          dirtyTitle,
          cleanTitle: dom.dirtyIndicator.title,
          cleanAria: dom.dirtyIndicator.ariaLabel,
          isDirty: state.isDirty,
        };
        """
    )

    assert "Example Show: card_type" in result["dirtyTitle"]
    assert result["cleanTitle"] == ""
    assert result["cleanAria"] == ""
    assert result["isDirty"] is False

def test_save_error_does_not_reset_dirty_baseline():
    result = _run_js_scenario(
        """
        const payload = {
          fingerprint: 'remote-v1',
          libraries: { 'TV Shows': '/mnt/tv' },
          series: [{ name: 'Example Show', config: { card_type: 'standard' } }],
        };
        state.libraries = payload.libraries;
        state.entries = payload.series.map((entry) => ({ name: entry.name, config: { ...entry.config } }));
        assignPersistedBaseline(payload, payload.fingerprint);

        state.entries[0].config.card_type = 'banner';
        refreshDirtyState();

        const baselineBeforeSave = state.persistedBaselineFingerprint;
        globalThis.fetch = async () => ({
          ok: false,
          json: async () => ({ error: 'save failed' }),
        });

        await saveConfiguration();

        return {
          baselineBeforeSave,
          baselineAfterFailedSave: state.persistedBaselineFingerprint,
          isDirtyAfterFailedSave: state.isDirty,
          dirtyHiddenAfterFailedSave: dom.dirtyIndicator.hidden,
        };
        """
    )

    assert result["baselineAfterFailedSave"] == result["baselineBeforeSave"]
    assert result["isDirtyAfterFailedSave"] is True
    assert result["dirtyHiddenAfterFailedSave"] is False
