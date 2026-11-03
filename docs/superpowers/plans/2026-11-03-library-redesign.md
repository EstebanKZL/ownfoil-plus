# Stage 2 Library Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Redesign the Library page (`/`) with the stage 1 design system: header with stat tiles and progress, one toolbar with sorting, filter pills with exact counts, new cards, empty/error states.

**Architecture:** The page JS moves to `app/static/js/library.js` first (pure move). Then each feature is added there and in `index.html`, using only existing GraphQL queries (`apps`, `titles`, `stats`), with aliases for the pill counts.

**Tech Stack:** Jinja, jQuery, Bootstrap 5.3, GraphQL (Strawberry), pytest.

**Spec:** `docs/superpowers/specs/2026-11-03-library-redesign-design.md`

## Global Constraints

- Work only in `beta/` on branch `beta`; never push; version unchanged; CHANGELOG under `## [Unreleased - beta]`.
- No server/GraphQL changes.
- One bare inline `<script>` in `index.html` (constants + `I18N`); logic in `static/js/library.js`.
- Every UI string in `app/i18n.py` with `en` and `es` (voseo); JS gets them through `I18N`.
- Colors only from tokens (`--op-*`); components from stage 1 (`.page-head`, `.stat-tile`, `.filter-pill`, `.toolbar`, `.surface`, `.status-badge`, `.empty-state`).
- Sort fields exactly `NAME`, `RELEASE_DATE`; directions `ASC`, `DESC`; default NAME ASC.
- `localStorage` keys kept: `activeFilters`, `searchTerm`, `currentView`, `itemsPerPage`, `cardSize`; new `librarySort`. Every read validated, every access in try/catch.
- Tests run from `beta/` with the Python 3.13 venv and `PYTHONUTF8=1`, always passing `tests/...` paths.

## Review Focus

1. A stored `librarySort` or `activeFilters` with unknown values (old version, hand edit): falls back to defaults, never a failing query. Pinned in Task 2.
2. A shopper (no file stats) and an anonymous visitor on a public shop: no size tile, no admin-only controls, counts still correct. Pinned in Task 3.
3. Pill counts equal what clicking the pill shows, with a search term and a type filter active. Pinned in Task 5 (real GraphQL run on the fixture).
4. `?q=` from Ctrl+K still filters on load and the pills/counts reflect it. Pinned in Task 5.
5. A failed GraphQL request (server down mid-session) shows the error state with Retry, not a silently stale grid. Pinned in Task 7.

---

### Task 1: Move the page JS to `static/js/library.js`

**Files:**
- Create: `app/static/js/library.js`
- Modify: `app/templates/index.html` (inline script keeps `IS_ADMIN`, `IS_SHOP`, `WEB_DOWNLOADS_ENABLED`, `SHOW_GAME_BACKGROUND_IMAGE`, `I18N`; then `<script src=".../js/library.js">`)
- Modify tests that read JS from the template: `tests/test_card_icon_metadata_query.py`, `tests/test_library_i18n.py`, `tests/test_library_background_image_toggle.py`, any other found by `grep -l "index.html\|function \|const .*_QUERY" tests/`
- Test: `tests/test_library_page.py` (new)

**Interfaces:**
- Produces: `library.js` with the same globals as today (`CARDS_QUERY`, `ICONS_QUERY`, `LIST_QUERY`, `LIBRARY_STATS_QUERY`, `loadPage()`, `queryVariables()`, `listQueryVariables()`, `updateFilter()`, `onFilterChange()`, `resetToFirstPage()`, render functions). Test helper `_library_js()` returning the file text.

- [ ] **Step 1: Write failing tests** in `tests/test_library_page.py`:

```python
def test_library_logic_lives_in_its_own_script(client):
    html = client.get("/").get_data(as_text=True)
    assert "/static/js/library.js" in html
    assert "function loadPage" not in html
    assert "const I18N = {" in html
    js = client.get("/static/js/library.js").get_data(as_text=True)
    assert "function loadPage" in js and "const CARDS_QUERY" in js

def test_library_page_has_one_bare_inline_script(client):
    html = client.get("/").get_data(as_text=True)
    assert len(re.findall(r"<script>", html)) == 1
```

(use the login/fixture pattern of `tests/test_library_i18n.py` for `client`).
- [ ] **Step 2: Run** - FAIL.
- [ ] **Step 3: Move** lines from `let itemsPerPage` to the end of the inline script into `library.js` verbatim (LF). Update the template-reading tests to read `app/static/js/library.js` for JS assertions (query extraction, `function renderMetadataEditForm`, `setTitleOverride`, `SHOW_GAME_BACKGROUND_IMAGE` usage), keeping HTML assertions on the page.
- [ ] **Step 4: Run** `tests/test_library_page.py tests/test_card_icon_metadata_query.py tests/test_library_list_view_query.py tests/test_library_i18n.py tests/test_library_background_image_toggle.py tests/test_library_view_layout_fixes.py tests/test_library_health_filter.py tests/test_ui_polish.py tests/test_list_view_banner_css.py` - PASS.
- [ ] **Step 5: Commit** `Move the library page JS to static/js/library.js`.

### Task 2: Sorting

**Files:** `app/static/js/library.js`, `app/templates/index.html`, `app/i18n.py`, `tests/test_library_page.py`

**Interfaces:**
- Produces: `let librarySort = {field: 'NAME', direction: 'ASC'}`; `loadSortFromStorage() -> void`; `SORT_FIELDS = ['NAME', 'RELEASE_DATE']`; queries take `$orderBy: OrderBy` and pass `orderBy: $orderBy`; `queryVariables()` and `listQueryVariables()` include `orderBy: librarySort`. Markup: `<select id="sortField">` with options `NAME`, `RELEASE_DATE`; `<button id="sortDirection" data-direction="ASC|DESC">`. i18n: `library.sort_label`, `library.sort_name`, `library.sort_release_date`, `library.sort_asc`, `library.sort_desc`.

- [ ] **Step 1: Failing tests:**

```python
def test_sort_controls_offer_name_and_release_date(client):
    html = client.get("/").get_data(as_text=True)
    sel = html.split('id="sortField"', 1)[1].split("</select>", 1)[0]
    assert re.findall(r'value="(\w+)"', sel) == ["NAME", "RELEASE_DATE"]
    assert 'id="sortDirection"' in html

def test_queries_take_order_by_and_stored_sort_is_validated():
    js = _library_js()
    for name in ("CARDS_QUERY", "ICONS_QUERY", "LIST_QUERY"):
        q = _extract_query(js, name)
        assert "$orderBy: OrderBy" in q and "orderBy: $orderBy" in q
    assert "SORT_FIELDS.includes(" in js and "librarySort" in js

def test_shipped_queries_sort_by_release_date(library):
    # run CARDS_QUERY and LIST_QUERY extracted from library.js against the real schema
    # with orderBy {field: RELEASE_DATE, direction: DESC}: no errors, totals unchanged
```

(`library` fixture and `_run` as in `tests/test_card_icon_metadata_query.py`.)
- [ ] **Step 2: Run** - FAIL. **Step 3: Implement**; direction button shows `bi-sort-alpha-down`/`bi-sort-alpha-up` (`bi-sort-numeric-*` for dates) with a translated title. **Step 4: Run** Task 1's test list - PASS. **Step 5: Commit** `Library: sort by name or release date`.

### Task 3: Header, stat tiles and progress

**Files:** `app/templates/index.html`, `app/static/js/library.js`, `app/static/style.css`, `app/i18n.py`, tests

**Interfaces:**
- Produces: markup `<header class="page-head">` with `#libraryCount`; `<div class="stat-grid library-tiles" id="libraryTiles" hidden>`; `<div class="library-progress" id="libraryProgress" hidden>` with `.progress` and `#libraryProgressLabel`. `renderLibraryStats(stats)` replaces the old stats line (remove `#libraryStats` and its CSS). Tiles are `<button class="stat-tile ...">` for Pending updates (`data-pill="outdated"`) and Missing DLC (`data-pill="missingDlc"`), wired in Task 5 (`applyPill(name)`). i18n: `library.title`, `library.subtitle`, `library.tile_games`, `library.tile_updates`, `library.tile_missing_dlc`, `library.tile_size`, `library.progress` (`'{pct}% ({n} / {total})'` with label "Games up to date").

- [ ] **Step 1: Failing tests:** header and `#libraryTiles`, `#libraryProgress` exist; old `id="libraryStats"` gone; `renderLibraryStats` in JS computes `ownedTitles - upToDateTitles` and `ownedTitles - completeTitles` (assert those expressions or a small JS-free check: the strings `upToDateTitles` and `completeTitles` in the function body); size tile only added when `totalFiles` (assert `if (stats.totalFiles)` guard); i18n keys exist both languages.
- [ ] **Step 2-4:** FAIL → implement (tiles hidden when `ownedTitles` is 0) → PASS. **Step 5: Commit** `Library: header, stat tiles and progress`.

### Task 4: Toolbar, View menu, Filters menu

**Files:** `app/templates/index.html`, `app/static/js/library.js`, `app/static/style.css`, `app/i18n.py`, tests (`test_library_view_layout_fixes.py`, `test_library_i18n.py` updated deliberately)

**Interfaces:**
- Produces: `<div class="toolbar library-toolbar">` containing `#textFilter` (inside `.toolbar-search` with `bi-search`), the sort controls, the view toggle buttons (`.view-toggle-btn`, `btn-outline-secondary`), `#viewMenuBtn` dropdown holding the items-per-page items and `#cardSizeRange`, and `#filtersMenuBtn` dropdown holding all existing radio groups (type, ownership, update, completion; plus health in list view, shown/hidden by view). `#filtersActiveDot` shown when any filter is set. All existing ids of inputs are kept. `updateFiltersDot() -> void`. i18n: `library.view_menu`, `library.filters_menu`, `library.card_size`.

- [ ] **Step 1: Failing tests:** toolbar contains those ids; `#filterDropdownCol`/`#listHealthFilterCol` replaced by the single `#filtersMenuBtn` (health group present with `data-view-only="list"`); the dot element exists. **Step 2-4** → PASS with Task 1's test list. **Step 5: Commit** `Library: one toolbar with View and Filters menus`.

### Task 5: Filter pills with exact counts

**Files:** `app/templates/index.html`, `app/static/js/library.js`, `app/static/style.css`, `app/i18n.py`, tests

**Interfaces:**
- Consumes: filter state from Task 4, `queryVariables()`/`listQueryVariables()`.
- Produces: `<div class="pill-row" id="libraryPills">`; `CARD_PILLS = {all: {update: '', completion: ''}, outdated: {update: 'Outdated', completion: ''}, missingDlc: {update: '', completion: 'Missing DLC'}, upToDate: {update: 'Up to date', completion: ''}}`; `LIST_PILLS = {all: '', complete: 'COMPLETE', incomplete: 'INCOMPLETE', corrupt: 'CORRUPT', repack: 'REPACK'}`; `CARD_COUNTS_QUERY` (aliases `all`, `outdated`, `missingDlc`, `upToDate` over `apps(groupByAppId: true, appType, search, owned, upToDate, complete) { total }`) and `LIST_COUNTS_QUERY` (aliases over `titles(owned: true, search, libraryHealth) { total }`); `loadPillCounts() -> Promise<void>`; `applyPill(name) -> void` (sets the radios, then `onFilterChange()`); `renderPills() -> void`. Counts reload on search/filter/view change, not on paging. i18n: `library.pill_all`, `library.pill_outdated`, `library.pill_missing_dlc`, `library.pill_up_to_date`, `library.pill_complete`, `library.pill_incomplete`, `library.pill_corrupt`, `library.pill_repack`.

- [ ] **Step 1: Failing tests:**

```python
def test_card_pill_counts_equal_the_grid_totals(library):
    js = _library_js()
    counts = _run(library, _extract_query(js, "CARD_COUNTS_QUERY"),
                  appType=["BASE", "DLC"], search=None, owned=None)
    for alias, extra in (("all", {}), ("outdated", {"upToDate": False}),
                         ("missingDlc", {"complete": False}), ("upToDate", {"upToDate": True})):
        grid = _run(library, _extract_query(js, "CARDS_QUERY"), page=1, pageSize=1,
                    appType=["BASE", "DLC"], search=None, owned=None,
                    upToDate=extra.get("upToDate"), complete=extra.get("complete"),
                    orderBy={"field": "NAME", "direction": "ASC"})
        assert counts[alias]["total"] == grid["apps"]["total"], alias

def test_card_pill_counts_follow_search_and_type(library):
    # same comparison with search="<a fixture title word>" and appType=["BASE"]

def test_list_pill_counts_equal_the_list_totals(library):
    # LIST_COUNTS_QUERY aliases vs LIST_QUERY totals for each health value

def test_pills_markup_and_query_param_search_is_used_for_counts(client):
    html = client.get("/").get_data(as_text=True)
    assert 'id="libraryPills"' in html
    js = _library_js()
    assert "function loadPillCounts" in js and "function applyPill" in js
```

- [ ] **Step 2-4** FAIL → implement (one request per refresh; `fetchSeq`-style guard against stale answers) → PASS. **Step 5: Commit** `Library: filter pills with exact counts`.

### Task 6: Cards, icons and list rows

**Files:** `app/static/js/library.js`, `app/static/style.css`, tests (`test_ui_polish.py`, `test_library_view_layout_fixes.py` updated deliberately)

**Interfaces:**
- Produces: card markup `.card.game-surface.game-card.library-card` with `<img class="card-img-top library-cover">`, `.library-card-body` holding `.game-title`, `.library-card-meta` ("publisher · year"), `.library-badges` with `.status-badge--wait` (update available), `--dlc` (missing DLC), `--ok` (complete and up to date), a plain `.status-badge` "DLC" on DLC cards; not owned: `.library-card.is-missing` + "Missing" badge. Version popover and metadata click kept. Icons: `.library-icon.surface`. List rows: tokens and radii only. Phone (< 576px): 2 card columns, slider hidden. i18n: `library.badge_update`, `library.badge_missing_dlc`, `library.badge_complete`, `library.badge_dlc`.

- [ ] **Step 1: Failing tests:** JS builds those classes (string checks in `library.js`); CSS rules exist for `.library-card`, `.library-badges`, `.library-card.is-missing` using tokens only; phone media block sets 2 columns. **Step 2-4** → PASS with Task 1's list. **Step 5: Commit** `Library: new cards, icons and list rows`.

### Task 7: Empty and error states

**Files:** `app/templates/index.html`, `app/static/js/library.js`, `app/i18n.py`, tests

**Interfaces:**
- Produces: `#libraryEmpty` (`.empty-state`, hidden) with `#clearFiltersBtn`; `#libraryEmptyLibrary` (empty library, admin text with links `/admin/settings#Library` and `/admin`); `#libraryError` with `#libraryRetryBtn`. `clearAllFilters() -> void` (radios to "all", search empty, storage updated, page 1). `loadPage()` on a thrown fetch shows `#libraryError` and hides the grid; success hides it. i18n: `library.empty_title`, `library.empty_body`, `library.clear_filters`, `library.empty_library_title`, `library.empty_library_admin`, `library.error_title`, `library.retry`.

- [ ] **Step 1: Failing tests:** markup ids exist; `loadPage`'s catch block references `libraryError`; `clearAllFilters` resets `searchTerm` and `activeFilters`; i18n keys both languages. **Step 2-4** → PASS. **Step 5: Commit** `Library: empty and error states`.

### Task 8: Docs

**Files:** `CHANGELOG.md` (extend `## [Unreleased - beta]` with a "Library" part explaining the why), `Usage.md` (`## Library view` section: header, sorting, pills, Filters/View menus).

- [ ] Write; run `tests/test_branding.py`; commit `Document the library redesign`.

### Task 9: Verification

- [ ] Full suite in the background (`tests`).
- [ ] Browser (beta on 8466, restart it to load the new code): desktop 1440 and 1024, phone 375; dark/light; Joy-Con, Neon, Ownfoil-Plus; admin and shopper; cards/icons/list; click each pill and check the grid total equals its count; sort both fields and directions; Filters menu dot; View menu; search and `?q=`; metadata modal; empty state with an impossible search; Clear filters. The fixture library is empty, so add a few test files to `beta-data` first (copy any `.nsp`/`.nsz` named `[TITLEID][v0]`) or rely on the pytest fixture totals for counts.
- [ ] Fix anything found with a test RED→GREEN, commit each.
