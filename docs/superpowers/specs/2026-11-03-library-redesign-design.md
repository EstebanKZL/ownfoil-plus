# Stage 2 - Library page redesign

Status: scope approved in conversation on 2026-11-03, pending review of this written spec.
Branch: local `beta` worktree, on top of stage 1 (design tokens, styles, navigation).

## Goal

Give the Library (`/`, `templates/index.html`), the most used page, the stage 1 design
language: a page header with the library at a glance, one toolbar, one-click filters
with counts, and new game cards. Nothing the page does today stops working: the three
views (cards, icons, list), paging, search (including `?q=` from Ctrl+K), every filter,
the metadata modal (view and admin edit), downloads, remembered preferences, and the
shop-user vs admin differences.

Success: a person sees how the library is doing (games, pending updates, missing DLC,
size, % up to date) without opening anything; the most common filters are one click and
show how many games they will return; sorting by name or release date is possible; the
page looks like the Dashboard of stage 1 in every style and mode, on desktop and phone.

## 1. Header and summary

- `.page-head`: icon `bi-grid`, title "Library", a count badge with the number of owned
  games, and a one-line description.
- Four `.stat-tile`s from the existing `stats` GraphQL query (`ownedTitles`,
  `upToDateTitles`, `completeTitles`, `totalFiles`, `totalSize`):

  | Tile | Value | Tone |
  |---|---|---|
  | Games | `ownedTitles` | `--ok` |
  | Pending updates | `ownedTitles - upToDateTitles` | `--wait` |
  | Missing DLC | `ownedTitles - completeTitles` | `--nav` |
  | Total size | `formatBytes(totalSize)` | `--action`, admins only (shown when `totalFiles > 0`, which is already 0 for non-admins) |

  Clicking "Pending updates" or "Missing DLC" applies the matching filter (section 3).
- A progress bar "Games up to date: 55% (10 / 18)" (`upToDateTitles / ownedTitles`).
- With no owned games (empty install, or a visitor whose stats read zero) the tiles and
  bar are not shown, as the current stats line is not shown today.
- These count games (titles); the grid counts cards (base games and DLC) - labels make
  that clear ("games" vs the pill counts, which follow the grid).

## 2. Toolbar

One `.toolbar` block replacing today's row of separate buttons:

- Search input (with a search icon), same debounce, same `localStorage['searchTerm']`
  and `?q=` behavior as today.
- Sort: a select with **Name** and **Release date**, plus a direction toggle
  (ascending / descending). Sent as `orderBy: {field: NAME|RELEASE_DATE, direction:
  ASC|DESC}` on the `apps` (cards, icons) and `titles` (list) queries, which already
  accept it. Default Name ascending, as today. Remembered in
  `localStorage['librarySort']` (`{field, direction}`, validated on read).
  Not offered: "recently added" - `ADDED_AT` only applies to the `files` query.
- View toggle: cards / icons / list (same three views, same `localStorage['currentView']`).
- A **View** menu holding "Items per page" (9, 12, 18, 27, custom) and the card size
  slider (cards and icons only), instead of two separate controls.
- A **Filters** button (section 3) with a dot when any filter inside it is active.

## 3. Filter pills

A row of `.filter-pill`s under the toolbar, each with a count.

Cards and icons views:

| Pill | Sets | Count |
|---|---|---|
| All | update = none, completion = none | grid total with those two cleared |
| Update pending | update = Outdated | grid total with `upToDate: false` |
| Missing DLC | completion = Missing DLC | grid total with `complete: false` |
| Up to date | update = Up to date | grid total with `upToDate: true` |

List view (its own filter, `libraryHealth`, as today): All, Complete, Incomplete,
Corrupt, Repack - counts from `titles(owned: true, libraryHealth: X) { total }`.

- Counts come from one GraphQL request with aliases (`all: apps(...) { total }`,
  `outdated: apps(..., upToDate: false) { total }`, ...), built from the same variables
  as the grid (search, type, ownership) minus the dimension each pill sets, so a count
  is exactly what clicking the pill returns. Refreshed with the grid when search or
  the Filters menu change; not on paging.
- A pill is active when the current update/completion (or health) state equals what it
  sets; a combination no pill represents (e.g. Complete, set in the Filters menu)
  leaves none active.
- The **Filters** menu keeps every current filter group: type (all / base / DLC),
  ownership (all / owned / missing), update, completion - and in list view the health
  group. Pills and menu are two views of the same state, persisted in
  `localStorage['activeFilters']` exactly as today.
- On phones the pill row scrolls sideways instead of wrapping.

## 4. Game cards

- Cards and icon tiles use the `.surface` look: 16 px radius, thin border, the cover
  art on top, name and "publisher · year" under it, hover lift with an accent border
  (no lift under `prefers-reduced-motion`).
- `.status-badge`s on the card for its state, each with its fixed color: update
  available (`--wait`), missing DLC (`--dlc`), complete and up to date (`--ok`). DLC
  cards show a "DLC" badge. Not-owned cards are dimmed with a "Missing" badge, as today.
- The existing metadata (details) and download buttons keep their behavior.
- List view keeps its layout (cover, banner strip, collapsible Updates/DLC sections,
  download buttons) and adopts the tokens, radii and badges.
- Phones: cards view uses 2 columns; the card size slider is hidden there.

## 5. Empty and loading states

- No results: `.empty-state` with "No games match these filters" and a **Clear
  filters** button (resets search, pills and the Filters menu). An empty library (no
  owned games at all, no filters): an empty state pointing admins to Settings > Library
  paths, and to Upload files on the Dashboard.
- A failed query shows an inline error with a Retry button instead of an empty grid.

## 6. Code structure

- The page's JavaScript (about 1,300 lines) moves from `index.html` to
  `app/static/js/library.js`. `index.html` keeps one bare inline `<script>` with the
  server-fed constants (`IS_ADMIN`, `IS_SHOP`, `WEB_DOWNLOADS_ENABLED`,
  `SHOW_GAME_BACKGROUND_IMAGE`) and the `I18N` object, then loads `library.js`.
- The GraphQL query strings move with it; tests that read them from `index.html`
  (`test_card_icon_metadata_query.py`, `test_library_list_view_query.py`, others found
  while implementing) read `library.js` instead.
- No server or GraphQL changes are needed.

## 7. i18n

Every new string in `app/i18n.py`, `en` and `es` (voseo): header description, tile
labels, progress label, sort labels, View/Filters labels, pill labels, empty states,
error and retry.

## Out of scope

The title page (stage 3), statistics and dashboard details (stage 4), the admin pages
(stage 5), and new features from SLMW: favorites, wishlist, recommendations.

## Testing

- Moving the JS: the existing library tests pass, updated only where they read the
  query strings from the template.
- New tests: header, tiles and progress bar markup; toolbar holds search, sort, view,
  View menu and Filters; sort select offers exactly NAME and RELEASE_DATE and the
  queries take `$orderBy`; stored sort is validated; pill markup and the count query
  shape (aliases, one request) for both filter sets; the shipped count query runs
  against the real GraphQL schema and its totals equal the grid query's totals for each
  pill on the fixture library; empty state and Clear filters exist; card markup uses
  `.surface` and status badges; i18n keys exist in both languages; still one bare
  inline script.
- Browser: desktop and 375 px, light and dark, the three styles, admin and shopper;
  each view; a pill, the Filters menu, sorting, paging, search, `?q=`, the metadata
  modal and a download in list view.
