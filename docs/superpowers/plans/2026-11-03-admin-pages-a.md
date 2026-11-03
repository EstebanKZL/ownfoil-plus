# Stage 5a Files, Tasks and Services Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Files, Tasks and Services in the stage 1 design language, with their JS moved to `static/js/`.

**Architecture:** First move each page's inline JS verbatim (keeping the server-fed string blocks inline), then restyle markup and CSS page by page; behavior is untouched except the drawer's new game link.

**Tech Stack:** Jinja, vanilla JS/jQuery, Bootstrap 5.3, pytest.

**Spec:** `docs/superpowers/specs/2026-11-03-admin-pages-a-design.md`

## Global Constraints

- `beta/` only; never push; version unchanged; CHANGELOG under `## [Unreleased - beta]`.
- No server or schema changes; one bare inline `<script>` per page; strings in `app/i18n.py` (`en` + `es`); tokens only; text via `textContent`.
- Tests from `beta/`, Python 3.13 venv, `PYTHONUTF8=1`, `tests/...` paths; commit only on a green run.

## Review Focus

1. The Files drawer link for a file with no apps, or whose apps carry no title id: no link, never `/game/undefined`. Pinned in Task 3.
2. Every element id the moved JS queries still exists after the markup changes (tiles, toolbar, table, drawer, task lists, worker cards). Pinned in Tasks 1-4 (existing tests) and a scripted id check in Task 5.
3. Light mode: the Files tones (formerly literal pastel pairs) keep readable text on their backgrounds. Pinned in Task 3 (tokens, no literals) and the browser check.
4. Tasks page live updates (realtime socket) and the nav counter keep working after the move. Pinned by existing tests and the browser check.
5. Phone (375 px): no horizontal overflow on the three pages. Browser check.

---

### Task 1: Move the JS of files, tasks and services
- [ ] Failing test (`tests/test_admin_pages.py`): each page loads `static/js/<page>.js`, has one bare inline script, and named functions (`files`: `fileRow`, `openDrawer`, `paintTiles`; `tasks`: `scheduleRender`, `markDone`; `services`: the discovery submit handler name) are in the file, not the page.
- [ ] Move verbatim, the inline block keeping everything up to the last Jinja expression (files: through line ~264; tasks: through ~99; services: none). Update tests that read JS from the templates. Commit `Move the files, tasks and services JS to static/js`.

### Task 2: Page headers and section surfaces
- [ ] Failing tests: `.page-head` on the three pages; Tasks' sections and Services' section are `.surface`.
- [ ] Implement markup (keep every id and button); i18n keys for new descriptions. Commit `Admin pages: headers and surfaces`.

### Task 3: Files look and drawer game link
- [ ] Failing tests: `--files-*` variables defined with `var(--op-...)` only (no hex in those blocks); `.files-tile` tone and `.active` rules use tokens; drawer code builds `/game/${...}` only when a title id exists.
- [ ] Implement CSS mapping and the drawer link (`files.open_game` string). Commit `Files: tokens, tile tones and a link to the game page`.

### Task 4: Tasks tones and workers
- [ ] Failing tests: CSS rules for `.task-progress .progress-bar` (`--op-nav`), failed (`--op-danger`) and scheduled (`--op-wait`) rows; worker cards `.surface` with a status dot class per state in the JS.
- [ ] Implement. Commit `Tasks: progress, state tones and worker cards`.

### Task 5: Docs and verification
- [ ] CHANGELOG stage 5a part; Usage Files/Tasks lines if behavior visibly changed (drawer link).
- [ ] Scripted check: every `getElementById('x')` / `$('#x')` id in the three JS files exists in its template (or is created by the JS).
- [ ] Full suite in the background; browser (restart beta killing workers) at 1440 and 375, dark/light, three styles; fix findings RED→GREEN; final whole-branch review.
