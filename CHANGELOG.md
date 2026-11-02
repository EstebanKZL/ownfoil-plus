# Changelog

All notable changes to Ownfoil-Plus are documented here, version by version. This
only covers this fork's own changes on top of [Ownfoil](https://github.com/a1ex4/ownfoil) -
see the upstream project for its own history.

## [Unreleased - beta]

A new design for the web UI, stage 1 of a redesign inspired by
[Switch Library Manager Web](https://github.com/DeLFuS77/switch-library-manager-web)
(AGPL-3.0, like Ownfoil; credited in the new `NOTICE.md`). This stage lays the
foundation the next ones build on, so every page ends up looking like one product
instead of each page carrying its own colors.

- **Design tokens.** Every color now lives in one file, `static/css/tokens.css`, which
  also feeds Bootstrap's variables: existing pages take the new look without being
  rewritten. Each color has one meaning everywhere - green up to date, amber something
  waits for you, gold favorites, red errors.
- **Three color styles, on top of light / dark / auto.** Joy-Con (the default: cyan to
  navigate, red for actions), Ownfoil-Plus (the logo's cyan) and Neon (red with cyan).
  The admin picks the one everyone sees, also on the login page, in the new
  `Settings > Appearance`; each browser can still choose its own from the theme menu.
  Contrast of text on the accent colors is at least 4.5:1 in all six combinations,
  which is why the red is a little deeper than a pure neon red.
- **Flat navigation.** The admin pages were behind `Admin` and a second row of tabs;
  now `Files`, `Tasks` and `Stats` are on the top bar, with counters for unidentified
  files and running tasks (the tasks one updates live on the Tasks page), and the rest
  under an `Admin` menu. URLs are unchanged. On phones, admins get a bottom bar with a
  `More` sheet for everything else.
- **Inter font**, served by the app itself like the other front-end libraries, so the
  UI still works on a LAN with no internet access.
- **Shared components** (page header, stat tiles, filter pills, toolbar, surfaces,
  status badges, empty states), shown first on the Dashboard, the login, the setup
  guide and the offline page. The library, the game page and the other admin pages
  adopt them in the next stages.

## [6.2.5.45]

Image vulnerabilities, from a Docker Scout report of 5 critical / 30 high.

- **Python dependencies: from 42 known vulnerabilities to none** (checked with
  `pip-audit`). They were all in three pinned packages, each with a fixed release:
  - **Pillow 12.3.0 -> 13.0.0** (39 of them, including the critical ones);
  - **strawberry-graphql 0.324.0 -> 0.339.1** (2);
  - **Werkzeug 3.1.8 -> 3.1.9** (1).
  Also gunicorn 26.0.0 -> 26.2.0 and setproctitle 1.3.7 -> 1.3.8. urllib3 - which the
  app needs, under `requests`, for TitleDB, artwork and notifications - is now pinned
  explicitly (2.8.0) instead of left to whatever `requests` resolved.
- **pip is removed from the final image.** The app never uses it at runtime, and it
  carries its own vendored copies of libraries (urllib3 among them) that scanners flag
  whenever they lag behind; the app's own urllib3 stays.
- **The 32-bit ARM builds (arm/v6, arm/v7) clean up for real.** Their build tools were
  installed in one `RUN` and removed in another, so they stayed in the image's earlier
  layer; install and cleanup are now a single step (`apk --virtual .build-deps`). And
  the runtime libraries Pillow and zstandard link against (libjpeg-turbo, zlib,
  libffi) are now installed explicitly - removing `jpeg-dev` used to remove
  libjpeg-turbo with it, which could leave Pillow unable to open JPEG artwork there.
  Unused cairo/pango/gdk-pixbuf build packages dropped.
- **New `.github/dependabot.yml`**: weekly PRs for outdated Python packages (minor and
  patch grouped in one PR, majors on their own), the base image, and monthly for
  GitHub Actions - with the test suite run on each.
- **New `Security` workflow** on every PR and weekly: `pip-audit` on
  `requirements.txt`, plus the image built and scanned with Trivy (fails on a fixable
  CRITICAL or HIGH vulnerability). It also lists the urllib3 copies inside the image
  and checks pip is gone.
- `requirements.txt` and `pyproject.toml` are checked to pin identical versions.
- New `tests/test_dependency_security.py` (5 tests).

## [6.2.5.44]

UI polish, from screenshots of a real 266-game library.

- **Card view: no more cut-off cards.** On a narrow card (6+ per row) the game info
  sits under the banner, and every card in a row stretches to the tallest one - but
  the info block didn't stretch with it, leaving a bare strip under shorter cards that
  read as the card being cut off. The info block now fills the card down to its edge,
  with the badges pinned to the bottom, so a row lines up.
- **A softer light theme**: warm off-white "paper" tones (the page `#eceae4`, cards
  and panels a step lighter) with charcoal text, instead of Bootstrap's stark white and
  near-black - easier on the eyes for long reading.
- **The light theme now covers the game cards too.** Card and List views were forced
  dark with `text-bg-dark` in both themes, which also left some text unreadable in the
  light theme (e.g. "Base game" and version labels in the List view, dark grey on the
  dark card). They follow the theme now; the dark theme looks exactly as before.
- **Tasks > History: 5 visible, the rest by scrolling, and a "Clear history" button**
  (new `DELETE /api/tasks/history`, admin only; queued, running and failed tasks are
  untouched).
- **Dashboard: "Recently added" and "Latest downloads" show 10, the rest by
  scrolling** (now up to 30 each, from 8 and 6).
- **Stats > Downloads: "Most downloaded", "By user", "By client" and "Latest
  downloads" show 10 rows each, the rest by scrolling, with the header row kept in
  view.** "Most downloaded" now lists up to 50 titles (was 10).
- **"Upload files" moved from the Files page to the dashboard**, next to the `Storage`
  heading (above the free-space figures). Finishing an upload refreshes the dashboard,
  so the new game shows in "Recently added". The dialog and its script are now a
  reusable partial (`_upload_modal.html`) and `static/js/upload.js`; the global search
  finds it under the dashboard ("upload", "subir").
- The row capping is one small helper (`static/js/scroll-limit.js`) that sizes each
  list from its rendered rows, so it's exact on a phone too, where rows wrap to two
  lines.
- New `tests/test_ui_polish.py` (13 tests).

## [6.2.5.43]

Performance for large libraries ("Etapa 4"), measured on a synthetic library of 6,000
games / 30,000 apps / 18,000 files rather than guessed. (WAL mode, `synchronous=NORMAL`
and a busy timeout were already set on the database.)

- **New indexes** (migration `d5e6f7a8b9c0`, applied automatically on start with the
  usual pre-migration backup):
  - `apps(title_id)`: every per-game recompute scanned the whole apps table. **The
    batch recompute after each TitleDB refresh went from 19.4 s to 3.8 s**, and each
    per-game lookup from ~1 ms to 0.05 ms.
  - `files(added_at)`: the Files page's default newest-first order and the dashboard's
    recently added list sorted the whole table on every page (4.1 ms -> 0.06 ms).
  - `files(library_id)`: the foreign key a library removal cascades through.
- **Adding a file no longer loads every path of its library**: `add_file` checked
  `filepath in get_library_file_paths(...)` - every path of the library, for every
  file - which on an 18,000-file first scan was ~8 ms per file, minutes in total. It's
  now one indexed lookup.
- **New: Prometheus metrics at `/metrics`** (library size, unidentified files, owned /
  complete / up-to-date games, files per verification status, tasks per status,
  downloads, disk space and reachability per library, backup count and age, users,
  shop visibility). Plain text format written by hand, so no new dependency; values are
  exact (no rounding of byte counts or timestamps). Needs an admin account (Basic Auth
  or a session) or the new `OWNFOIL_METRICS_TOKEN` bearer token. `Install.md` has a
  scrape config and alert examples.
- New `tests/test_performance_metrics.py` (11 tests).

## [6.2.5.42]

Phone layout fixes for the admin pages, found by going through every page at 375px.
None of the pages scrolled sideways; these are about how much fits on a screen.

- **Files: the six summary tiles are two compact columns on a phone** instead of one
  full-width tile per row, which took more than a full screen of scrolling before the
  file list itself. Now the list starts on the first screen.
- **Tasks: task names are no longer cut to a few letters on a phone** ("Daily …",
  "Updat…"): the date and details move to a second line under the name, which gets
  the whole width.
- **Admin tabs are one horizontally scrolling row on a phone** instead of wrapping onto
  two lines, and the current page's tab is scrolled into view (so `Stats` isn't hidden
  past the right edge).
- **Settings: half-width fields are full width on a phone** (worker count, intervals,
  region/language, ...), still half width from tablets up.
- Desktop and tablet layouts are unchanged.
- New `tests/test_mobile_layout.py` (5 tests).

## [6.2.5.41]

- **New: light / dark / automatic theme**, from a sun/moon menu in the navbar.
  Automatic follows the device's own setting and switches live when it changes. The
  choice is remembered per browser (localStorage) and applied by a small script in
  `<head>` before the first paint, so there's no flash of the wrong colors. Dark stays
  the default, so nothing changes for anyone who doesn't pick a theme. The UI was
  already built on Bootstrap's theme variables; game cards (card and list views)
  deliberately stay dark over their artwork in both themes, as do the "console screen"
  boxes on the Setup page and the navbar.
- **New: global search** (`Ctrl+K` / `Cmd+K`, `/`, or the magnifier in the navbar),
  on every page. Finds games in the library by name or title ID, files by name (admins
  only), and pages and settings sections by name or keyword in English and Spanish
  ("notificaciones", "backup", "usuarios", "discord"...), accent-insensitive. Arrow keys
  move, `Enter` opens: a game opens the library already filtered to it, a file opens
  the Files page filtered to it, a setting jumps to its section. A user without admin
  access only ever sees games and the pages they can open.
- New `/api/search` endpoint (shop access; files only for admins). The library page
  and the Files page now accept `?q=` to start pre-filtered.
- Settings sections that had no anchor now have one (`#Library`, `#Titles`, `#Media`,
  `#Shop`, `#Scheduler`, `#Workers`, `#Backup`), so links can jump straight to them.
- New `tests/test_theme_search.py` (13 tests); `test_settings_i18n`'s divider check
  now finds the sections by their ids, since their names also appear in the search
  list.

## [6.2.5.40]

- **New: dashboard**, now the landing page of `Admin` (and the first entry of its
  sidebar). At the top, only what needs attention, each linking to the page that
  fixes it: missing/invalid console keys, an unreachable library, under 5% free disk
  space, corrupt files, failed tasks, unidentified files, games with duplicate files,
  no backups yet - or "All good". Then four tiles (games with % complete / up to date,
  files and total size, downloads in the last 7 days, running and queued tasks), a
  free-space bar per library, the 8 latest added files and 6 latest downloads, and
  status badges for maintenance (next run), last backup, notifications and shop
  access. One `/api/dashboard` request of plain aggregate SQL, so it stays fast on big
  libraries.
- **New: installable app (PWA)**. The web UI can be installed on a phone, tablet or
  computer with its own icon and window, under the shop's name; an `Install app`
  button shows up in the navbar when the browser offers it. A service worker caches
  the static files (pages open faster) and shows a "can't reach the server" page with
  a retry button instead of a browser error when the server is down. Pages always come
  from the network, and the API, downloads, artwork and uploads are never intercepted.
  Browsers only allow this on HTTPS or `localhost`; on a plain-http LAN address
  nothing changes.
- **Fixed the web app manifest**: the old static `site.webmanifest` pointed its icons
  at `/web-app-manifest-*.png`, which don't exist at that path (the shop's catch-all
  route redirected them), so the app was never actually installable. It's now served
  at `/manifest.webmanifest` with the shop's name, correct icon paths (`any` and
  `maskable`), a dark theme color and shortcuts to the library and the dashboard.
- New `tests/test_dashboard_pwa.py` (12 tests).

## [6.2.5.39]

- **New: upload games from the web UI** (Files page > "Upload files", admin only).
  Pick the destination library, drop `nsp`/`nsz`/`xci`/`xcz` files or click to choose
  them, and they upload one after another with a progress bar, speed, and pause /
  resume / cancel per file.
- **Resumable**: files go up in 8 MiB chunks, each appended at the offset the server
  confirms. An upload is identified by library + file name + size, so if the
  connection drops, the tab is closed or the server restarts, choosing the same file
  again carries on from where it stopped instead of starting over. Unfinished uploads
  are listed in the same window (with a discard button) and removed automatically
  after 7 days without activity (at startup and in the daily maintenance window).
- **Works behind a reverse proxy with a small body limit**: if a chunk is refused with
  413 (nginx's default is 1 MB), the chunk size halves automatically down to 512 KiB.
  Network errors are retried with backoff, and an offset mismatch (a lost response, a
  second tab) is corrected from what the server actually has.
- **No multi-GB copy at the end**: the partial file is a hidden `.part` file in the
  target library itself (not a game extension, so scans and the file watcher ignore
  it), and finishing is a rename. The new file is then identified and processed like
  any other: `add_file` is queued explicitly so it works with the file watcher off.
- **Refused up front**: unknown library, wrong extension, a name already in the
  library, an unreachable library folder, or not enough free space for the rest of
  the file. File names keep brackets and accents (a `[titleId]` in the name is how a
  file is identified without keys); only path separators and characters no
  filesystem accepts are removed.
- Upload session metadata is a small JSON file per upload under `data/uploads/`, so
  it needs no database migration.
- `Install.md`: reverse proxy note on body size limits for uploads.
- New `tests/test_uploads.py` (24 tests).

## [6.2.5.38]

- **New: download history** (Stats > Downloads). Until now each file only had a
  counter; now every counted download is logged with **who** (the console's shop
  user, or the signed-in web user; none on a public shop), **which client** (Tinfoil,
  Sphaira, CyberFoil, the web UI's own download button, or "other"), **from which
  address** (the real one behind a reverse proxy) and **when**.
- The new section shows, for the last 7, 30, 90 or 365 days: total downloads and data
  served, a **downloads-per-day chart** (plain CSS bars - no chart library, so it works
  offline like the rest of the UI), the **10 most downloaded titles**, counts **per
  user** and **per client**, and the **50 latest downloads**. All-time total too.
- Logged on exactly the same 60-second per-file-and-address throttle as the existing
  counter, so a Sphaira HEAD-then-GET, a resumed download or a Range probe is one
  entry, not several.
- Each entry keeps its own copy of the file name and title, so the history still reads
  right after the file is deleted, renamed or reorganized (the link to the file is set
  to null instead of cascading the entry away).
- Kept for one year (older entries are pruned as new ones come in), and a "Clear
  history" button empties it without touching the per-file counters. A failure to
  write the log never affects the download itself.
- New `download_events` table: database migration `c4d5e6f7a8b9`, applied
  automatically on start (with the usual pre-migration database backup).
- New `tests/test_download_history.py` (15 tests).

## [6.2.5.37]

- **New: daily maintenance window** (Settings > Maintenance & backups). Off by
  default; once on, runs every day at a chosen time (server local time, `04:00` by
  default) and can:
  - **back up** the database, settings and console keys (on by default once the
    window is enabled), keeping the newest N (`7` by default);
  - **scan the libraries** - finds new and missing files and processes what's
    pending, useful with the file watcher off or on network shares;
  - **delete update files superseded by a newer version**;
  - **re-verify every file**, never / Sundays only / every day - unlike the normal
    verification, which only checks new files, this catches files damaged after they
    were added. Slow on big libraries, hence weekly as the suggested choice.
  Each job runs as its own task, so it shows on the Tasks page and one failing doesn't
  stop the others. The next run is shown next to the time, and is recomputed on
  every start (so a clock or timezone change, or turning it off while the server was
  down, never leaves a stale run behind). A failed backup still books the next day's
  run, and with notifications on it is reported as a failed task.
- **Backups**: one zip per backup in `config/backups/` (the persistent config volume)
  with `ownfoil.db`, `settings.yaml` and `keys.txt`. The database is copied with
  SQLite's online backup API, so the snapshot is consistent even while workers are
  writing, and each zip is written under a temporary name and renamed into place, so
  an interrupted backup never leaves a truncated file that looks valid. TitleDB and
  artwork are left out: they're downloaded again on their own.
- **"Back up now" button and backup list** in the same section, with download and
  delete per backup (admin only; names are matched exactly, so the endpoints can't be
  pointed at any other file). Restoring is a manual step, documented in the section
  and in `Usage.md`.
- New `tests/test_maintenance_backups.py` (20 tests).

## [6.2.5.36]

- **New: push notifications** (Settings > Notifications), through **Discord**,
  **Telegram**, **ntfy** and a **generic JSON webhook** (for Home Assistant, n8n,
  scripts...), any combination at once. Off by default. Four events, each with its own
  checkbox:
  - **A game, update or DLC is added to the library** - announced on a file's first
    identification only, so a later re-identify pass (e.g. after uploading keys)
    doesn't announce the whole library again.
  - **A new update or DLC is released for a game you have** - checked after every
    TitleDB refresh, for titles whose base game is in the library. Adding a new game
    doesn't announce its existing updates/DLC as "new", and neither does the very
    first refresh of an empty database.
  - **Verification finds a corrupt file** (the CORRUPT status only - repacks and
    modified files don't trigger it).
  - **A background task fails**, with the task name and error.
- **Grouped, not spammed**: events are collected for 20 seconds after the first one
  and sent as one message per event type (up to 15 lines, then "...and N more"), so a
  scan adding 200 files sends one message instead of 200, and stays clear of Discord's
  and Telegram's rate limits.
- **Messages in English or Spanish**, chosen in the same section (independent of the
  browser's UI language).
- **"Send test" button** that uses the form as filled in, even before saving, and
  reports each channel's result separately (e.g. "Test sent to: discord · telegram
  (Failed: HTTP 401)").
- A channel that's down never fails a scan or a task: delivery errors are only logged.
- ntfy is published through its JSON API, so titles with accents (game names,
  Spanish texts) arrive intact; an access token is supported for protected topics.
- The "without sensitive data" settings export also leaves out the Discord/webhook
  URLs and the Telegram/ntfy tokens.
- New `tests/test_notifications.py` (21 tests).

## [6.2.5.35]

Quality and infrastructure ("Etapa 1").

- **The test suite now runs in CI.** New `.github/workflows/tests.yml` runs pytest on
  Python 3.14 (the Docker image's version) on every push and pull request. Until now
  the ~2,000 tests only ever ran by hand.
- **The Docker image is only published from code that passes the tests**:
  `docker.yml` calls `tests.yml` first (`needs: tests`), for tag builds and the weekly
  rebuild alike.
- **New `/api/health` endpoint** (no login needed, reveals nothing beyond "up" and
  whether the database answers; 503 if it doesn't). The image has a `HEALTHCHECK` on it,
  so `docker ps` shows `healthy`/`unhealthy` and orchestrators can restart a stuck
  container. The Helm chart's readiness probe uses it too (it used to probe `/`,
  which is a login redirect on a private shop) and gains a liveness probe.
- **The web UI no longer depends on any CDN.** Bootstrap 5.3.1, Bootstrap Icons
  1.11.1 and jQuery 3.6.0 are served from `app/static/vendor/` (unmodified upstream
  files, hashes checked against the CDN's own SRI values - see
  `app/static/vendor/README.md`), so a shop on a LAN without internet access, or
  behind a filtering DNS, still gets a working interface. Font Awesome was dropped
  entirely: it was loaded on every page but not a single icon used it.
- **Fixed the 96x96 favicon link**, whose `sizes` attribute had ended up inside the
  file name (`favicon-96x96.png" sizes="96x96`), so browsers never found it.
- **The shop now reports its real version** to clients (OPTIONS handshake, LAN
  discovery) instead of `unknown`: the Docker image doesn't install the package, so
  the version is now read from `pyproject.toml`, which the image now ships.
- **Fixed `Files.last_attempt` defaulting to the server's start time**:
  `default=datetime.datetime.now()` was evaluated once, at import, so every new file
  got the same timestamp until the next restart. Now `default=datetime.datetime.now`.
- **`pyproject.toml` points at this fork** (homepage, repository, issues, changelog;
  upstream kept as its own link, original author credited, fork maintainer added).
- **Tests: fixed the capture fixture building mixed-separator paths on Windows**
  (`C:\...\library\Test Game/file.nsp`), which made 11 Sphaira download tests fail
  when the suite ran on Windows. A real scan never stores such paths; only the fixture
  did.
- **Restored `app/data/titledb/languages.json` to the repository.** The placeholder
  Settings reads before the first TitleDB download had silently dropped out of git
  (`/app/data/` in `.gitignore`), so the Docker image shipped without it and a fresh
  install's Settings page returned 500 until TitleDB finished downloading. The new CI
  caught it on its first run. `.gitignore` now un-ignores that one file explicitly.
- New `tests/test_ops_hardening.py` (15 tests).

## [6.2.5.34]

Security hardening ("Etapa 0"). **Upgrading signs everyone out once** - the old
cookie-signing key is gone, so every existing browser session has to log in again.
Console clients (Tinfoil, Sphaira, CyberFoil) use Basic Auth and are unaffected.

- **Login cookies are now signed with a per-install random key.** The Flask
  `SECRET_KEY` used to be a constant in `app.py`, public on GitHub: anyone could forge
  a session cookie for user id 1 and get admin access on any install. It is now read
  from `OWNFOIL_SECRET_KEY`, or generated once with `secrets.token_hex` and stored in
  `config/.secret_key` (created `0600`, race-safe with `O_EXCL`).
- **Session and remember-me cookies are `SameSite=Lax`**, so a page on another site
  can't make a signed-in admin's browser submit a settings import or a keys upload.
- **The login no longer works as an open redirect**: `next` must be a local path
  (`https://…`, `//host`, `/\host` and `scheme:` all fall back to `/`). It is now also
  carried through the login form, so being sent to `/login` from an admin page brings
  you back to that page afterwards (before, it always landed on `/`).
- **Web login brute-force guard**: 5 failed attempts for the same username from the
  same address within 15 minutes lock that pair until the window passes (HTTP 429).
  Keyed per address *and* username, so one mistyped password behind a reverse proxy
  doesn't lock everyone else out.
- **The login page now says when the credentials are wrong** (it used to just reload
  silently) and keeps the typed username.
- **Users can be edited**: the pencil button in Settings > Authentication (which was
  always disabled) opens a dialog to change permissions and, optionally, the password.
  New `PATCH /api/user` endpoint, admin only.
- **The last admin account can no longer be deleted or demoted** - with no admin left,
  authentication switches off entirely and the server is open to anyone on the network.
- **Usernames in the users table are escaped** - they were inserted as raw HTML.
- **"Without sensitive data" settings export**: leaves out the Tinfoil key pair and
  the saved `hauth` values, for sharing the file. Importing it keeps the current ones.
- New `tests/test_auth_hardening.py` (26 tests).

## [6.2.5.33]

- **Fixed the file watcher wiping the whole library registry when a disk disconnects**
  (reported directly: with "Vigilancia de archivos" on, unplugging/losing the drive
  cleared everything, forcing a full re-scan and re-verify). The scan paths already
  had an offline guard (`_library_looks_offline` plus a >50%-missing sanity check),
  but the watcher's own `handle_file_deleted` / `handle_dir_deleted` tasks did not:
  an unmounted USB drive or dropped share reaches the watcher as a flood of delete
  events, and each one deleted its row unconditionally. Both tasks now go through
  `deletion_event_is_trustworthy`: a delete is only acted on when the library root is
  online and non-empty **and** the path is really gone. Real deletions - from the web
  UI or straight off the disk - still clean the registry exactly as before; a
  disconnected disk leaves every row (and its identification/verification state)
  untouched, and reconnecting needs no re-verify.
  - Known tradeoff, same as the scan guard: deleting *every* file in a library by hand
    leaves its rows until the library itself is removed in Settings, since an empty
    root is indistinguishable from an unplugged drive.
  - New `tests/test_watcher_delete_safety.py` (6 tests; the 4 disconnect cases fail on
    the old code).

## [6.2.5.32]

- **Gave `README.md` the same "more convincing" rewrite as `DOCKERHUB.md`**,
  requested directly right after it. The intro and "About this fork" section now
  lead with why to actually use this fork (verified fixes, a weekly-rebuilt and
  security-patched Docker image) instead of starting straight into a feature list,
  and mention the same newer features the old text left out - the Files admin page
  and LAN discovery. No change to the legal fork notice, the image gallery, or the
  Installation/Usage/Credits sections.

## [6.2.5.31]

- **Rewrote the Docker Hub overview page**, requested directly ("algo mejor mas
  convincente"): leads with why to actually pull this image (weekly-rebuilt,
  security-patched, multi-arch, verified-against-real-clients fixes) instead of
  starting straight into a feature list, and folds in newer fork features the old
  text never mentioned (the Files admin page, native Sphaira/Tinfoil/CyberFoil shop
  support with LAN discovery, the tie-break options for duplicate resolution).
- **New `DOCKERHUB.md`** is now the single source of truth for that text, and a new
  `.github/workflows/dockerhub-description.yml` pushes it to Docker Hub automatically
  whenever it changes on `main` (via `peter-evans/dockerhub-description`, reusing the
  same `DOCKERHUB_USERNAME`/`DOCKERHUB_TOKEN` secrets `docker.yml` already needs) -
  this fork has no Docker Hub push access from here to update the page directly, so
  this makes the next edit to one file the only step, instead of a manual copy/paste
  into Docker Hub's own editor every time. Kept as its own workflow, deliberately
  separate from the image build: editing the description shouldn't trigger a full
  multi-arch rebuild, and a broken build shouldn't block a description update.
  **Note:** the Docker Hub access token needs "Read & Write" permission for this step
  specifically - a token scoped only for pushing images can still fail here even
  though `docker.yml` works fine with it.
- Lightly reworded `README.md`'s own opening line to match, for consistency between
  the two.

## [6.2.5.30]

- **Filter dropdown (Biblioteca and Administración) no longer highlights the whole
  row on hover.** Bootstrap's default `.dropdown-item:hover` paints a grey background
  behind the entire row hosting a filter's radio buttons, not just the one under the
  cursor - the per-button highlight was already correct, so the row-level background
  is now turned off for these specific rows (`.filter-group-item`), leaving only the
  hovered/checked button lit up, as requested directly from a screenshot.
- **List view: the divider line above the base-game row now always shows**, even for
  a title with no Updates/DLC. It used to only appear because Bootstrap's
  `list-group-flush` draws a border *between* rows - with a title's only row being
  the base game (nothing else under it), there was no second row to draw that border
  against, so the line silently vanished for exactly the titles that have the least
  going on underneath them. Scoped to the outer list only (`.list-top-group`), so the
  nested Updates/DLC collapsible sections keep their normal behavior.
- **Card view: the type/version/DLC badges no longer overlap the title on a narrow
  card.** There was already a fix for this, but it only keyed off the browser
  *window's* width (`@media (max-width: 767.98px)`), so it only ever helped on a
  phone - a card can go just as narrow on a wide desktop window once the card-size
  slider packs 6-8 cards into a row, which is what the reported screenshot showed.
  Switched to a `@container` query keyed off the card's own rendered width
  (`.game-card` now establishes an inline-size container), so the same "badges move
  below the title instead of floating over it" behavior kicks in whenever the card
  itself is too narrow, regardless of window size. No change to the badges/overlay
  themselves otherwise - same look, same position, whenever there's room for it.

## [6.2.5.29]

- **Moved the "Show game background image" switch above "Enable organizer"** in
  Ajustes → Organizador, requested directly.
- **Lightened the list-row text shadow when the background image is off.** With no
  banner behind the text any more, the full-strength shadow (tuned for reading over a
  busy image) just read as bold/harsh over a flat background. A new `.no-banner` class
  (toggled by the same `SHOW_GAME_BACKGROUND_IMAGE` flag, in `renderListView`) lightens
  `.list-card-body`'s `text-shadow`/icon `drop-shadow` in that case; with the
  background on, the shadow is exactly what it was before.
- **Repo hygiene: added `.gitignore`/`.dockerignore`, requested directly ("no queden
  datos comprometedores").** Auditing what's actually tracked turned up real runtime
  files committed by mistake in a prior local run - `app/config/settings.yaml`,
  `app/config/titles.db` (a fresh/default config and an empty titledb cache, not
  personal library data, but still generated local state that should never be
  committed), plus a stray `.pytest_cache/`. All removed from tracking. Neither
  `app/config/` nor `app/data/` (besides the one intentional placeholder,
  `titledb/languages.json`) nor Python/pytest caches can land in the repo again.
- **Docker Hub vulnerability hardening**, requested directly after a scan showed 5
  critical / 30 high / 16 medium / 2 low / 1 unknown findings on the published image.
  Investigated rather than guessed: `.github/workflows/docker.yml` - the file
  `tests/test_branding.py`'s own `test_docker_image_is_published_under_the_new_dockerhub_repository`
  (a long-standing failure every run this session reported as "pre-existing,
  unrelated") expects to exist - **never actually existed in this repo's real
  history**, confirmed against the pushed `origin/main`, not just this clone. With no
  automated rebuild at all, nothing ever picked up newer Alpine/Python security
  patches after an image was pushed - almost certainly the main driver behind the
  count climbing over time.
  - **Added the missing `.github/workflows/docker.yml`**: builds and pushes the same
    four platforms (`amd64`, `arm64`, `arm/v7`, `arm/v6`) on a version-tag push, with
    `pull: true`/`no-cache: true` so it always starts from today's base image rather
    than a cached one, plus a **weekly schedule** that rebuilds `latest` from the
    same source just to pick up upstream patches even between releases - the actual
    lever against vulnerabilities silently accumulating. Needs two repo secrets to
    push for real: `DOCKERHUB_USERNAME` and `DOCKERHUB_TOKEN` (a Docker Hub access
    token, not the account password).
  - **Dockerfile now runs `apk upgrade` alongside `apk update`** before installing
    anything, so bash/su-exec and the build toolchain all come from an already-patched
    package index, not whatever shipped frozen in the base layer.
  - **Replaced `sudo` with `su-exec`** (Dockerfile and `docker/run.sh`): the image only
    ever used sudo for one privilege-drop, a job `su-exec` is purpose-built for at a
    fraction of the size - and removes sudo's own real CVE history
    (e.g. CVE-2021-3156, CVE-2023-22809) from the image entirely.
  - Could not actually pull a base image or run a live scan from this sandbox (Docker
    Hub registry access is policy-blocked here), so these are the real, verifiable
    structural fixes rather than a guessed-at vulnerability count - the real number
    will show up in Docker Hub's own scan after the next push.
  - New `tests/test_docker_hardening.py` (6 tests) plus confirmation that the
    long-standing `test_branding.py` failure is now fixed as a direct side effect.
- **Removed the dead `titledb/images.py` image cache (and its 3 orphaned test files,
  10 tests).** This module and a `/api/titledb-image/...` route it was meant to back
  arrived from an unrelated branch with no route or task ever wired up - the 10 tests
  against it were failing on every run. Before implementing the missing pieces,
  `app/tasks.py`'s own comments turned up the real story: this exact cache was already
  superseded by the newer "Local artworks" pipeline (`media.py`, `/api/media/...`,
  `download_media_task`), which is live and reads/writes artwork for every Icon/List/
  Card view and the shop API already. Finishing the old module would have stood up a
  second, duplicate image cache competing with the one actually in use, so it and its
  tests were deleted instead. Full suite is green with no replacement test needed -
  nothing calls the removed module, and the live pipeline already has its own
  coverage (`tests/test_download_media_task.py`).

## [6.2.4.29]

- **New setting: "Show game background image in Library list view"** (Ajustes →
  Organizador), requested directly. A switch, on by default (today's look is
  unchanged for anyone who doesn't touch it), that turns off each game's background
  artwork (`.list-banner-strip`) behind its row in the Library page's **List view**
  only - the small cover icon on the left (`.list-cover`) keeps showing regardless,
  as asked. Does not touch the Card grid view or a game's own detail popup, neither
  of which pairs a background with a separate icon the way the List view does.
  - New `library.management.organizer.show_background_image` setting (default
    `true`), stored alongside the rest of the Organizer section even though it's a
    display preference rather than a file-organization one, by explicit request -
    it's excluded from the organizer "naming signature" so toggling it never
    triggers a re-organize of already-organized files.
  - `app.py` passes it into the Library page as `show_game_background_image`; a new
    `SHOW_GAME_BACKGROUND_IMAGE` JS const in `index.html` gates only the
    `.list-banner-strip` append in `renderListView` - a one-line, narrowly scoped
    change next to the icon's own unconditional append.
  - New `tests/test_library_background_image_toggle.py` (default-on, persistence,
    round-trip through `/api/settings`, the JS gate itself, and translated
    label/help text) plus matching assertions added to `test_settings_i18n.py`.

## [6.2.4.28]

- **Fixed install/DLC regression on a title's own detail screen, reported against the
  Switch client directly** (Sphaira, in Discovery mode): opening a specific game and
  tapping Install did nothing - no network request at all - and that game's DLC
  showed with the base game's own id instead of its name, with no icon. The
  catalogue list was unaffected (its version display, fixed in 6.2.4.24, was already
  correct), which narrowed this to the `title(titleId:)` detail query specifically.
  Investigated the same way as the rest of this audit: cloned Sphaira's own source
  ([NaGaa95/sphaira](https://github.com/NaGaa95/sphaira)) to read the exact GraphQL
  query it fires on that screen (`TITLE_QUERY` in `ownfoil_api.cpp`) rather than
  guess, and compared it against this fork's schema and resolvers. Two compounding
  bugs, both in `app/gql/`, not upstream regressions (upstream's download mechanism
  is architecturally different and never shared this code path):
  - **`Selection.child()` (`selection.py`) returned on the first field it found with
    the requested name, instead of merging every differently-aliased selection of
    that field.** `TITLE_QUERY` nests `apps` three times under one `title(titleId:)`
    query - `base:`, `updates:`, `dlc:` - each with its own arguments and its own
    sub-selection. Only the `dlc:` alias asks for `titledb{name ...}`, so
    `resolve_title`'s `apps_sel.has("titledb")` check - built from whichever alias
    `child("apps")` happened to return first - came back false, and no DLC ever got
    its titledb row hydrated: the client fell back to the raw app id, with no icon.
    Fixed by merging sub-selections across every alias of a field, the same way this
    file already exists (identically) in upstream - a straight, exact port.
  - **`resolve_title`'s `want_apps_downloadable` flag only checked for
    `downloadableFile`, not for `downloadUrl`/`downloadSize`/`downloadExtension`
    directly - unlike `resolve_apps`'s equivalent flag, which already checked all
    four.** `TITLE_QUERY`'s `base:` alias asks for those three fields directly and
    never asks for `downloadableFile`, so `files_loaded` never got hydrated for the
    base app under this query path, `downloadUrl` resolved to null, and Sphaira had
    nothing to install - with no request ever reaching the server, matching exactly
    what was observed. `resolve_titles` (the plural query) had the identical gap;
    fixed both the same way, mirroring `resolve_apps`'s own already-correct check.
  - Two new regression tests in `tests/test_gql_sphaira_schema_compat.py`, built from
    `TITLE_QUERY`'s real aliased shape, confirmed to fail against the pre-fix code
    and pass against the fix.

## [6.2.4.27]

- **Fixed the Pending tab in `/admin/files` showing raw internal stage names**
  ("organize", "verify", "compress") instead of a human label. Flagged as a
  deliberately-unfixed finding from the 6.2.4.26 translation pass (so as not to mix
  an unrelated fix into that batch); fixed now as its own small, focused change. The
  values come straight from `tasks.STAGES`' own internal identifiers (used
  everywhere else in the codebase as plain strings) - a new `PENDING_STAGE_LABEL`
  map in `files.html`, fed by the `I18N` bridge, humanizes (and translates) them
  before they're joined into the detail column.

## [6.2.4.26]

- **Full Spanish/English translation coverage for `/admin/files`** (item 2.4 of the
  audit request). This page had zero `t()` calls - every other admin page is
  bilingual via the `ownfoil_lang` cookie, but Files was built almost entirely in
  client-side JS (filters, the file table, the duplicates/outdated comparison
  tables, the file drawer), which never passes through Jinja at all. Fixed with the
  same two-part approach: the static chrome (heading, tab descriptions, setting
  labels, toolbar) now uses ordinary `{{ t('files.xxx') }}` calls; everything built
  in JS reads from a new `const I18N = {...}` object populated server-side via `t()`
  - the exact same bridge pattern the Library page's own `index.html` already uses
    for its Card/List view text, just not previously extended to this page.
  - ~165 new `files.*` keys in `i18n.py`, with real Spanish text throughout (not
    English duplicates), matching this fork's existing tone.
  - Pure text-externalization: no behavior, layout, or visual change. The English
    text in every converted string is byte-for-byte identical to what used to be
    hardcoded, so existing tests asserting on that English text (duplicate-reason
    labels, the "Prefer larger on tie" toggle, the search placeholder, etc.) needed
    no changes.
  - New `tests/test_files_i18n.py` covering both languages for the static chrome and
    for the `I18N` bridge object, plus a couple of JS call sites that now read from
    it instead of a literal.
  - **Noticed, not fixed, per the "no cambios a ciegas" instruction:** the Pending
    tab's per-file detail text (`r._stages.join(' · ')`) shows raw backend stage
    identifiers (e.g. `organize`, `verify`, `compress`) rather than a humanized,
    translated label - this isn't a hardcoded English string to move into i18n, it's
    a small missing polish step (the stage names were never run through `humanize()`
    at all). Flagging it rather than folding it into this change.

## [6.2.4.25]

- **Added "prefer multi-content files" as a new, opt-in tie-break setting for
  automatic duplicate resolution** (`Settings > Duplicate files`), matching upstream
  2.5.0's own "Prefer multi-content files" option - but placed differently on
  purpose, per an explicit decision made for this fork: upstream checks it *before*
  verification rank, so a multi-content bundle can beat an individually-verified file
  even when the bundle itself verified worse. Here, `prefer_multicontent` only ever
  breaks a tie *after* this fork's own existing verification-rank gate has already
  narrowed the group down to files sharing the single best Valid/Repack/Corrupt
  verdict - it can never choose a worse-verified bundle over a validly-verified
  individual file. It sits first in the existing tie-break chain (ahead of the
  compression and size preferences), since none of those three settings interact:
  turning one on never turns on another, and each only ever narrows a tie the
  previous one left unsettled.
  - `app/library.py`'s `duplicate_winner_with_preferences()` gained the new
    `prefer_multicontent` parameter; `app/tasks.py`'s `resolve_duplicate_files_task`
    reads the setting (`library.management.duplicates.prefer_multicontent`, off by
    default) and wires it through.
  - New checkbox in Settings, greyed out together with the other two tie-break
    controls whenever "Automatically resolve duplicate files" itself is off.
  - Full i18n coverage (en/es) for the new setting, following the existing
    tie-break strings' own wording and level of detail.

## [6.2.4.24]

- **Fixed a game's real version showing as "v0" (or "v65536", "v131072"...) on
  `/admin/files`.** Those are the raw Nintendo version counters - multiples of 65536,
  so a perfectly normal first release ("1.0.0") is 0 - and this fork never read the
  human-readable string a game actually reports about itself ("1.0.0", "1.2.1"...),
  unlike upstream 2.5.0, which has always had this. Ported the missing piece: at
  identification time, each content's own Control NCA is now also read (a small,
  separate, best-effort pass alongside the existing CNMT identification - a failure
  reading it, or a DLC that carries no Control NCA at all, never affects whether
  identification itself succeeds), its display version is stored on the matching
  `Apps` row (new `display_version` column + migration), exposed over GraphQL as
  `App.displayVersion`/`AppVersion.displayVersion` (previously present but hardcoded
  to always return `null`), and preferred by `/admin/files`' own version column,
  falling back to the old `v{appVersion}` form exactly as before when nothing has
  been read yet - matching upstream's own fallback behaviour.
  - **Only ownfoil's own NACP-parsing module was ported** (the part that reads
    `control.nacp`'s DisplayVersion field), trimmed to that one field - upstream's
    version of it also reads per-language name/publisher/icon out of the same
    container, which this fork already gets from titledb instead and has no use for
    here. The NCA-opening mechanics it needed (reading a Control NCA out of a
    `meta_only`-opened container by its own partition table) were ported alongside it
    in `containers/container.py`, since nothing here previously had a reason to open
    anything but the CNMT.
  - **Existing identified files are not retroactively affected.** `display_version`
    only gets filled in the next time a file is (re-)identified - there is no bulk
    backfill task, deliberately: this fork already discourages unnecessary
    re-scanning of a working library, and adding one here would be exactly that.
    Forcing a re-identify of an already-identified file (there isn't a dedicated
    button for this today - deleting and re-adding it, or clearing `identified`
    directly, both work) is what picks the version up for a file added before this
    change; anything identified from now on gets it automatically, with no extra step.
  - A transient Control NCA read failure on a *later* re-identify of an already
    versioned file can never blank out a value a previous pass already found - the
    database upsert only overwrites `display_version` when the new read actually
    produced one.

## [6.2.4.23]

First batch from the full comparison-audit against upstream 2.5.0 (duplicate deletion,
local/remote access, installs, compression, admin/files covers, Docker note). Each item
below was independently verified against the real code of both before changing anything.

- **Fixed duplicate files reappearing after a rescan.** `_delete_file_from_disk` used to
  swallow an `os.remove()` failure (permissions, a locked handle, a flaky network mount)
  with nothing but a log line, and its three callers (the Files page's per-row Delete
  button, and the admin app/title delete actions) deleted the database row regardless -
  so the row vanished while the physical file stayed exactly where it was, and the next
  scan picked it back up and reported it as a "new" duplicate. Each caller now only
  deletes a row once its file is actually confirmed gone from disk; a file that fails to
  delete keeps its row (and, for `deleteAppRecord`/`deleteTitleApps`, keeps that one
  app's row too, without blocking any of its siblings from completing normally).
- **Fixed "the shop did not indicate how to install this" on Sphaira.** Its file lookup
  resolved by filename alone, ignoring which library/folder the request was actually for
  - so two files sharing a filename across libraries or folders (organize-by-language
    makes this common) could resolve to the wrong one, or fail to resolve at all. It now
  matches the full virtual path against every library, same as upstream, while keeping
  this fork's own response/download-counting code.
- **Fixed the Files admin page's manual Compress/Verify buttons doing nothing with the
  matching Settings toggle off.** `compress_file_task`/`verify_file_task` lost their
  `manual` bypass parameter at some point - the global "compression enabled"/"automatic
  verification" toggles are meant to control only the automatic pass during a scan,
  never whether an admin can trigger either one by hand.
- **Fixed the Setup page's "Local"/"Remote" connection-instructions tabs** disappearing
  down to just "Remote" (and the local address going blank) whenever viewed through the
  configured public/remote host - same root cause as the Discovery section fixed in
  6.2.4.22, just a second place it was wired the same way. Both tabs, and a real local
  address, now always show: which URL loaded the page says nothing about which access
  method actually works for the Switch.
- **Fixed missing covers/icons on the Pending, Duplicates and Outdated updates tiles.**
  Unlike the main Files table, these three never ran their rows through the `apps`
  hydration the Files admin page's JS actually queries (`apps { title { name iconUrl
  } }`) - so a file's `apps` always came back empty there, even fully identified ones,
  and the UI fell through to its "?" placeholder.
- **Restored the Docker discovery note's styling on `/admin/services`** to match
  upstream's: a yellow warning alert with an icon and `<code>`-highlighted flags
  (`--network host` / `network_mode: host`), instead of a plain blue box with the
  markup stripped - while keeping this fork's own longer wording (it also covers the
  Windows firewall, which upstream's note doesn't mention).

## [6.2.4.22]

- Fixed the Setup page's entire "Discovery" section silently disappearing (not just
  its banner - the heading, the instructions, everything) whenever an admin viewed
  `/setup` through their configured public/remote domain instead of a local address,
  even when they were on the same WiFi as their Switch at the time. The section was
  gated by `show_local_tab`, which exists to hide the *local address/port* fields
  (meaningless once you're definitely remote) - but Discovery itself is a LAN UDP
  broadcast capability of the server, unrelated to which URL the admin's own browser
  happened to be using to view the page. The Discovery heading is now shown whenever
  Discovery is enabled (or the viewer is an admin, same as before) regardless of
  `show_local_tab`; the local address/port instructions elsewhere on the page keep
  their original, correct gating.

## [6.2.4.21]

- Ported the Files page's "Duplicates" tab to upstream 2.5.0's own comparison-table
  design: one column per physical copy (instead of a plain stacked list of
  neutral "Keep this copy"/"Delete" button pairs), with rows for the attributes
  that tell the copies apart (version, verification, compressed, organized,
  added, size), the recommended copy's column marked green "Keep", a losing
  copy's column marked red "Delete" with the specific reason it lost, and the one
  attribute cell that explains that reason highlighted amber - all ported
  directly from upstream's own template/JS. A tied group with no recommended
  copy (this fork's own settings left the tie unresolved - the exact Torchlight
  III scenario reported) still renders every column neutrally with no fabricated
  winner, same as before. Also added the bottom summary bar's "Delete N file(s)"
  bulk action (the button and its markup already existed in `runRemoval()`, it
  was simply never wired to anything), and a second "Prefer larger on tie"
  toggle next to "Automatic resolution", matching upstream's own two-control row.
  The group header's icon placeholder is now a real title icon when one is
  available, same oversight fix.
  **Deliberately not** ported 1:1: upstream's reason for a losing copy is always
  "Added later" (it breaks ties by `addedAt` with a separate "Prefer bundles"
  setting) - this fork's own `duplicate_winner_with_preferences()` never compares
  timestamps at all, it ranks by verification status (Valid > Repack > Corrupt),
  then its own compression preference, then size if "prefer larger on tie" is
  on. So the reason text here says "Worse verification" / "Not the preferred
  compression" / "Smaller copy" (whichever one this fork's logic actually used),
  falling back to a generic "Not the recommended copy" only when none of those
  individually explains it. Upstream's separate "Prefer bundles" setting has no
  equivalent here and was not added - this fork already has its own, different
  tie-break settings (compression preference, prefer-larger-on-tie) built
  earlier in its own history, and this change is a visual/interaction port, not
  a replacement of that feature set.

## [6.2.4.20]

- Fixed the Files page's "Content" filter chip (Base/Update/DLC/Bundle) silently
  doing nothing: `FileFilter` had no field for it at all, so picking "Base" kept
  showing Update/DLC rows too, since the server-side `files` query the table
  actually fetches from was never constrained - the client-side match function
  the chip used was wired up for a filtering path the Files page's "all files"
  table doesn't take (that path is only used for the duplicates/outdated groups
  view). Added `FileFilter.content` (`[FileContentKind!]`, matching ANY of the
  given app types or `MULTI` for a bundle file) and wired the chip to it.

## [6.2.4.19]

- Fixed the Files page's "Duplicates" tile undercounting: it only summed a group
  toward the count/bytes-to-free figures when the backend had a single confident
  automatic pick (`recommendedKeepId`), so a group tied at the best verification
  rank (two files both `Repack`, say - common without "Prefer larger on tie"
  turned on) silently contributed nothing to the tile, even though the group was
  still listed below for manual resolution. The tile now counts every duplicate
  group, estimating "to free" conservatively (everything but the single largest
  copy) when there's no recommended winner yet.

## [6.2.4.18]

- Settings > Workers now has a "Max concurrent network tasks" control, alongside
  the existing "Worker count" and "Max concurrent I/O tasks" ones. The backend for
  this was already fully built and already working - a per-concurrency-group task
  cap (`tasks.blocked_task_names`, with `download_title_media` already registered
  under the `net` group) and a real worker-process pool that rescales itself when
  settings change - it just had no default limit and no way to set it from the UI,
  so artwork downloads ran with no cap at all. `POST /api/settings/worker` now
  validates and stores every concurrency group `DEFAULT_SETTINGS['worker']
  ['group_limits']` declares (`io` and now `net`), not just `io`, with the same
  per-field validation either way.
- Settings page: toggles that render as plain checkboxes instead of on/off
  switches now match upstream 2.5.0 again (`Delete older updates`, `Compress
  files`, `Verify files`, `Enable organizer`, and the three client-enabled
  toggles, plus this fork's own `Web downloads` and `Auto-resolve duplicates`) -
  they'd silently lost their switch styling at some point; secondary/nested
  options (`Remove empty folders`, `Windows compatible filenames`, `Encrypt
  shop`, etc.) correctly stay plain checkboxes, same as upstream.
- Settings page: several help texts lost their `<code>`-highlighted technical
  terms (`NSZ`/`XCZ`, `NCA`, `https`, `X-Forwarded-Proto`, the template attribute
  syntax, the scheduler interval format) when they were moved into translatable
  i18n strings - restored across both English and Spanish.

## [6.2.4.17]

- Fixed a regression from 6.2.4.16: `/api/media/...` (the web library's own cover
  art requests) returned 401 on a private shop even for a signed-in admin, because
  the route's `file_access` gate only ever checked HTTP Basic Auth, never the
  session cookie a plain `<img src>` request carries. It now goes through
  `auth.resolve_shop_caller` - session, Basic Auth, or a public shop, admin bypass
  included - the same gate GraphQL has used since 6.2.4.13.
- `Title.screenshots` is now a parametrized `screenshots(size:): [Image!]` field,
  matching upstream 2.5.0's `icon`/`banner` shape instead of the flat `[String!]`
  it shipped as - Sphaira's title-detail query asks for two renditions of the same
  list (a small one for a grid, a larger one for a viewer) in one query, which the
  flat shape couldn't express. Resolved through Local artworks the same way
  icon/banner are, falling back to the titledb hotlink at its native size for any
  screenshot with no local copy.
- Added `App.downloadUrl` / `downloadSize` / `downloadExtension`, so a shop
  client's catalogue query can read where to download an app and what it is
  without a separate `downloadableFile` round trip. Deliberately scoped down from
  upstream's opaque-token, multi-file dedup-preference system: these name the same
  file `downloadableFile` already resolves (an app's first owned file) and reuse
  the existing `/api/get_game/<id>` route, rather than a new token-addressed one.

## [6.2.4.16]

- Unified artwork on one pipeline, matching upstream 2.5.0: the web library page
  (Card/Icon/List views) now reads `icon`/`banner` straight off the same GraphQL
  `titledb`/`title` fields a shop client (Sphaira, Tinfoil) already does, resolved
  through Local artworks (`/data/media/`) or the titledb hotlink otherwise. Removed
  the separate, older `/data/titledb/images/` cache it used to go through instead
  (`titledb/images.py`, the `/api/titledb-image` route, the `cache_titledb_images`
  task) - there is now exactly one place artwork is downloaded to and exactly one
  place it's read from, for every page and every client alike.
- Scanning or re-identifying a file now also checks that its title's artwork is
  downloaded, instead of only picking it up on the next scheduled titledb refresh -
  a freshly-added game's cover used to stay hotlinked (or blank, until the next
  refresh) even with Local artworks on.

## [6.2.4.15]

- Fixed Sphaira's real native query failing GraphQL schema validation outright on
  this fork, even after it could reach `/api/graphql` and authenticate (6.2.4.11,
  6.2.4.13) - the query itself asked for fields the schema didn't have. Added:
  - `StringFilter.notIn` (`appId: {notIn: [...]}` etc.), the exclusion counterpart
    of the existing `in`.
  - `App.displayVersion` / `AppVersion.displayVersion` - the human-readable version
    string (e.g. `"1.2.0"`) a game's own Control NCA reports, as upstream exposes
    it. Always `null` on this fork for now: nothing here extracts it from a file's
    container yet, unlike upstream, but the field now exists so a client asking
    for it gets a clean `null` instead of a schema error.
  - `App.latestOwnedVersion` - the newest owned version behind an app, keyed the
    same way `versions` already is.
  - `Title.icon(size:)` / `Title.banner(size:)`, matching upstream's parametrized
    `Image`/`ImageSize` fields (`ORIGINAL`/`THUMB`/`CLIENT`/`SCREEN`) - selects
    whichever rendition Local artworks (6.2.4.12/6.2.4.14) has on disk, or the raw
    titledb hotlink at its native size when there's no local copy yet (or Local
    artworks is off). `screenshots(size:)` was deliberately not added: it wasn't
    in the failing query, and it would collide with this fork's existing flat
    `screenshots` field name.

## [6.2.4.14]

- Fixed the browser tab/navbar (and the Sphaira handshake's own `name` field)
  still saying plain "Ownfoil" on an install whose `settings.yaml` was carried
  over from upstream Ownfoil, or from an early build of this fork before its own
  blank-by-default shop name was introduced: that file already had the shop name
  saved as upstream's exact stock default ("Ownfoil"), which the usual
  missing-keys-only settings merge can never fix, since the key was never
  missing - only stale. It's now migrated once, automatically, to this fork's own
  default ("" - already rendered everywhere as "Ownfoil-Plus"); a shop
  deliberately renamed back to plain "Ownfoil" afterward is never touched again.
  The Basic Auth challenge on a private shop (the handshake, GraphQL) now also
  says "Ownfoil-Plus" in the realm, for the same reason.
- Local artworks (Settings) now downloads and stores all four artwork sizes
  (original, thumb, client, screen), same as upstream, instead of only the one
  rendition actually linked from GraphQL - the disk-usage table reports all four
  columns too. Serving is unchanged: the fork's schema still exposes one
  icon/banner/screenshot URL per title rather than several selectable sizes, so
  only the `client` rendition is ever linked - but every size is on disk, ready
  for the day that schema grows a selectable size, and the usage breakdown now
  matches the real shape upstream's own does.

## [6.2.4.13]

- Fixed the real bug behind "detects the shop but shows no games": once 6.2.4.11
  let a console get past the `OPTIONS /` handshake, every GraphQL query right after
  it still came back 401. `/api/graphql`'s own gate only ever checked the browser's
  login session cookie - never the Basic Auth header a console client (Sphaira,
  Tinfoil) sends instead, and never let a public shop's anonymous reads through
  either, even though every other shop-facing route (file downloads, the handshake
  itself) already does both. Confirmed against a real shop's own access log:
  `OPTIONS /` now 200s, but the following `POST /api/graphql` still 401'd for the
  same request. GraphQL now authenticates the same way those other routes do -
  session cookie or Basic Auth, and a public shop needs neither - while admin-only
  mutations stay gated exactly as before, independent of this fix.

## [6.2.4.12]

- Added "Local artworks" to Settings, ported from the real production shop: a
  "Download artwork locally" toggle and a collapsible disk-usage breakdown
  (icon/banner/screenshots, by stored rendition, with a running total and file
  count). Once enabled, each title's icon, banner and screenshots are downloaded
  once into a local, content-addressed store and served back from `/api/media/...`
  instead of hotlinked from Nintendo's own CDN - so a console reading them through
  the shop API (a native "Ownfoil" client, concretely Sphaira once 6.2.4.11's
  handshake fix lets it connect) never talks to Nintendo directly, and the fork's
  own web UI benefits the same way for free. A dead or slow source URL is retried
  on its own backoff schedule (up to 3 attempts) without failing the rest of that
  title's artwork, and never blocks the next titledb refresh from trying again.
  Simplified from upstream's version: one serving rendition (`client`) instead of
  four, since this fork's GraphQL schema already exposes a single icon/banner URL
  and screenshot list per title rather than several selectable sizes - so the
  substitution happens transparently inside the existing fields, with no schema
  change for any existing consumer. Known gap: unlike upstream, there is no
  automatic sweep of local files for titles removed from the library - disk usage
  only grows until a future release adds one; the disk-usage panel at least makes
  that visible.
- Fixed Settings so the duplicate tie-break controls ("prefer the larger file" /
  "prefer compressed vs. uncompressed on a tie") visually disable themselves when
  "Automatically resolve duplicate files" is off, matching the backend's own
  already-correct behavior (both are already inert server-side once auto-resolve
  is off - only the UI wasn't showing that).

## [6.2.4.11]

- Fixed the real bug behind Sphaira "detecting but not connecting" to a shop: `/`
  never answered the `OPTIONS` handshake Sphaira's native "Ownfoil" menu sends
  before anything else (server name, uid, protocol version, capabilities) - Flask
  silently auto-answered it with an empty 200, which Sphaira cannot parse, so it saw
  the server respond but never went on to call the GraphQL API. Confirmed against a
  real shop's own access log: only repeated `OPTIONS /` with no `POST
  /api/graphql` ever following, unlike a working upstream shop's log for the
  same console. `/` now answers this handshake itself (same shape as upstream's),
  gated the same way as every other shop endpoint - open on a public shop, Basic
  Auth with shop access otherwise.

## [6.2.4.10]

- Files admin page rebuilt again to match the real production Files page exactly:
  6 tiles (All files/Unidentified/Verification issues/Duplicates/Outdated
  updates/Pending, dropping the standalone "Not organized" tile), a search box +
  "+ Filter" dropdown + top/bottom pagination (replacing the filter-chip-only
  toolbar), and a "Console keys" status indicator next to the Unidentified/
  Verification panels.
- The previously-deferred "Outdated updates" and "Pending" tiles now have full,
  real functionality rather than placeholders:
  - **Outdated updates** lists, per title, every owned update file older than the
    newest owned version, with per-file size and a one-click bulk delete (files
    inside a multi-content bundle are never offered here, same guard the
    automatic "delete older updates" setting already honors).
  - **Pending** lists every file the automatic pipeline still owes work to
    (identify/verify/compress/organize) given the current Settings, so stuck or
    newly-scanned files are visible instead of silent.
- Every file row (and the Duplicates/Outdated groups) now has real
  Retry/Verify/Compress/Decompress/Delete actions, each backed by its own
  mutation and polling the task it starts so the row shows busy and surfaces a
  failure message instead of going quiet.
- New `outdatedUpdateGroups` and `pendingFiles` GraphQL queries and a
  `retryIdentification` mutation back the above; the `verificationStatus` file
  filter now accepts a list of statuses instead of one, so the "Verification
  issues" tile can match every broken-or-unverified status in a single query
  (the Stats page's own verification drill-down was updated for this too).

## [6.2.4.9]

- The Setup page is now fully translated to Spanish again (it had briefly gone
  English-only in the 6.2.4.8 rebuild), and the connection details that matter most -
  the server name, local/remote address, username and password shown in each card's
  table - are highlighted in pink again, like they were before that rebuild.

## [6.2.4.8]

- Setup page rebuilt to match upstream Ownfoil 2.5.0's current layout: Sphaira gets its
  own card first (native "Ownfoil" menu, discovery-aware instructions), and Tinfoil,
  Sphaira's older file-browser mode and CyberFoil moved into a collapsed "Legacy
  clients" section below it, instead of three equal tabs.
- Files admin page rebuilt to match upstream 2.5.0's layout and depth: tiles for
  All/Unidentified/Verification issues/Not organized/Duplicates, filter chips (format,
  verification, identified-by, compressed, organized, library), a search box, and a
  side detail drawer per file. Duplicate groups are now reviewed and resolved directly
  on this page (each copy's verification/compressed/organized state, a recommended
  copy to keep when it's safe to say, and a one-click "keep this copy" per file) -
  the Stats page's own duplicate-resolution feature still works exactly as before and
  both act on the same data.
  Not yet ported from upstream's 2.5.0 Files page, deliberately left for a follow-up
  rather than rushed: the separate "Outdated updates" and "Pending" tiles/tabs, and
  per-file Verify/Compress/Decompress/Retry actions - these reach deep into this
  fork's own task-pipeline internals (different from upstream's), and porting them
  safely needs its own pass rather than a blind copy.

## [6.2.4.7]

- New "Files" admin page, ported from upstream Ownfoil 2.5.0: a flat, searchable and
  filterable (by library, format, verification status) list of every tracked file,
  with clickable tiles for All files / Unidentified / Verification issues / Not
  organized, and a delete action per file. Duplicate files keep being reviewed and
  resolved from the existing Stats page - this page's "Duplicate groups" tile links
  there instead of duplicating that feature with a second, less capable UI.
- Setup page's Sphaira instructions rewritten to match the client's current built-in
  "Ownfoil" menu (Menu -> Menus -> Ownfoil -> Discover local servers), replacing the
  old, outdated manual-mount workflow. Shows the "Discovery is enabled" banner and
  skips straight to "connect and discover" when LAN discovery (6.2.4.6) is on, falls
  back to manual add-server instructions when it's off.

## [6.2.4.6]

- A new, configurable Shop name (Settings > Shop): replaces "Ownfoil-Plus" in the
  navigation bar, the browser tab, and the app name when added to a phone's home
  screen, and is handed to connected clients. Leave it empty to keep the default.
- LAN discovery, ported from upstream Ownfoil 2.5.0 and adapted to this fork's own
  settings/branding: a new "Services" admin page with a toggle so Sphaira and other
  compatible clients can find this shop on the local network automatically, with no
  address or port to type in on the console. Needs host networking in Docker to
  actually reach the LAN - see Install.md.
- Fixed a pre-existing bug where, on a server's very first boot (no `settings.yaml`
  yet), the in-memory default settings object could end up mutated in place instead
  of copied, which could leak one test/run's settings into another's initial
  defaults within the same process.

## [6.2.4.5]

- Clicking a row in the Stats page's "Libraries" table now opens a detail view of
  every title in that library - Base/Updates/DLC laid out the same way the Library
  page's List view does, Updates and DLC grouped into collapsible sections.
- A search box on all three of the Stats page's drill-down views (Libraries,
  Verification Status, App Types), to find a specific title or file in a long list
  without scrolling.
- Two new admin actions on each title in that new library detail view: clean a
  title's tracked database record without touching its file (for recovering a
  stuck or inconsistent entry), or delete the file from disk and its record
  together, for real. Both work on a single update/DLC on its own, or on a base
  game with the choice to sweep every update and DLC under it at the same time.
  Neither needs a settings toggle turned on first anymore - just admin access.
- Fixed the "App Types" drill-down (added in 6.2.4.4) opening to a broken, stuck
  modal that couldn't be closed without reloading the page.

## [6.2.4.4]

- Clicking a row in the Stats page's "App Types" table (Base/DLC/Update) now shows
  exactly which titles account for the gap between "Registered" and "Owned" - e.g.
  a title an update or DLC was scanned for, but the base game's own file never was.
- "Verify library now" is "Verify pending files" again - a quick, light action that
  only checks new or never-verified files, the same thing the automatic pipeline
  already does on its own.
- The "Danger zone" section is now "Clean Library", with a clearer explanation:
  it resets tracked file data so the library can be rediscovered from scratch, and
  never deletes anything from disk.

## [6.2.4.3]

- Card and Icon views now use the same local artwork cache the List view already
  did, instead of fetching covers straight from the remote catalogue.
- Clicking a game's cover in Card or Icon view now opens the same detailed info
  panel the List view's info button does.
- Release dates and file sizes in that info panel are now formatted properly
  (`24/06/2022`, `12.9 GiB`) instead of showing the catalogue's raw values.
- A short activity history on the Tasks page, showing the most recent completed
  operations (a scan, a verify pass, a titledb update, ...) - previously nothing
  was kept once a task finished.
- A pagination bar at the top of the Library page too, not just the bottom.
- The List view's per-game banner now shows behind the whole card, the way it did
  originally, instead of a shorter strip up top.
- "Verify library now" is now an explicit, confirmed action that re-checks every
  file, including already-verified ones - the automatic pipeline already picks up
  new or never-verified files on its own, so the button now does the one thing it
  couldn't before.
- Fixed a real data-loss risk: an unstable or not-yet-reconnected network share
  (or a drive still mounting at startup) could get files' tracked verification
  state wiped and treated as brand new once it came back, instead of being left
  alone until the drive was reliably back.

## [6.2.4.2]

- Users with shop access (not just admins) can now use the List view's download
  button, as long as an admin has turned it on in Settings.
- Card and Icon views now go through the same local artwork cache the List view
  already used, instead of fetching covers straight from the remote catalogue -
  faster repeat loads, and covers keep working even if that remote host is slow or
  unreachable.
- Clicking a game's cover in Card or Icon view opens the same rich info panel the
  List view's info button does - genre, players, rating, languages, file size, and
  screenshots.
- Release dates and file sizes in that info panel are now formatted properly
  (`24/06/2022`, `12.9 GiB`) instead of showing the catalogue's raw values.
- The "Updates" version-history popover in Card view now shows one entry per line
  instead of running them all together.
- A duplicate-file tie between a compressed and an uncompressed copy can now be
  resolved by that alone, separately from the existing "prefer the larger file"
  setting - useful since a compressed file is always going to be the smaller one.
- The same compressed/uncompressed preference is also available for the manual
  "resolve all by size" bulk action.
- The Duplicate Files section on the Stats page is now always visible, not just
  when there happens to be a duplicate to resolve.
- Fixed a real bug where dismissing a failed task that had its own failed children
  (e.g. after an unclean restart) silently failed instead of clearing the list.
- Fixed task progress and the Worker cards not updating during a very large backlog -
  the currently-running task could fall outside what the page was shown, so it
  looked stuck at 0% or idle even while actively working.

## [6.2.4.1]

- Editable game info: fix or fill in a title's name, developer, description, and
  other details by hand from the List view's info panel, when the catalogue is
  missing or wrong about them - it stays that way even after the catalogue updates,
  changing only the specific fields you set.
- A filter in the List view to quickly find titles that are complete, incomplete, or
  have a corrupt or repack file anywhere in them (base, update, or DLC).
- Colored badges in the README so each one is visually distinct at a glance.

## [6.2.4.0]

Initial release of this fork, bringing together everything built on top of
upstream Ownfoil:

- Full Spanish/English web interface, switchable anytime from the navbar.
- A List view showing every game with its updates and DLC in one place, including
  what's still missing from the library.
- Local caching of game artwork, so covers and banners keep working even if the
  remote image host is unreachable.
- Duplicate file detection and resolution - automatic when verification gives a
  clear, unambiguous answer (with a choice of preferring the larger file), and
  manual otherwise, one at a time or in bulk.
- A safety fix to the file organizer: a same-size collision at the target filename
  no longer gets silently deleted, in case it turns out to be a different (better
  or worse) file that merely happens to weigh the same.
- A direct "Verify library now" action on the Stats page.
- Settings export/import from the web UI.
- A dedicated Docker image, `estebankzl/ownfoil-plus`, published for
  `linux/amd64`, `linux/arm64`, `linux/arm/v7`, and `linux/arm/v6`.
