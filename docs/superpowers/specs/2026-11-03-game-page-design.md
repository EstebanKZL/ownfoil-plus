# Stage 3 - Game page

Status: design approved in conversation on 2026-11-03, pending review of this written spec.
Branch: local `beta` worktree, on top of stages 1 and 2.

## Goal

Give every game its own page, `/game/<titleId>`, in the stage 1 design language
(inspired by SLMW's title page), replacing the Library's metadata modal. Everything the
modal showed and everything the list view knows about a game (updates, DLC, files,
downloads) lives in one place, with its own URL.

Success: from a card, the list view or Ctrl+K a person lands on the game's page; they
see at a glance whether they have it, whether it is up to date and complete, the
catalogue data, and what is missing; admins download files and edit metadata there;
the back button returns to the Library as they left it.

## 1. Route and access

- `GET /game/<title_id>`: an explicit Flask route (the `/<path:path>` catch-all sends
  every other browser path to `/`). `title_id` is accepted case-insensitively,
  normalized to uppercase; anything that is not 16 hex digits renders the page's
  not-found state with status 404.
- Access exactly as the Library: when `shop.public` is false, the same
  `access_required('shop')` gate (login redirect with a safe `next`); when public,
  anyone. The template gets the same `is_admin`, `is_shop` and `web_downloads_enabled`
  values `access_shop()` computes (shared helper, not duplicated).
- Shop clients (Tinfoil, Sphaira, CyberFoil) never request `/game/...`; the route
  serves the browser UI only.
- The page title is `<shop name> | <game name>` once loaded (the server renders
  `<shop name> | Game`; JS updates `document.title`).

## 2. Data

One GraphQL request from `static/js/game.js`, the existing
`title(titleId:)` query (owned or catalogue-only titles):

- Title: `titleId name intro description developer publisher releaseDate bannerUrl
  iconUrl size category numberOfPlayers rating languages region screenshots { url }
  ownership { haveBase upToDate complete }`.
- Owned apps: `apps(owned: true) { appId appType appVersion releaseDate
  downloadableFile { id size verificationStatus } }` and, for admins,
  `files { ... }` (filename, size, extension, verification) - null for other roles,
  as the schema already enforces.
- Updates: `apps(appType: [UPDATE]) { appId appVersion releaseDate owned
  downloadableFile { id size verificationStatus } }` (ownfoil's tracked updates, the
  same source the list view uses and `ownership.upToDate` is computed from).
- DLC: `availableDlc { appId version titledb { name iconUrl bannerUrl releaseDate } }`
  cross-referenced with owned DLC apps.
- `title` null: the not-found state.

Downloads use the existing `/api/library/download/<file_id>` route and its gate
(admin + Settings > web downloads), exactly as the list view does. Metadata edits use
the existing `setTitleOverride` / `deleteTitleOverride` mutations.

## 3. Page layout

**Breadcrumb**: `Library › <name>`; "Library" goes back in history when the previous
page was the Library (so filters, sort, page and scroll survive), else links to `/`.

**Hero** (`.game-hero`): the banner blurred behind (or the style's glows when there is
no art), the cover on the left, and:
- status badges: In your library / Not in your library, Update available,
  Missing DLC, Complete (same colors as the Library cards);
- the name (h1), "publisher · year";
- actions: **Download all** (admins with web downloads on: one button per owned file
  is in the sections; "all" downloads them one after another in the browser),
  **Edit metadata** (admins), **Copy title ID**.

**Fact tiles** (`.game-facts`): Title ID, Release date (DD/MM/YYYY from titledb's
YYYYMMDD), Region, Languages, Genre, Players, Rating, Size, Installed version (highest
owned update, or the base), Latest version (highest known). A tile without a value is
not drawn.

**Sections** (`.surface` blocks, in this order; a section with nothing to show is not
drawn):
1. **Description**: `intro` as a lead line when present, then `description`.
2. **Screenshots**: a horizontal gallery (scroll-snap) instead of the carousel;
   clicking one opens it full size in a light modal.
3. **Updates**: an amber notice when the latest update is missing; a row per known
   update version (version, release date, owned/missing badge; for admins the
   verification icon and a download button).
4. **DLC**: owned and missing DLC (icon, name, owned/missing badge, admin download).
   `?dlc=<appId>` scrolls to and highlights that row.
5. **Files** (admins only): every file of the game: filename, size, format,
   verification status, download.

**Metadata edit** (admins): the modal's edit form (name, developer, publisher, release
date, description, Reset to catalogue) moves to an offcanvas/modal on the page, using
the same mutations; on save the page reloads its data.

**States**: loading skeleton (hero and tiles placeholders); not found ("This game
isn't in the catalogue or the library", back to Library); request failed (error with
Retry), the same `.empty-state` look as the Library.

## 4. Navigation changes

- Library cards: the cover and the title link to `/game/<titleId>` (real `<a>`
  elements, so middle-click / open in new tab work). DLC cards link to their game:
  `/game/<parentTitleId>?dlc=<appId>`. Icon view icons link the same way.
- Library list view: the game name links to its page.
- The metadata modal (`#metadataModal` and its JS) is removed from the Library.
- Ctrl+K (`static/js/search.js`): games open `/game/<titleId>`.

## 5. Code structure

- `templates/game.html` (extends `base.html`, includes `nav.html`): markup skeleton,
  one bare inline `<script>` with `IS_ADMIN`, `IS_SHOP`, `WEB_DOWNLOADS_ENABLED`,
  `TITLE_ID` and the `I18N` object, then `static/js/game.js`.
- Shared helpers the Library and the game page both need (`gqlFetch`,
  `formatTitledbDate`, `formatTitledbSize`, `statusBadge`, the verification badge map,
  the metadata edit form) move to `static/js/library-common.js`, loaded by both pages.
- Styles in `style.css` under a "Game page (stage 3)" block, tokens only.
- Every new string in `app/i18n.py`, `en` and `es`.

## Out of scope

Favorites, collections, similar games, play time, anything needing new data or a
schema change; stats/dashboard (stage 4) and admin pages (stage 5).

## Testing

- Route: 200 with the page for a known id (lowercase id accepted), 404 state for an
  invalid id, login redirect when the shop is private and anonymous, 200 for a shopper,
  public shop anonymous 200; `IS_ADMIN`/`WEB_DOWNLOADS_ENABLED` rendered per role.
- The shipped `GAME_QUERY` (extracted from `game.js`) runs against the real schema on
  a seeded library (owned base + DLC, catalogue-only title) for an admin and a shopper:
  no errors; `files` null for the shopper; catalogue-only title has `ownership` null.
- Library: cards and icons are links to `/game/...`, DLC to the parent with `?dlc=`;
  list view names link; the metadata modal is gone; search.js games point to `/game/`.
- i18n keys in both languages; one bare inline script on `/game/...`; tokens-only CSS.
- Browser: desktop and 375 px, light/dark, three styles, admin and shopper; an owned
  game with update and DLC, a catalogue-only game, a not-found id; download, edit
  metadata, copy title ID, `?dlc=` highlight, back to the Library keeps its state.
