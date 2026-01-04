from __future__ import annotations

import subprocess
import textwrap


def test_preview_cache_timestamps_normalized_to_milliseconds():
    script = textwrap.dedent(
        """
        const fs = require('fs');
        const vm = require('vm');

        const source = fs.readFileSync('webui/static/app.js', 'utf8');

        const maxAgeMatch = source.match(/const PREVIEW_CACHE_MAX_AGE_MS =[^;]+;/);

        const normalizeStart = source.indexOf('function normalizeTimestamp');
        const isExpiredStart = source.indexOf('function isPreviewCacheExpired');
        const loadLegacyStart = source.indexOf('function loadLegacyPreviewCache');

        const snippets = [
          maxAgeMatch?.[0],
          normalizeStart >= 0 && isExpiredStart > normalizeStart
            ? source.slice(normalizeStart, isExpiredStart).trim()
            : null,
          isExpiredStart >= 0 && loadLegacyStart > isExpiredStart
            ? source.slice(isExpiredStart, loadLegacyStart).trim()
            : null,
        ];

        if (snippets.some((part) => !part)) {
          throw new Error('Required cache helpers were not found in app.js');
        }

        const snippet = `
          ${snippets.join('\\n')}
          module.exports = { PREVIEW_CACHE_MAX_AGE_MS, normalizeTimestamp, isPreviewCacheExpired };
        `;

        const context = { module: { exports: {} } };
        vm.createContext(context);
        vm.runInContext(snippet, context);

        const {
          PREVIEW_CACHE_MAX_AGE_MS,
          normalizeTimestamp,
          isPreviewCacheExpired,
        } = context.module.exports;

        const nowMs = Date.now();
        const recentSeconds = Math.floor(nowMs / 1000);

        if (normalizeTimestamp(recentSeconds) !== recentSeconds * 1000) {
          throw new Error('Seconds-based timestamps should convert to milliseconds.');
        }

        if (isPreviewCacheExpired(recentSeconds)) {
          throw new Error('Seconds-based timestamps should be treated as fresh after normalization.');
        }

        const stillFreshMs = nowMs - PREVIEW_CACHE_MAX_AGE_MS + 5000;
        if (isPreviewCacheExpired(stillFreshMs)) {
          throw new Error('Millisecond timestamps inside max age should stay fresh.');
        }

        const expiredSeconds = Math.floor(
          (nowMs - PREVIEW_CACHE_MAX_AGE_MS - 5000) / 1000
        );
        if (!isPreviewCacheExpired(expiredSeconds)) {
          throw new Error(
            'Expired seconds-based timestamps should still be stale after normalization.'
          );
        }
        """
    )

    result = subprocess.run(
        ["node", "-e", script],
        check=False,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
