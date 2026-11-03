# Stage 5a - Files, Tasks and Services pages

Status: design proposed in conversation on 2026-11-03 (stage 5 split in two: 5a these
pages, 5b Settings), pending review of this written spec.
Branch: local `beta` worktree, on top of stages 1-4.

## Goal

Bring the Files (`/admin/files`), Tasks (`/admin/tasks`) and Services
(`/admin/services`) pages into the stage 1 design language, and move their inline
JavaScript out of the templates (pending item 1). Every behavior stays: Files' tabs,
filters, chips, paging, drawer, actions (verify, organize, delete, duplicate and
outdated resolution, bulk removal), watched tasks; Tasks' live queue over the
realtime socket, scheduled, failed (retry/purge), history (clear), workers; Services'
discovery toggle.

Success: the three pages share the look of the Dashboard and Statistics; a file
leads to its game page; running tasks read at a glance; the templates hold markup and
strings only.

## 1. Files

- `.page-head` (icon `bi-file-earmark`, the current heading and description, refresh
  button kept).
- The six state tiles (`#filesTiles`, `.files-tile`) keep their markup, ids and
  behavior and take the `.stat-tile` look: a tone per state (all `--nav`, unidentified
  `--wait`, verification `--ok` or `--danger` when something failed, duplicates and
  outdated `--wait`, pending `--nav`), the active tile outlined in `--op-nav`.
- The `--files-*` palette (semantic tones of the page) maps onto the tokens
  (`--op-ok`, `--op-wait`, `--op-danger`, `--op-nav`) for both modes, so the page
  follows the style; the per-tone backgrounds become `rgba(var(--op-*-rgb), .12)`.
- Toolbar, chips, table and the drawer use `.surface` / tokens (radii, borders,
  hover in `--op-nav`), no Bootstrap literal colors.
- An identified file's drawer gets an "Open game page" link to `/game/<titleId>`
  (the base title id of its first app).

## 2. Tasks

- `.page-head` (icon `bi-list-task`, title, a one-line description).
- Queue, Scheduled, Failed and History each a `.surface` section with the current
  header buttons.
- A running task's progress bar uses `--op-nav`; a failed task row is marked with
  `--op-danger`; scheduled rows with `--op-wait`.
- Workers: the cards keep their content in `.surface` cards with a status dot
  (busy `--op-nav`, idle `--op-ok`, offline `--op-text-muted`).

## 3. Services

- `.page-head` (icon `bi-broadcast`); the discovery section as a `.surface`.

## 4. Code structure

- `templates/files.html`, `tasks.html`, `services.html` keep one bare inline
  `<script>` each with their server values and strings; the logic moves to
  `static/js/files.js`, `tasks.js`, `services.js`. Tests that read JS from those
  templates read the files.
- New strings in `app/i18n.py` (`en` + `es`), styles under "Admin pages (stage 5a)" in
  `style.css`, tokens only. No server or schema changes.

## Out of scope

Settings (stage 5b). New Files/Tasks features.

## Testing

- JS moved: existing Files/Tasks/Services tests pass, updated only where they read JS
  from the template; one bare inline script per page.
- New: `.page-head` on the three pages; tile tones and active state in CSS; the
  `--files-*` palette defined through tokens (no hex literals); drawer game link built
  from the title id and only for identified files; tasks progress/failed/scheduled
  tones; worker status dots; i18n keys in both languages.
- Browser: the three pages at 1440 and 375, dark/light, three styles; Files tabs,
  drawer, a filter chip; Tasks live updates while a task runs.
