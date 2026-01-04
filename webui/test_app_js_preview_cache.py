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
    """Run restoreCachedPreview with minimal stubs to confirm it executes."""
    node = _node_path()
    if not node:
        pytest.skip("node is required for preview cache harness")

    app_js_source = APP_JS_PATH.read_text(encoding="utf-8")
    sentinel = "async function restoreCachedPreview(entry) {"
    start = app_js_source.find(sentinel)
    assert start != -1, "restoreCachedPreview definition not found"
    brace_count = 0
    end = None
    for index in range(start, len(app_js_source)):
        char = app_js_source[index]
        if char == "{":
            brace_count += 1
        elif char == "}":
            brace_count -= 1
            if brace_count == 0:
                end = index
                break
    assert end is not None, "could not isolate restoreCachedPreview body"
    restore_function = app_js_source[start : end + 1]

    harness = f"""
    {restore_function}
    const events = [];
    const calls = [];
    const previewCacheKey = async () => "key";
    const legacyPreviewCacheKey = () => "legacy";
    const serializeEntrySnapshot = () => "snap";
    const normalizeSnapshot = (value) => value;
    const normalizePreviewCacheValue = (key, value) => value;
    const readPreviewCacheEntry = async (key) => {{
      if (key === "key") {{
        return {{ key: "key", src: "img", snapshot: "snap", cachedAt: Date.now() - 1000 }};
      }}
      return null;
    }};
    const logPreviewCacheEvent = async (type, entry, extra) => events.push({{ type, extra }});
    const isPreviewCacheExpired = () => false;
    const applyPreviewCacheState = () => calls.push("apply");
    const writePreviewCacheEntry = async () => calls.push("write");
    const persistLegacyPreviewCache = () => calls.push("persist");
    const entry = {{ name: "Series", previewSrc: null }};

    restoreCachedPreview(entry)
      .then(() => {{
        console.log(JSON.stringify({{
          previewSrc: entry.previewSrc,
          previewStale: entry.previewStale,
          events,
          calls,
        }}));
      }})
      .catch((error) => {{
        console.error(error);
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
    data = json.loads(output)
    assert data["previewSrc"] == "img"
    assert data["previewStale"] is False
    assert any(event["type"] == "cache-hit" for event in data["events"])
