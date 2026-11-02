# Stage 1 - Design system, styles and navigation

Status: approved in conversation on 2026-11-02, pending review of this written spec.
Branch: local `beta` worktree (`ownfoil-plus/beta/`), not pushed until the maintainer says so.

## Goal

Give Ownfoil-Plus a new visual design inspired by
[DeLFuS77/switch-library-manager-web](https://github.com/DeLFuS77/switch-library-manager-web)
(SLMW) while keeping every Ownfoil-Plus feature, its name and its identity. This first
stage builds the foundation every later page redesign uses: design tokens, three color
styles, the Inter font, a flat navigation with a phone bottom bar, and a set of shared
components shown on the Dashboard.

Success: every page picks up the new colors, font and navigation without a per-page
rewrite; the maintainer can switch between 3 styles x light/dark/auto; nothing that works
today stops working (routes, permissions, i18n, PWA, offline LAN use).

## Licensing

Ownfoil (a1ex4/ownfoil) and SLMW are both AGPL-3.0, so SLMW's design ideas and adapted
style fragments can be used.

- Add `NOTICE.md` crediting a1ex4/ownfoil (AGPL-3.0, the upstream) and
  DeLFuS77/switch-library-manager-web (AGPL-3.0, design inspiration and adapted style
  fragments), with links and license names.
- One line in `README.md` pointing to `NOTICE.md`.
- Do not use SLMW's logo, name, branding or UI copy. Styles get our own names.
- Inter is SIL OFL 1.1: listed in `app/static/vendor/README.md` with its license file.

## 1. Visual foundations

### Tokens

New stylesheet `app/static/css/tokens.css`, loaded in `base.html` after Bootstrap and
before `style.css`. It is the only place color values are defined.

- Shared (all styles): surfaces (`--op-surface-0` page, `--op-surface-1` card,
  `--op-surface-2` raised), text (`--op-text`, `--op-text-muted`), borders
  (`--op-border`, `--op-border-strong`), radii (8 / 12 / 16 px), shadows, motion
  (150-200 ms, `--op-ease`).
- Semantic colors with one meaning each, identical across styles: green `--op-ok`
  (up to date, done), amber `--op-wait` (something waits for you: update, missing DLC,
  step to do), gold `--op-fav` (favorites), red `--op-danger` (errors, destructive).
- Per style, only three things change: `--op-nav` (navigation accent: active page,
  filters, focus), `--op-action` (primary action buttons) and `--op-glow-1/2` (soft
  background glows of page headers).

| Style | `data-style` | `--op-nav` | `--op-action` |
|---|---|---|---|
| Ownfoil | `ownfoil` | cyan (logo) | cyan |
| Neon | `neon` | red | red, cyan as secondary |
| Joy-Con (default) | `joycon` | cyan (logo) | neon red |

Selectors: `:root[data-style="..."]` combined with `[data-bs-theme="light|dark"]`, so
6 combinations. Each style defines a dark and a light variant; light keeps today's soft
warm palette idea with the style's accents toned down for contrast.

The tokens feed Bootstrap's variables (`--bs-primary`, `--bs-primary-rgb`,
`--bs-body-bg`, `--bs-body-color`, `--bs-border-color`, `--bs-link-color`,
`--bs-font-sans-serif`, ...), so existing templates take the new look without edits.
Hard-coded colors in `style.css` (e.g. `#0d6efd`, the `--files-*` palette, the card
gradients) are replaced by tokens.

### Choosing a style

- New setting `appearance.default_style` in `DEFAULT_SETTINGS` (`constants.py`),
  default `"joycon"`, allowed `ownfoil | neon | joycon`; an unknown value falls back to
  `joycon` when read.
- New Settings section **#Appearance** (admin) to change it; added to the Ctrl+K page
  list in `templates/nav.html`.
- A context processor exposes `default_style`; `base.html` renders
  `<html data-bs-theme="dark" data-style="{{ default_style }}">` so the admin's choice is
  in the markup before any JS runs (also on login, setup and offline pages).
- `theme.js` gains a second axis: `localStorage['style']`, accepted only if it is one of
  the three values; when set, it overrides the server default; `setStyle(name)` saves
  and applies it; a "Use the server default" option clears it. Applied synchronously in
  `<head>` like the mode, so there is no flash.
- The theme menu shows Mode (light / dark / auto) and Style (three color swatches with
  names); the active choice of each is marked.

### Typography and icons

- Inter variable (woff2, latin + latin-ext), vendored in
  `app/static/vendor/inter/` with an `@font-face` in `tokens.css`; system font stack as
  fallback. No CDN.
- Keep Bootstrap Icons (already vendored).

## 2. Components and navigation

### Top bar (desktop, >= 768 px)

Left to right: logo + shop name; **Library**, **Files** (count of unidentified files),
**Tasks** (count of running tasks), **Statistics**; **Admin** dropdown (Dashboard,
Settings, Services, Setup); right side: Ctrl+K search, theme menu (mode + style),
language, account (profile / logout, or login).

- Active page: a pill tinted with `--op-nav` plus an underline.
- Counters: computed server-side by a helper cached for a few seconds (no extra query
  per click), exposed through a context processor, only for admins. The Tasks counter
  is also updated live through `realtime.js` (`tasks` topic) on pages that already
  open the socket; a zero count hides the badge.
- Non-admin users see Library, search, theme, language and account only (as today).
- The Admin sub-navigation in `settings_layout.html` is removed; routes stay the same
  (`/admin`, `/admin/settings`, `/admin/files`, ...), so bookmarks keep working.

### Bottom bar (phone, < 768 px)

- Fixed at the bottom: **Library, Files, Tasks, Statistics, More** (icons + short
  labels, counters as dots/badges). Non-admins: no bottom bar entries beyond Library,
  so the bar is not shown; the top bar menu is used instead.
- **More** opens a bottom sheet (Bootstrap offcanvas-bottom) with the Admin links,
  theme (mode + style), language and account.
- Respects `env(safe-area-inset-bottom)`; page content gets bottom padding so nothing
  hides under the bar. On phones the top bar keeps only the logo and search.

### Shared components (in `style.css`)

| Class | What it is |
|---|---|
| `.page-head` | Colored icon square, title, optional count badge, one-line description, soft glow from `--op-glow-*`. |
| `.stat-tile` | Icon, big number, label; tinted with one semantic or style color (`.stat-tile--ok`, `--wait`, `--nav`, `--action`). |
| `.filter-pill` | Rounded filter with a count; `.active` is filled with `--op-nav`. |
| `.toolbar` | One block holding search input, sort select and view toggles. |
| `.surface` | Card: 16 px radius, thin border, `--op-surface-1`, slight lift on hover. Replaces `game-surface` styling while keeping that class working. |
| `.status-badge` | Up to date / update / missing DLC / favorite, each with its fixed color. |
| `.empty-state` | Icon, title, one sentence, optional button. |

Motion is short (150-200 ms) and disabled under `prefers-reduced-motion: reduce`.

### Pages in this stage

All pages get the new colors, font, radii and navigation through the tokens. Their own
layouts are not redesigned yet (stages 2-5), except:

- **Dashboard**: uses `.page-head` and `.stat-tile` as the reference page.
- **Login, setup, offline**: new style (logo, surfaces, buttons).

## 3. Scope, verification and delivery

### In scope

1. `tokens.css` with 3 styles x light/dark, wired into Bootstrap variables.
2. Vendored Inter.
3. `theme.js` style axis, `appearance.default_style` setting and #Appearance section.
4. Flat top bar with counters, phone bottom bar with the More sheet.
5. Shared components; Dashboard as the reference page.
6. Login, setup and offline pages restyled.
7. New strings in `app/i18n.py`, `en` and `es` (voseo).
8. `NOTICE.md`, README credit, CHANGELOG draft.

### Out of scope (later stages)

Library (stage 2), title page (3), statistics and dashboard details (4), settings,
files, tasks and admin pages (5). Splitting JS out of the big templates happens as each
page is redesigned.

### Testing

- New tests: `appearance.default_style` default and fallback; `data-style` rendered in
  pages for each value; `theme.js` only accepts the three style names; nav shows admin
  items and counters only to admins; the Admin dropdown and bottom bar link to the
  existing routes; i18n keys exist in both languages.
- Existing tests that must keep passing, updated deliberately where the markup changes:
  `test_*_i18n.py` (one bare inline `<script>` per page), settings tests, nav/search
  tests.
- Run affected test files first, then the full suite in the background
  (`PYTHONUTF8=1`, Python 3.13 venv, `pytest tests` from `beta/`).

### Browser verification

Run the beta app from `beta/` on port 8466 with its own data directory. Check desktop
and 375 px, light and dark, all three styles (6 combinations), admin and non-admin user.
Check text contrast on accent colors (WCAG AA for body text and buttons). Send the
screenshots to the maintainer.

### Delivery

- Commits on the local `beta` branch only; no push, no change to `main`.
- `pyproject.toml` version unchanged while in beta; `CHANGELOG.md` gets a
  `## [Unreleased - beta]` section that becomes `6.2.5.N` when the maintainer asks to
  promote beta, which then follows the normal branch + PR + CI + release flow.
