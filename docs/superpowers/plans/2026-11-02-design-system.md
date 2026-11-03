# Stage 1 Design System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give Ownfoil-Plus design tokens, three color styles x light/dark/auto, the Inter font, a flat top bar with counters, a phone bottom bar and shared components, with the Dashboard as the reference page.

**Architecture:** A new `tokens.css` holds every color and feeds Bootstrap's CSS variables, so existing pages restyle without edits. The style is a second axis next to the mode: the server renders the admin's `appearance.default_style` as `data-style` on `<html>`, and `theme.js` overrides it from `localStorage`. Navigation is rebuilt in `nav.html`; counters come from a small cached helper exposed by a context processor.

**Tech Stack:** Flask + Jinja, Bootstrap 5.3 (vendored), jQuery, plain CSS custom properties, pytest.

**Spec:** `docs/superpowers/specs/2026-11-02-design-system-design.md`

## Global Constraints

- Work only in `ownfoil-plus/beta/` on local branch `beta`. Never push, never touch `main`.
- Do not change the version in `pyproject.toml`. CHANGELOG goes under `## [Unreleased - beta]`.
- Style names, exactly: `ownfoil`, `neon`, `joycon`; default `joycon`. Display names: Ownfoil / Neon / Joy-Con (es: Ownfoil / Neón / Joy-Con).
- Mode values stay `light`, `dark`, `auto`; dark stays the default mode.
- Every user-facing string goes in `app/i18n.py` with `en` and `es` (voseo). No hard-coded UI text.
- One bare inline `<script>` per page (the `test_*_i18n.py` rule). Shared JS goes in `app/static/js/`.
- No CDN: Inter is vendored under `app/static/vendor/inter/`.
- No color literals outside `tokens.css` for anything this stage touches.
- Do not use SLMW's logo, name or copy. Credit it in `NOTICE.md`.
- Files with LF line endings.
- Tests: Python 3.13 venv, `PYTHONUTF8=1 python -m pytest -q -p no:cacheprovider -W ignore tests/<file>` run from `beta/` (always pass the `tests/` path).

## Review Focus

1. A browser whose `localStorage['style']` holds an unknown value (old version, typo): the server default must apply, not a page without accent colors. Pinned in Task 3.
2. `settings.yaml` with an invalid `appearance.default_style`, or no `appearance` section at all (upgrades): pages render with `joycon`. Pinned in Task 1.
3. First run (no admin account yet, empty DB) treated as admin by the nav: counters must render as zero/hidden, never a 500. Pinned in Task 4.
4. A shopper or anonymous visitor on a public shop: no admin items and no counter queries in the page. Pinned in Task 4.
5. On a phone the fixed bottom bar must not cover the last row of content or the upload modal's buttons: body gets bottom padding only when the bar is present. Pinned in Task 5.

---

### Task 1: Appearance setting (backend + Settings section)

**Files:**
- Modify: `app/constants.py` (`DEFAULT_SETTINGS`, new `APPEARANCE_STYLES`)
- Modify: `app/settings.py` (new `get_default_style`, `set_appearance_settings`)
- Modify: `app/app.py` (route `POST /api/settings/appearance`; context processor next to `inject_shop_name`)
- Modify: `app/templates/settings.html` (new `#Appearance` section + its JS in the existing inline script)
- Modify: `app/templates/nav.html` (search list entry for `#Appearance`)
- Modify: `app/i18n.py`
- Test: `tests/test_appearance.py` (new)

**Interfaces:**
- Produces: `constants.APPEARANCE_STYLES = ('ownfoil', 'neon', 'joycon')`; `DEFAULT_SETTINGS['appearance'] = {'default_style': 'joycon'}`; `settings.get_default_style() -> str` (always one of `APPEARANCE_STYLES`); `settings.set_appearance_settings(data: dict) -> None`; Jinja global `default_style` (str) on every page; i18n keys `sections.appearance`, `appearance.desc`, `appearance.default_style`, `style.ownfoil`, `style.neon`, `style.joycon`.

- [ ] **Step 1: Write the failing tests** in `tests/test_appearance.py` (reuse the `admin_client` / `shopper_client` login pattern from `tests/test_theme_search.py`):

```python
def test_default_style_is_joycon(shop_app):
    import settings
    assert settings.get_default_style() == "joycon"

def test_invalid_default_style_falls_back_to_joycon(shop_app, monkeypatch):
    import settings
    monkeypatch.setitem(settings.get_settings(), "appearance", {"default_style": "pink"})
    assert settings.get_default_style() == "joycon"

def test_missing_appearance_section_falls_back(shop_app, monkeypatch):
    import settings
    monkeypatch.delitem(settings.get_settings(), "appearance", raising=False)
    assert settings.get_default_style() == "joycon"

@pytest.mark.parametrize("style", ["ownfoil", "neon", "joycon"])
def test_admin_sets_style_and_pages_render_it(admin_client, style):
    resp = admin_client.post("/api/settings/appearance", json={"default_style": style})
    assert resp.get_json()["success"] is True
    for url in ("/", "/admin", "/login", "/offline"):
        assert f'data-style="{style}"' in admin_client.get(url).get_data(as_text=True)

def test_unknown_style_is_rejected(admin_client):
    body = admin_client.post("/api/settings/appearance", json={"default_style": "pink"}).get_json()
    assert body["success"] is False and body["errors"][0]["path"] == "appearance/default_style"

def test_shopper_cannot_change_style(shopper_client):
    assert shopper_client.post("/api/settings/appearance", json={"default_style": "neon"}).status_code in (302, 401, 403)

def test_appearance_section_and_search_entry(admin_client):
    html = admin_client.get("/admin/settings").get_data(as_text=True)
    assert 'id="Appearance"' in html
    assert "/admin/settings#Appearance" in admin_client.get("/").get_data(as_text=True)
```

- [ ] **Step 2: Run** `tests/test_appearance.py` - expected FAIL (`get_default_style` missing).
- [ ] **Step 3: Implement.** `get_default_style()` reads `get_settings().get('appearance', {}).get('default_style')` and returns it only if in `APPEARANCE_STYLES`, else `'joycon'`. Route validates like `/api/settings/maintenance`: unknown value -> `{'success': False, 'errors': [{'path': 'appearance/default_style', 'error': ...}]}`, `@access_required('admin')`. Context processor `inject_default_style` returns `{'default_style': get_default_style()}`. Settings section: `<h2 id="Appearance">`, a short `appearance.desc` paragraph, three radio cards (swatch + name) posting on change, following the existing section save pattern in `settings.html`. Search list entry: `(t('settings_nav.settings') ~ ' › ' ~ t('sections.appearance'), '/admin/settings#Appearance', 'bi-palette', 'appearance apariencia theme tema style estilo colors colores')`. The `data-style` attribute on `<html>` comes in Task 2; for this task's render test, add it to `base.html` now: `<html lang="en" data-bs-theme="dark" data-style="{{ default_style|default('joycon') }}">`, and update `tests/test_theme_search.py::test_theme_script_runs_in_head_before_the_stylesheets` to assert `'<html lang="en" data-bs-theme="dark" data-style="joycon">'`.
- [ ] **Step 4: Run** `tests/test_appearance.py tests/test_theme_search.py tests/test_settings_i18n.py tests/test_i18n.py` - expected PASS.
- [ ] **Step 5: Commit** `Add appearance.default_style setting and Settings section`.

### Task 2: Tokens, Inter and Bootstrap wiring

**Files:**
- Create: `app/static/css/tokens.css`
- Create: `app/static/vendor/inter/InterVariable.woff2`, `app/static/vendor/inter/OFL.txt`
- Modify: `app/static/vendor/README.md`, `app/templates/base.html`, `app/static/style.css`
- Test: `tests/test_design_tokens.py` (new)

**Interfaces:**
- Consumes: `data-style` on `<html>` (Task 1).
- Produces: CSS custom properties used by every later task: `--op-surface-0/1/2`, `--op-text`, `--op-text-muted`, `--op-border`, `--op-border-strong`, `--op-radius-sm` (8px), `--op-radius` (12px), `--op-radius-lg` (16px), `--op-shadow`, `--op-ease`, `--op-dur` (180ms), `--op-ok`, `--op-wait`, `--op-fav`, `--op-danger`, `--op-nav`, `--op-nav-rgb`, `--op-action`, `--op-action-rgb`, `--op-on-action` (text on action color), `--op-glow-1`, `--op-glow-2`.

- [ ] **Step 1: Write the failing tests** in `tests/test_design_tokens.py` (read `tokens.css` like `tests/test_mobile_layout.py` reads `style.css`):

```python
STYLES = ("ownfoil", "neon", "joycon")

def test_every_style_defines_its_accents_in_both_modes():
    css = _read("app/static/css/tokens.css")
    for style in STYLES:
        for mode in ("dark", "light"):
            block = _rule(css, f'[data-style="{style}"][data-bs-theme="{mode}"]')
            for var in ("--op-nav:", "--op-action:", "--op-glow-1:", "--op-glow-2:"):
                assert var in block, (style, mode, var)

def test_tokens_feed_bootstrap():
    css = _read("app/static/css/tokens.css")
    for var in ("--bs-primary:", "--bs-primary-rgb:", "--bs-body-bg:", "--bs-body-color:",
                "--bs-border-color:", "--bs-link-color:", "--bs-body-font-family:"):
        assert var in css

def test_inter_is_vendored_and_declared(shop_app):
    css = _read("app/static/css/tokens.css")
    assert "@font-face" in css and "InterVariable.woff2" in css
    assert shop_app.client.get("/static/vendor/inter/InterVariable.woff2").status_code == 200

def test_tokens_load_between_bootstrap_and_style(shop_app):
    head = shop_app.client.get("/login").get_data(as_text=True).split("</head>", 1)[0]
    assert head.index("bootstrap.min.css") < head.index("css/tokens.css") < head.index("style.css")

def test_style_css_has_no_bootstrap_blue_literal():
    assert "#0d6efd" not in _read("app/static/style.css").lower()
```

`_rule(css, selector)` returns the body of the rule whose selector list contains `selector`; write it as a small helper in the test file.

- [ ] **Step 2: Run** - expected FAIL (no `tokens.css`).
- [ ] **Step 3: Implement.** Download Inter 4.x variable (`InterVariable.woff2`) and `OFL.txt` from the official rsms/inter GitHub release into a fresh scratchpad dir, check the file, then copy it in. Values for the accents:

| style | mode | `--op-nav` | `--op-action` | `--op-on-action` |
|---|---|---|---|---|
| ownfoil | dark | `#00e5d0` | `#00b8a6` | `#0d1117` |
| ownfoil | light | `#00857a` | `#00857a` | `#ffffff` |
| neon | dark | `#ff5c6c` | `#d62839` | `#ffffff` |
| neon | light | `#c41f30` | `#c41f30` | `#ffffff` |
| joycon | dark | `#00e5d0` | `#ff4554` | `#ffffff` |
| joycon | light | `#00857a` | `#d62839` | `#ffffff` |

Semantic colors (all styles): dark `--op-ok #3fb950`, `--op-wait #f59a23`, `--op-fav #f2b51d`, `--op-danger #f85149`; light `#1a7f37`, `#9a6512`, `#b8860b`, `#cf222e`. Dark surfaces `#0d1117 / #161b22 / #1c2230`, border `#2a313c`; light keeps today's warm palette values from the existing `[data-bs-theme=light]` block in `style.css` (move them into `tokens.css`). Bootstrap mapping: `--bs-primary: var(--op-action)`, `--bs-link-color: var(--op-nav)`, `--bs-body-bg: var(--op-surface-0)`, `--bs-body-font-family: "Inter", system-ui, ...`. In `style.css` replace `#0d6efd` and the `--files-*` palette with tokens (`--files-primary: var(--op-action)`, `--files-success: var(--op-ok)`, etc.).
- [ ] **Step 4: Run** `tests/test_design_tokens.py tests/test_ui_polish.py tests/test_list_view_banner_css.py tests/test_mobile_layout.py` - expected PASS.
- [ ] **Step 5: Commit** `Add design tokens, three styles and vendored Inter`.

### Task 3: Style axis in theme.js and the theme menu

**Files:**
- Modify: `app/static/js/theme.js`, `app/templates/nav.html` (theme dropdown), `app/i18n.py`
- Test: `tests/test_theme_search.py` (extend)

**Interfaces:**
- Consumes: `data-style` from the server (Task 1), style names.
- Produces: `window.setStyle(name: 'ownfoil'|'neon'|'joycon'|null)` (`null` clears the override); `window.setTheme(mode)` unchanged; menu items `[data-style-choice="ownfoil|neon|joycon|server"]`; i18n keys `theme.mode`, `theme.style`, `theme.style_server`.

- [ ] **Step 1: Write the failing tests:**

```python
def test_theme_script_validates_style_names(shop_app):
    js = shop_app.client.get("/static/js/theme.js").get_data(as_text=True)
    assert "['ownfoil', 'neon', 'joycon']" in js
    assert "localStorage.getItem('style')" in js or 'STYLE_KEY' in js
    assert "window.setStyle" in js

def test_theme_menu_offers_three_styles_and_server_default(admin_client):
    html = admin_client.get("/").get_data(as_text=True)
    assert {"ownfoil", "neon", "joycon", "server"} <= set(re.findall(r'data-style-choice="(\w+)"', html))
```

- [ ] **Step 2: Run** - expected FAIL.
- [ ] **Step 3: Implement.** On load, remember the server value (`document.documentElement.dataset.style`) as `serverStyle`; `storedStyle()` returns the `localStorage` value only if it is in the allowed list, else `null` (Review Focus 1); apply `storedStyle() || serverStyle`. `setStyle(null)` removes the key. Mark the active menu item the same way `data-theme-choice` is marked. Menu: two headed groups (Mode, Style), each style item with a 14px swatch span using `--op-nav`/`--op-action` of that style via inline `data-style` preview classes defined in `tokens.css` (`.style-swatch[data-swatch="joycon"]`).
- [ ] **Step 4: Run** `tests/test_theme_search.py tests/test_i18n.py` - expected PASS.
- [ ] **Step 5: Commit** `Add style switcher to the theme menu`.

### Task 4: Flat top bar with counters

**Files:**
- Create: `app/nav_counts.py`
- Modify: `app/app.py` (context processor), `app/templates/nav.html`, `app/templates/settings_layout.html` (drop the sidebar), `app/static/style.css`, `app/i18n.py`
- Delete: `app/static/js/admin-nav.js` (and its `<script>` in `settings_layout.html`)
- Modify: `tests/test_mobile_layout.py` (remove `test_admin_tabs_are_one_scrollable_row_on_phones`)
- Test: `tests/test_navigation.py` (new)

**Interfaces:**
- Produces: `nav_counts.get_nav_counts() -> dict` with keys `unidentified: int`, `running_tasks: int`, cached 5 s (`time.monotonic`); `nav_counts.clear_cache() -> None` for tests. Jinja global `nav_counts` (dict) only computed when the viewer is admin, else `{}`. Element ids `navCountTasks`, `navCountFiles`; nav links carry `data-nav="library|setup|files|tasks|stats|admin"`.

- [ ] **Step 1: Write the failing tests** in `tests/test_navigation.py`:

```python
def test_admin_sees_flat_items_linking_existing_routes(admin_client):
    html = admin_client.get("/admin").get_data(as_text=True)
    for href in ('href="/admin/files"', 'href="/admin/tasks"', 'href="/admin/stats"',
                 'href="/admin/settings"', 'href="/admin/services"', 'href="/setup"'):
        assert href in html
    assert "settings-sidebar" not in html

def test_shopper_sees_no_admin_items_or_counts(shopper_client):
    html = shopper_client.get("/").get_data(as_text=True)
    assert 'href="/admin/files"' not in html and "navCountTasks" not in html
    assert 'href="/setup"' in html

def test_counts_are_zero_and_hidden_on_an_empty_library(admin_client):
    import nav_counts
    nav_counts.clear_cache()
    assert nav_counts.get_nav_counts() == {"unidentified": 0, "running_tasks": 0}
    html = admin_client.get("/admin").get_data(as_text=True)
    assert re.search(r'id="navCountTasks"[^>]*\bhidden\b', html)

def test_first_run_nav_renders(shop_app, monkeypatch):
    # No admin account yet: the nav treats the visitor as admin and must not crash.
    import app as app_mod
    monkeypatch.setattr(app_mod, "admin_account_created", lambda: False)
    resp = shop_app.client.get("/")
    assert resp.status_code == 200
    assert 'href="/admin/tasks"' in resp.get_data(as_text=True)

def test_active_item_is_marked(admin_client):
    html = admin_client.get("/admin/tasks").get_data(as_text=True)
    assert re.search(r'data-nav="tasks"[^>]*aria-current="page"', html)
```

If the shop fixture library already contains unidentified files, assert the fixture's real count instead of 0; add one unidentified `Files` row in a separate test and assert `unidentified` grows by 1 after `clear_cache()` and the `navCountFiles` badge shows the new number.

- [ ] **Step 2: Run** - expected FAIL.
- [ ] **Step 3: Implement.** `get_nav_counts()` runs `Files.query.filter(Files.identified.is_(False)).count()` and `Task.query.filter_by(status='running').count()`. Nav order and visibility per the spec's "Top bar" section; "admin" is `current_user.is_admin or admin_account_created == false`, as in today's `nav.html`. Active item: pill with `rgba(var(--op-nav-rgb), .15)` background and a 2px `--op-nav` underline. Badges: `--op-wait` for unidentified files, `--op-nav` for tasks; `hidden` attribute when 0. Live tasks count: only on pages that already open a `Realtime` with the `tasks` topic (check with `grep -l "new Realtime" app/templates`); in each, the existing `tasks` handler also sets `#navCountTasks` text to the number of tasks with `status === 'running'` and toggles `hidden` when 0. Other pages show the server count from page load. `settings_layout.html` keeps `{% block panel %}` inside a plain `container-fluid`.
- [ ] **Step 4: Run** `tests/test_navigation.py tests/test_theme_search.py tests/test_mobile_layout.py tests/test_*_i18n.py tests/test_dashboard_pwa.py` - expected PASS.
- [ ] **Step 5: Commit** `Flat top navigation with counters`.

### Task 5: Phone bottom bar and More sheet

**Files:**
- Modify: `app/templates/nav.html`, `app/static/style.css`, `app/i18n.py`
- Test: `tests/test_navigation.py` (extend), `tests/test_mobile_layout.py` (extend)

**Interfaces:**
- Consumes: Task 4's visibility rules and `nav_counts`.
- Produces: `<nav class="bottom-nav">` (admins only) and `#moreSheet` (Bootstrap `offcanvas offcanvas-bottom`); `body.has-bottom-nav`; i18n keys `nav.more`, `nav.files`, `nav.tasks`, `nav.stats` (reuse `settings_nav.*` if equal).

- [ ] **Step 1: Write the failing tests:**

```python
def test_bottom_nav_for_admins_only(admin_client, shopper_client):
    html = admin_client.get("/").get_data(as_text=True)
    assert 'class="bottom-nav' in html and 'id="moreSheet"' in html
    assert 'class="bottom-nav' not in shopper_client.get("/").get_data(as_text=True)

def test_bottom_nav_is_phone_only_and_padded():
    css = _css()
    phone = _media_block(css, "max-width: 767.98px")
    assert re.search(r"\.bottom-nav \{[^}]*position: fixed", phone)
    assert "safe-area-inset-bottom" in phone
    assert re.search(r"body\.has-bottom-nav \{[^}]*padding-bottom", phone)
    assert re.search(r"\.bottom-nav \{[^}]*display: none", css)  # hidden by default (desktop)
```

- [ ] **Step 2: Run** - expected FAIL.
- [ ] **Step 3: Implement.** Five items: Library, Files, Tasks, Stats, More (icons `bi-grid`, `bi-file-earmark`, `bi-list-task`, `bi-bar-chart`, `bi-three-dots`), active item in `--op-nav`. More sheet lists Setup, Dashboard, Settings, Services, the mode and style choices (same `data-theme-choice` / `data-style-choice` buttons, so `theme.js` marks them), language and account. Add `has-bottom-nav` to `<body>` from `nav.html` with a tiny line in `theme.js`'s `DOMContentLoaded` (`if (document.querySelector('.bottom-nav')) document.body.classList.add('has-bottom-nav')`) - no new inline script. Below 768px hide the top bar's collapsible menu and toggler for admins; keep logo + search.
- [ ] **Step 4: Run** `tests/test_navigation.py tests/test_mobile_layout.py tests/test_*_i18n.py` - expected PASS.
- [ ] **Step 5: Commit** `Phone bottom navigation with More sheet`.

### Task 6: Shared components and Dashboard reference page

**Files:**
- Modify: `app/static/style.css`, `app/templates/dashboard.html`
- Test: `tests/test_design_tokens.py` (extend), `tests/test_dashboard_pwa.py` (adjust if it asserts old markup)

**Interfaces:**
- Consumes: tokens (Task 2).
- Produces: classes `.page-head` (children `.page-head__icon`, `.page-head__title`, `.page-head__count`, `.page-head__desc`), `.stat-tile` + modifiers `--ok`, `--wait`, `--nav`, `--action` (children `.stat-tile__icon`, `.stat-tile__value`, `.stat-tile__label`), `.filter-pill` (+ `.active`, child `.filter-pill__count`), `.toolbar`, `.surface`, `.status-badge` + `--ok`, `--wait`, `--dlc`, `--fav`, `.empty-state`.

- [ ] **Step 1: Write the failing tests:**

```python
COMPONENTS = (".page-head", ".stat-tile", ".filter-pill", ".toolbar", ".surface",
              ".status-badge", ".empty-state")

def test_components_exist_and_use_tokens_only():
    css = _read("app/static/style.css")
    for cls in COMPONENTS:
        body = _rule(css, cls)
        assert body, cls
        assert not re.search(r"#[0-9a-fA-F]{3,8}\b", body), cls

def test_reduced_motion_disables_component_transitions():
    assert "prefers-reduced-motion: reduce" in _read("app/static/style.css")

def test_dashboard_uses_page_head_and_stat_tiles(admin_client):
    html = admin_client.get("/admin").get_data(as_text=True)
    assert 'class="page-head' in html and "stat-tile" in html
```

- [ ] **Step 2: Run** - expected FAIL.
- [ ] **Step 3: Implement.** Visuals per the spec's component table; `.game-surface` keeps working and shares `.surface`'s rules. Dashboard: replace the `task-section-head` + subtitle with `.page-head` (icon `bi-speedometer2`, existing `dash.title` / `dash.subtitle`, refresh button kept), and make the JS that fills `#dashTiles` emit `.stat-tile` markup (modifier: files -> `--nav`, size -> `--action`, unidentified -> `--wait`, up to date -> `--ok`).
- [ ] **Step 4: Run** `tests/test_design_tokens.py tests/test_dashboard_pwa.py tests/test_ui_polish.py tests/test_*_i18n.py` - expected PASS.
- [ ] **Step 5: Commit** `Shared components; Dashboard as reference page`.

### Task 7: Login, setup and offline pages

**Files:**
- Modify: `app/templates/login.html`, `app/templates/setup.html`, `app/templates/offline.html`, `app/static/style.css`
- Test: `tests/test_design_tokens.py` (extend)

- [ ] **Step 1: Write the failing test:** `/login` and `/offline` contain `class="surface` and the logo `logo/logo.svg`; `/setup` (admin) contains `class="page-head`.
- [ ] **Step 2: Run** - expected FAIL.
- [ ] **Step 3: Implement.** Login: centered `.surface` card with logo, shop name, page-head glow behind it, action-colored submit. Setup: `.page-head` (icon `bi-joystick`). Offline: `.empty-state` inside `.surface`.
- [ ] **Step 4: Run** `tests/test_design_tokens.py tests/test_auth_hardening.py tests/test_first_run.py tests/test_dashboard_pwa.py tests/test_*_i18n.py` - expected PASS.
- [ ] **Step 5: Commit** `Restyle login, setup and offline pages`.

### Task 8: Credits and docs

**Files:**
- Create: `NOTICE.md`
- Modify: `README.md`, `app/static/vendor/README.md` (if not done in Task 2), `CHANGELOG.md`, `Usage.md` (Appearance section)
- Test: `tests/test_branding.py` (extend)

- [ ] **Step 1: Write the failing test:** `NOTICE.md` mentions `a1ex4/ownfoil`, `DeLFuS77/switch-library-manager-web` and `AGPL-3.0`; `README.md` links `NOTICE.md`; `CHANGELOG.md` starts with `## [Unreleased - beta]`.
- [ ] **Step 2: Run** - expected FAIL.
- [ ] **Step 3: Write** the docs. CHANGELOG entry explains the why (one design system so later page redesigns are consistent; styles as identity; flat nav to reach admin pages in one click), in the established style.
- [ ] **Step 4: Run** `tests/test_branding.py tests/test_dockerhub_description.py` - expected PASS.
- [ ] **Step 5: Commit** `Credit upstream and SLMW; document appearance`.

### Task 9: Full verification

- [ ] **Step 1:** Full suite in the background from `beta/`: `PYTHONUTF8=1 python -m pytest -q -p no:cacheprovider -W ignore tests` - expected: all pass.
- [ ] **Step 2:** Run the beta app on port 8466 with its own data dir. `app/local.py` hard-codes `PORT = 8465`, so do not change product code: use a launcher script in the scratchpad that puts `beta/app` on `sys.path`, sets `local.PORT = 8466` and calls the same entry point `ownfoil.cli` uses. Admin via `USER_ADMIN_NAME` / `USER_ADMIN_PASSWORD` with a generated test value recorded in the scratchpad, not in chat. Give the maintainer the exact command.
- [ ] **Step 3:** In the browser, for each style x light/dark (6 combos), desktop and 375px: Library, Dashboard, Files, Tasks, Settings#Appearance, login. Also as a shopper. Check text contrast of `--op-on-action` on `--op-action` and `--op-nav` text on surfaces (AA, 4.5:1 body / 3:1 large).
- [ ] **Step 4:** Send the screenshots to the maintainer; fix anything found (each fix its own commit).
