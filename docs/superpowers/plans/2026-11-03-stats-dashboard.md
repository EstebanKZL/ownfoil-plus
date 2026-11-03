# Stage 4 Statistics and Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Statistics as an overview (donut, ring, bars, largest files) and a finished Dashboard (notices, storage bars, linked recents), JS moved out of both templates.

**Architecture:** Move each page's inline JS to `static/js/stats.js` / `dashboard.js`, add `static/js/charts.js` with pure helpers, then rework markup and renderers section by section with existing data.

**Tech Stack:** Jinja, jQuery/vanilla JS, Bootstrap 5.3, Strawberry GraphQL, pytest.

**Spec:** `docs/superpowers/specs/2026-11-03-stats-dashboard-design.md`

## Global Constraints

- `beta/` only; never push; version unchanged; CHANGELOG under `## [Unreleased - beta]`.
- No server or schema changes; no chart libraries; one bare inline `<script>` per page; strings in `app/i18n.py` (`en` + `es`); tokens only; catalogue/path text via `textContent`/`.text()`.
- Tests from `beta/`, Python 3.13 venv, `PYTHONUTF8=1`, `tests/...` paths; commit only when the run is green.

## Review Focus

1. Empty install (no files, no downloads, no libraries): every chart/section renders an empty state, never NaN or a broken gradient. Pinned in Tasks 2-3.
2. A library path or filename with HTML/quotes: shown as text. Pinned in Tasks 3-4.
3. A file whose apps are unidentified (no title): the largest-files row shows the filename without a link. Pinned in Task 3.
4. Storage of an offline library or with unknown totals: no division by zero, shown as offline. Pinned in Task 4.
5. The verification drill-down, downloads clear and duplicate resolution still work after the move. Pinned in Task 1 (existing tests) and the browser check.

---

### Task 1: Move the JS out of `stats.html` and `dashboard.html`

Files: create `app/static/js/stats.js`, `app/static/js/dashboard.js`; modify both templates and the tests that read their JS (`grep -l "stats.html\|dashboard.html" tests/`).
- [ ] Failing test (`tests/test_stats_dashboard_page.py`): each page loads its script, has one bare inline script holding `I18N`, and the moved function names (`loadStats`, `renderTiles` / dashboard `renderTiles`, `renderStorage`) are no longer in the HTML.
- [ ] Move verbatim (keep server-fed consts and `I18N` inline; check the block for Jinja first). Run the stats/dashboard/i18n test files - PASS. Commit `Move the stats and dashboard JS to static/js`.

### Task 2: Chart helpers

Files: create `app/static/js/charts.js`; tests.
Produces: `percent(part, total) -> number` (0 when total is 0, one decimal), `donutGradient(segments, colors) -> string` (`conic-gradient(color a deg b deg, ...)`; empty or zero total → `conic-gradient(var(--op-surface-2) 0deg 360deg)`), `ringGradient(pct, color) -> string`, `CHART_COLORS` (token list).
- [ ] Failing tests: run the helpers under a tiny JS evaluator? No JS runtime in tests - assert the source contracts instead: `percent` guards `!total`; `donutGradient` returns the neutral ring on empty/zero; segment angles accumulate (`acc +=`); last segment ends at 360. Also a Python port check is not needed.
- [ ] Implement; both pages load `charts.js` before their own script. Commit `Chart helpers for stats and dashboard`.

### Task 3: Statistics page

Files: `stats.html`, `stats.js`, `style.css`, `i18n.py`, tests.
Produces: `.page-head`; `#statTiles` with four `.stat-tile`s; sections `#statsFormats` (donut + legend), `#statsLibraries` (bars, drill-down kept), `#statsVerification` (ring + rows, modal kept), `#statsTypes` (bars), `#statsLargest` (`LARGEST_FILES_QUERY`, rows link `/game/<titleId>` when known); downloads and duplicates wrapped in `.surface` sections; empty states per section.
- [ ] Failing tests: markup ids; `LARGEST_FILES_QUERY` extracted from `stats.js` runs as admin on the shop fixture with sizes descending; renderers use `textContent`/`.text(`; empty states exist; i18n keys.
- [ ] Implement; PASS with stats tests. Commit `Statistics: overview with charts and largest files`.

### Task 4: Dashboard

Files: `dashboard.html`, `dashboard.js`, `style.css`, `i18n.py`, tests.
Produces: `renderAlerts` → `.dash-notice.dash-notice--{warning|danger|info}`; `storageTone(freePct) -> 'ok'|'wait'|'danger'` (thresholds 15 and 5); `renderStorage` bars (offline/unknown handled); recent rows as links to `/game/<title_id>` when present; one GraphQL request for icons of the visible title ids (`titles(owned:true, filter...)` or per-id `title` aliases, max 20); status chips as `.status-badge`.
- [ ] Failing tests: `storageTone` thresholds in source; notices classes; recent link pattern; icons in one request; offline storage branch; i18n keys.
- [ ] Implement; PASS with dashboard tests. Commit `Dashboard: notices, storage bars and linked recents`.

### Task 5: Docs

CHANGELOG stage 4 part (why), Usage `## Stats page` and `## Dashboard` updated. Run `tests/test_branding.py`. Commit.

### Task 6: Verification

- [ ] Full suite in the background on the final commit.
- [ ] Browser (restart beta killing workers): stats and dashboard at 1440 and 375, dark/light, three styles; drill-downs, downloads selector, duplicates; fix findings RED→GREEN.
- [ ] Final whole-branch review.
