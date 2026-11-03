# Stage 4 - Statistics and Dashboard

Status: design approved in conversation on 2026-11-03, pending review of this written spec.
Branch: local `beta` worktree, on top of stages 1-3.

## Goal

Turn the Statistics page (`/admin/stats`) from tables into a readable overview, in the
stage 1 design language and inspired by SLMW's statistics page, and finish the
Dashboard (`/admin`) the same way. Every number and action the pages have today stays
(including the verification drill-down modal, downloads history and its clear action,
duplicates and their resolution).

Success: an admin sees at a glance how much space each format and library takes, how
much of the library is verified, what they own of each content type, which files are
largest, and how downloads go; on the Dashboard, alerts read as notices, storage as
bars, and recent items lead to their game page.

## 1. Statistics

All data comes from what the page already loads (the `stats` GraphQL query, the
downloads API, the duplicates query), plus one existing query for the largest files.

- **Header**: `.page-head` (icon `bi-bar-chart`, title, one-line description, refresh
  button kept).
- **Four main tiles** (`.stat-tile`): Games (`ownedTitles`; note "N complete · N up to
  date"), Files (`totalFiles`; note identified count), Total size (`totalSize`),
  Unidentified (`unidentifiedFiles`, tone `--wait`; links to `/admin/files` filtered to
  unidentified when that filter exists, else `/admin/files`).
- **Space by format**: a donut (`conic-gradient`, segments from `filesByExtension`
  sizes) with the total in the middle and a legend: format, file count, size, percent.
  Segment colors from a fixed token sequence (`--op-nav`, `--op-action`, `--op-wait`,
  `--op-ok`, `--op-fav`, muted for the rest).
- **Space by library**: one horizontal bar per `filesByLibrary` entry (path, count,
  size, percent of total). Clicking a library keeps today's drill-down.
- **Verification**: a ring with the percent of files whose status is VALID or
  SIGNATURE_OK, and a list per status (fixed meaning colors: valid/signature ok green,
  repack and modified amber, corrupt/signature failed red, unverified muted) with
  count and size; clicking a status opens today's files modal. The "Verify now" button
  stays.
- **Content by type**: per `appsByType` entry (base, update, DLC) a bar of owned /
  total with the numbers.
- **Largest files**: top 10 from `files(orderBy: {field: SIZE, direction: DESC},
  pageSize: 10) { items { id filename size apps { appType title { titleId name } } } }`
  (admin-only query, the page is admin-only); each row links to its game page.
- **Downloads**: the same tiles, chart and tables in `.surface` blocks; chart bars in
  `--op-nav` with a `title` per bar (day, count); the days selector and clear button
  kept.
- **Duplicates**: the same controls and actions; each group a `.surface` card.
- Every section is a `.surface` with a titled header (`.stats-section`), in a
  responsive grid (two columns from 992px, one below).

## 2. Dashboard

Data stays `/api/dashboard` (+ its existing calls).

- **Alerts**: `.dash-notice` rows with a tone per alert kind (warning amber, danger
  red, info cyan), icon, text and a chevron link, replacing Bootstrap list-group colors.
- **Storage**: one bar per library: used vs free, `--op-ok` normally, `--op-wait` below
  15 % free, `--op-danger` below 5 % free; offline libraries shown as such.
- **Recently added / Latest downloads**: rows with the game's icon when known (from a
  GraphQL lookup of the visible title ids, one request), name, detail line and time;
  rows with a `title_id` link to `/game/<title_id>`.
- **Status**: the chips become `.status-badge`s with the right tone.
- Header and tiles: already stage 1.

## 3. Code structure

- The inline JS of `stats.html` moves to `app/static/js/stats.js`, and the dashboard's
  to `app/static/js/dashboard.js`; each template keeps one bare inline `<script>` with
  its server values and `I18N`. Tests that read JS from those templates read the files.
- Chart helpers (donut and ring as `conic-gradient` strings, percent bars) in
  `app/static/js/charts.js`, used by both pages.
- Styles in `style.css` under "Statistics and Dashboard (stage 4)", tokens only.
- New strings in `app/i18n.py`, `en` and `es`.
- No server or schema changes.

## Out of scope

SLMW's year review and time-to-beat (they need new data); the admin pages' redesign
(stage 5).

## Testing

- JS moved: existing stats/dashboard tests pass, updated only where they read JS from
  the template; one bare inline script per page.
- New: chart helper output (`donutGradient` segments sum to 360deg, empty input gives a
  neutral ring; `percent` handles 0 totals); stats page markup (header, four tiles,
  the new sections); the largest-files query extracted from `stats.js` runs against the
  real schema as admin and returns ordered sizes; dashboard notices/storage tones by
  thresholds; recent rows link to `/game/<id>`; i18n keys in both languages; tokens-only
  CSS.
- Browser: desktop and 375 px, dark/light, the three styles; verification drill-down,
  downloads days selector, a duplicate group, storage bar tones.
