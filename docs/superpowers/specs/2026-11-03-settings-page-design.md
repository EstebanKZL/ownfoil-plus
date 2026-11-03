# Stage 5b - Settings page

Status: design approved in conversation on 2026-11-03 (option A: one page with a
sticky index), pending review of this written spec.
Branch: local `beta` worktree, on top of stages 1-5a.

## Goal

Bring Settings (`/admin/settings`) into the stage 1 design language and make its
twelve sections easy to reach, and move its inline JavaScript (about 1,370 lines) out
of the template - the last part of pending item 1. Every setting, button, modal and id
stays, and each section saves exactly as it does today.

Success: the page looks like the other admin pages; any section is one click away on
desktop and phone; every existing link into the page (`#Authentication`,
`#Maintenance`, `#Notifications`, `#Library`, control ids such as `#shopHostInput`)
still lands where it did; the template holds markup, strings and server data only.

## 1. Layout

- `.page-head` (icon `bi-gear`, title `settings_nav.settings`, a one-line description
  - new key `settings.page_desc`). The missing-admin / keys / host alerts stay above
  it, unchanged.
- Desktop (>= 992px): two columns - a sticky index on the left (about 14rem, below
  the top bar) and the sections on the right.
- Phone and tablet (< 992px): the index becomes a single row of chips, sticky under
  the top bar, scrolling sideways; no horizontal page overflow at 375px.

## 2. The sections

Each section becomes a `<section class="surface admin-section settings-section"
id="...">` with an `.admin-section__title` heading (icon + title); the `<hr
class="hr-settings">` separators go. Order, ids and icons:

| id | title key | icon |
|---|---|---|
| `Authentication` | `auth.heading` | `bi-people` |
| `Library` | `sections.library` | `bi-folder` |
| `Titles` | `sections.titles` | `bi-translate` |
| `Media` | `sections.media` | `bi-image` |
| `Shop` | `sections.shop` | `bi-shop` |
| `Scheduler` | `sections.scheduler` | `bi-clock` |
| `Maintenance` | `sections.maintenance` | `bi-archive` |
| `Notifications` | `sections.notifications` | `bi-bell` |
| `Workers` | `sections.workers` | `bi-cpu` |
| `Appearance` | `sections.appearance` | `bi-palette` |
| `Backup` | `backup.heading` | `bi-box-arrow-down` |
| `Danger` (new id) | `danger.heading` | `bi-exclamation-triangle` |

- One list of these entries at the top of the template drives both the index and the
  section headings (a Jinja macro), so the two can't drift apart.
- Sub-parts keep their content and become sub-headings inside their card
  (`.settings-subhead`): Library's paths, watcher, management, compression,
  verification, organizer and templates; Shop's clients; Maintenance's actions and
  backups; Notifications' events and channels. The notification channel cards become
  `.surface`-styled inner cards (tokens, no Bootstrap literal colors).
- Danger zone: the card has an `--op-danger` border and its title is in
  `--op-danger`; the reset modal is unchanged.
- Anchored targets get `scroll-margin-top` so the sticky top bar (and the phone chips)
  don't cover a section or a control reached through a link.

## 3. The index

- Links (`<a href="#Id">`) with the section's icon and title; a click scrolls smoothly
  (instant under `prefers-reduced-motion`) and updates the URL hash with
  `history.replaceState` (no history entry per click).
- Scrollspy: an `IntersectionObserver` marks the section being read
  (`.active` + `aria-current="true"` on its link); on the phone the active chip is
  scrolled into view inside the chip row (not the page).
- Arriving with a hash (`/admin/settings#Notifications`, or a control id inside a
  section) marks that section's link active.
- The index is a `<nav>` with an accessible name (new key `settings.index_label`,
  "On this page" / "En esta página").

## 4. Code structure

- `templates/settings.html` keeps one bare inline `<script>` holding the `I18N`
  object, plus two server values: `ADMIN_ACCOUNT_CREATED` (bool) and the TitleDB
  languages in a `<script type="application/json" id="settingsLanguages">` block. The
  logic moves to `static/js/settings.js`, loaded after the inline script.
- The four strings rendered inline into the JS today (`backup.import_no_file`,
  `backup.import_success`, `backup.import_failed` twice) move into `I18N`; the
  `{% if admin_account_created == false %}` block becomes an `if
  (!ADMIN_ACCOUNT_CREATED)` in the script.
- Global functions called from `onclick=` attributes stay top-level function
  declarations in `settings.js`.
- New strings in `app/i18n.py` (`en` + `es`), styles under "Settings (stage 5b)" in
  `style.css`, tokens only. No server, route or schema changes.
- Tests that read the settings JS from the template read `settings.js`.

## 5. Testing

- The index lists the twelve ids above in order, each with a matching section, and
  every section is a `.surface`.
- Every `getElementById` / `$('#...')` target that `settings.js` uses exists in the
  rendered page (the same check stage 5a added for Files and Tasks).
- The template has one bare inline script and no Jinja inside `settings.js`.
- Links into the page from the Dashboard, Ctrl+K, Files and Setup still point at ids
  that exist.
- Browser: 1440 and 375px, light and dark, the three styles; the index follows the
  scroll; saving works in Authentication (add user), Titles, Notifications and
  Appearance; a deep link (`#Maintenance`, `#shopHostInput`) lands visible.

## Out of scope

- Changing what any setting does, splitting Settings into several pages, or new
  settings.
- Sphaira save backups (pending item 2).
