# Stage 5b Settings Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Settings in the stage 1 design language - page head, twelve sections as cards, a sticky index with scrollspy (chips on the phone) - with its JS moved to `static/js/settings.js`.

**Architecture:** First move the inline JS verbatim, turning the few Jinja expressions inside it into `I18N` entries and server values. Then one Jinja list of sections drives both the index and every section heading; markup changes keep every id. The index behavior (smooth scroll, scrollspy, hash) lives in `settings.js`.

**Tech Stack:** Jinja, vanilla JS/jQuery, Bootstrap 5.3, IntersectionObserver, pytest.

**Spec:** `docs/superpowers/specs/2026-11-03-settings-page-design.md`

## Global Constraints

- `beta/` only; never push; version unchanged; CHANGELOG under `## [Unreleased - beta]`.
- No server, route or schema changes; one bare inline `<script>` per page; strings in `app/i18n.py` (`en` + `es`, voseo); tokens only; LF endings.
- Section order and ids exactly: `Authentication, Library, Titles, Media, Shop, Scheduler, Maintenance, Notifications, Workers, Appearance, Backup, Danger`.
- Tests from `beta/`, Python 3.13 venv, `PYTHONUTF8=1`, `tests/...` paths; commit only on a green run.

## Review Focus

1. The page with no admin account yet: the "new user" checkboxes are still forced on and disabled after the move (the old `{% if %}` block). Pinned in Task 1.
2. Deep links to a control inside a section (`#shopHostInput`, `#consoleKeysInputLabel`, Files' `#<control>` links) land visible, below the top bar and the phone chips. Pinned in Task 3 (`scroll-margin-top` on targets) and the browser check.
3. Every element id `settings.js` queries still exists after the markup rewrite (users table, modals, notification channels, backups list). Pinned in Task 2 (id check) and kept green through Task 3.
4. A browser without IntersectionObserver or with reduced motion: links still jump, nothing throws. Pinned in Task 4 (guarded, `behavior` chosen from the media query).
5. Phone 375px: the chip row scrolls sideways inside itself, the page doesn't. Pinned in Task 4 (CSS) and the browser check.

---

### Task 1: Move the settings JS to `static/js/settings.js`

**Files:** Create `app/static/js/settings.js`; modify `app/templates/settings.html` (script block, lines ~933-2306), `app/i18n.py` (no new keys - reuse `backup.import_*`); tests `tests/test_admin_pages.py`, and every test that asserts JS text from the settings page (`test_settings_i18n.py`, `test_settings_backup.py`, `test_worker_settings.py`, `test_appearance.py`, `test_shop_name_and_discovery.py`, `test_library_background_image_toggle.py`, others found by running the suite).

**Interfaces:** Produces the globals `I18N` (adds `importNoFile`, `importSuccess`, `importFailed`), `ADMIN_ACCOUNT_CREATED` (bool) inline; `<script type="application/json" id="settingsLanguages">` holding `languages_from_titledb`. `settings.js` reads the languages with `JSON.parse(document.getElementById('settingsLanguages').textContent)`.

- [ ] Failing tests in `tests/test_admin_pages.py`:
  - `test_settings_js_lives_in_a_static_file`: the page loads `/static/js/settings.js` after its one bare inline script; `function scanLibrary` is in `settings.js`, not in the page.
  - `test_settings_js_has_no_jinja`: `{{` and `{%` absent from `settings.js`.
  - `test_settings_server_values_are_data`: the page has `id="settingsLanguages"` with `type="application/json"` and `const ADMIN_ACCOUNT_CREATED =`; `settings.js` contains `if (!ADMIN_ACCOUNT_CREATED)`.
  - `test_no_admin_yet_forces_the_new_user_access_boxes`: the three ids `checkboxNewUserAdminAccess`, `checkboxNewUserShopAccess`, `checkboxNewUserBackupAccess` appear inside the `if (!ADMIN_ACCOUNT_CREATED)` block of `settings.js`.
- [ ] Run them: FAIL.
- [ ] Move everything after the `I18N` object verbatim into `settings.js` (via a scratchpad script writing with `newline=''`); replace the four inline `{{ t('backup.import_*') }}` with `I18N.importNoFile` / `importSuccess` / `importFailed`; replace the `languages = {{ ... }}` line and the `{% if %}` block as above.
- [ ] Update the tests that read JS from the page to read the page plus `settings.js`. Run the settings-related test files: PASS. Commit `Move the settings JS to static/js/settings.js`.

### Task 2: One section list, the page head and section cards

**Files:** `app/templates/settings.html` (markup lines 1-932), `app/i18n.py`, `app/static/style.css`, `tests/test_admin_pages.py`.

**Interfaces:** Produces the Jinja list `SETTINGS_SECTIONS` of `(id, title_key, icon)` tuples in the spec's order, and the macro `section_title(id)` rendering `<h2 class="admin-section__title"><i class="bi {icon}" aria-hidden="true"></i> {title}</h2>`. Each section is `<section class="surface admin-section settings-section" id="{id}">`. New keys `settings.page_desc` ("Everything your server does, section by section." / "Todo lo que hace tu servidor, sección por sección.") and `settings.index_label` ("On this page" / "En esta página").

- [ ] Failing tests:
  - `test_settings_has_a_page_head`: `.page-head` with `bi-gear` and the settings title.
  - `test_settings_sections_are_cards_in_order`: the `id`s of `<section class="surface admin-section settings-section" id="...">` in page order equal the twelve ids.
  - `test_settings_has_no_hr_separators`: no `hr-settings` in the page.
  - `test_danger_zone_is_marked`: `id="Danger"` section has class `settings-section--danger`; CSS rule `.settings-section--danger` uses `var(--op-danger)`.
  - Add `("/admin/settings", "settings.js")` to `test_every_id_the_script_queries_exists`.
  - `test_links_into_settings_still_land`: for each `/admin/settings#X` found in `templates/*.html` and `static/js/*.js` (literal ids only, skip Jinja), `id="X"` exists in the page.
- [ ] Run: FAIL.
- [ ] Rewrite the markup: alerts unchanged above `.page-head`; wrap each section; old `<h2 id>` ids move to the `<section>`; old `h3/h4/h5` sub-headings become `<h3 class="settings-subhead">`; notification channel `card`s use `settings-inner surface-2` styling (tokens). Keep every other id. CSS under "Settings (stage 5b)".
- [ ] Run the settings test files and `test_admin_pages.py`: PASS. Commit `Settings: page head and section cards`.

### Task 3: The index (markup and CSS)

**Files:** `app/templates/settings.html`, `app/static/style.css`, `tests/test_admin_pages.py`, `tests/test_mobile_layout.py` if it pins settings layout.

**Interfaces:** Produces `<div class="settings-layout">` containing `<nav class="settings-index" id="settingsIndex" aria-label="{settings.index_label}">` with one `<a class="settings-index__link" href="#{id}" data-section="{id}">` per entry (icon + title, from `SETTINGS_SECTIONS`), and `<div class="settings-sections">` with the cards.

- [ ] Failing tests:
  - `test_settings_index_lists_every_section`: links' `href`s in order equal `#` + the twelve ids, each with its icon.
  - `test_settings_index_is_sticky_and_becomes_chips`: CSS `.settings-index` has `position: sticky`; a `@media (max-width: 991.98px)` block gives it `overflow-x: auto` and `white-space: nowrap` (or `flex-wrap: nowrap`); `.settings-layout` is a grid only from `992px`.
  - `test_anchor_targets_clear_the_sticky_bars`: `.settings-section` and `.settings-section [id]` have `scroll-margin-top`.
- [ ] Run: FAIL. Implement. Run: PASS. Commit `Settings: section index`.

### Task 4: Index behavior - smooth scroll, scrollspy, hash

**Files:** `app/static/js/settings.js`, `tests/test_admin_pages.py`.

**Interfaces:** Produces in `settings.js` `function initSettingsIndex()` called on DOM ready, and `function setActiveSection(id)` (toggles `.active` + `aria-current="true"` on `[data-section=id]`, and on the phone scrolls that chip into view with `chip.parentElement.scrollTo({left: ...})` - never `scrollIntoView`, which would move the page).

- [ ] Failing tests (string-level on `settings.js`):
  - `test_index_click_scrolls_and_replaces_the_hash`: `history.replaceState` and `scrollIntoView` used in `initSettingsIndex`; `prefers-reduced-motion` decides `'smooth'` vs `'auto'`.
  - `test_scrollspy_is_guarded`: `IntersectionObserver` used only behind `'IntersectionObserver' in window`.
  - `test_arriving_hash_marks_its_section`: `initSettingsIndex` reads `location.hash` and resolves a control id to its section with `.closest('.settings-section')`.
  - `test_active_chip_scrolls_its_row_not_the_page`: `setActiveSection` body has no `scrollIntoView`.
- [ ] Run: FAIL. Implement. Run: PASS. Commit `Settings: index follows the scroll`.

### Task 5: Docs and verification

- [ ] CHANGELOG stage 5b section under `## [Unreleased - beta]` (why: one long page with no way around; JS split done). Commit.
- [ ] Full suite in the background; browser (restart beta killing workers): 1440 and 375, light/dark, three styles; index follows the scroll; save in Authentication (add a test user), Titles, Notifications, Appearance; deep links `#Maintenance`, `#shopHostInput`, `#Danger`; no horizontal overflow. Fix findings RED→GREEN.
- [ ] Final whole-branch review (opus) on the stage range; fix Critical/Important RED→GREEN.
