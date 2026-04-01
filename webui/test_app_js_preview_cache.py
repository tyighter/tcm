import json
import shutil
import subprocess
from pathlib import Path

import pytest


APP_JS_PATH = Path(__file__).resolve().parent / "static" / "app.js"


def _node_path():
    return shutil.which("node")


def test_app_js_syntax():
    """Ensure the UI bundle still parses."""
    node = _node_path()
    if not node:
        pytest.skip("node is required for syntax check")
    subprocess.run([node, "--check", str(APP_JS_PATH)], check=True)


def test_restore_cached_preview_executes():
    """Ensure previewUrlForEntry builds the correct static preview URL."""
    node = _node_path()
    if not node:
        pytest.skip("node is required for preview URL harness")

    app_js_source = APP_JS_PATH.read_text(encoding="utf-8")
    sentinel = "function previewUrlForEntry(entry"
    start = app_js_source.find(sentinel)
    assert start != -1, "previewUrlForEntry definition not found"
    signature_end = app_js_source.find(") {", start)
    assert signature_end != -1, "previewUrlForEntry signature malformed"
    body_start = app_js_source.find("{", signature_end)
    assert body_start != -1, "previewUrlForEntry body not found"
    brace_count = 0
    end = None
    for index in range(body_start, len(app_js_source)):
        char = app_js_source[index]
        if char == "{":
            brace_count += 1
        elif char == "}":
            brace_count -= 1
            if brace_count == 0:
                end = index
                break
    assert end is not None, "could not isolate previewUrlForEntry body"
    preview_function = app_js_source[start : end + 1]

    harness = f"""
    {preview_function}
    const resolveEntrySlug = (entry) => entry.slug || entry.name;
    const resolvePreviewEpisode = (entry) => entry.previewEpisode || "random";
    const previewSeasonForEntry = () => 2;
    const url = previewUrlForEntry({{ name: "Series", slug: "series", previewEpisode: "1-03" }});
    const params = new URLSearchParams(url.split("?")[1]);
    console.log(JSON.stringify(Object.fromEntries(params.entries())));
    """

    completed = subprocess.run(
        [node, "-e", harness],
        check=True,
        capture_output=True,
        text=True,
    )
    output = completed.stdout.strip().splitlines()[-1]
    data = json.loads(output)
    assert data["slug"] == "series"
    assert data["name"] == "Series"
    assert data["previewEpisode"] == "1-03"
    assert data["season"] == "2"


def test_request_entry_previews_queues_all_entries():
    """Ensure preview requests enqueue each entry for progressive loading."""
    node = _node_path()
    if not node:
        pytest.skip("node is required for preview request harness")

    app_js_source = APP_JS_PATH.read_text(encoding="utf-8")
    sentinel = "function requestEntryPreviews(entries = state.entries) {"
    start = app_js_source.find(sentinel)
    assert start != -1, "requestEntryPreviews definition not found"
    body_start = app_js_source.find("{", start)
    assert body_start != -1, "requestEntryPreviews body not found"
    brace_count = 0
    end = None
    for index in range(body_start, len(app_js_source)):
        char = app_js_source[index]
        if char == "{":
            brace_count += 1
        elif char == "}":
            brace_count -= 1
            if brace_count == 0:
                end = index
                break
    assert end is not None, "could not isolate requestEntryPreviews body"
    function_source = app_js_source[start : end + 1]

    harness = f"""
    {function_source}
    const queued = [];
    const state = {{ entries: [] }};
    const queueEntryPreview = (entry) => queued.push(entry.id);
    requestEntryPreviews([{{ id: "a" }}, {{ id: "b" }}, {{ id: "c" }}]);
    console.log(JSON.stringify(queued));
    """

    completed = subprocess.run(
        [node, "-e", harness],
        check=True,
        capture_output=True,
        text=True,
    )
    output = completed.stdout.strip().splitlines()[-1]
    data = json.loads(output)
    assert data == ["a", "b", "c"]


def test_building_state_toggles_preview_action_control():
    """Ensure renderEntry removes title indicator and swaps build button for building chip."""
    app_js_source = APP_JS_PATH.read_text(encoding="utf-8")

    assert "const building = isSeriesBuilding(entry.name);" in app_js_source
    assert "const buildIndicator = document.createElement('span');" not in app_js_source
    assert "buildIndicator.className = 'entry-build-indicator';" not in app_js_source
    assert "titleRow.append(titleContainer);" in app_js_source
    assert "titleRow.append(titleContainer, buildIndicator);" not in app_js_source
    assert "if (building) {" in app_js_source
    assert "buildChip.className = 'entry-build-chip';" in app_js_source
    assert "buildChip.setAttribute('aria-live', 'polite');" in app_js_source
    assert "<span>Building cards</span>" in app_js_source
    assert "previewActions.append(buildChip, manageButton);" in app_js_source
    assert "previewActions.append(buildButton, manageButton);" in app_js_source


def test_wizard_preview_refresh_skips_save_configuration():
    """Ensure new-entry wizard preview regeneration does not persist on each tweak."""
    app_js_source = APP_JS_PATH.read_text(encoding="utf-8")

    wizard_start = app_js_source.find("function openNewEntryWizard(entry) {")
    assert wizard_start != -1, "openNewEntryWizard definition not found"
    add_modal_start = app_js_source.find("function openAddEntryModal()", wizard_start)
    assert add_modal_start != -1, "openAddEntryModal boundary not found"
    wizard_source = app_js_source[wizard_start:add_modal_start]

    assert "const src = await fetchPreviewDataUrl(entry);" in wizard_source
    assert "await saveConfiguration();\n      const src = await fetchPreviewDataUrl(entry);" not in wizard_source


def test_wizard_preview_loading_state_feedback_present():
    """Ensure wizard preview refresh shows explicit loading progress and disables actions."""
    app_js_source = APP_JS_PATH.read_text(encoding="utf-8")

    wizard_start = app_js_source.find("function openNewEntryWizard(entry) {")
    assert wizard_start != -1, "openNewEntryWizard definition not found"
    add_modal_start = app_js_source.find("function openAddEntryModal()", wizard_start)
    assert add_modal_start != -1, "openAddEntryModal boundary not found"
    wizard_source = app_js_source[wizard_start:add_modal_start]

    assert "wizardActionButtons.forEach((button) => {" in wizard_source
    assert "button.disabled = isLoading;" in wizard_source
    assert "entry-build-indicator__spinner" in wizard_source
    assert "Generating preview…" in wizard_source
