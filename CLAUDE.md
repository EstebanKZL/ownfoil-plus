# CLAUDE.md

Guidance for Claude Code working on **Ownfoil-Plus** - a self-hosted Nintendo Switch
library manager and shop (fork of [a1ex4/ownfoil](https://github.com/a1ex4/ownfoil)),
maintained by EstebanKZL at `github.com/EstebanKZL/ownfoil-plus`, published as the
Docker image `estebankzl/ownfoil-plus`.

## Working with the maintainer

- **Talk to the maintainer in Spanish** (rioplatense, "vos"). Code, comments, commit
  messages and `CHANGELOG.md` are in **English**.
- The UI is bilingual: every user-facing string lives in `app/i18n.py` with both `en`
  and `es` entries (Spanish uses voseo: "Elegí", "Probá", "Revisá"). Never hard-code
  UI text in templates or JS - templates use `{{ t('key') }}`, JS gets strings through
  each page's `I18N` object (`{{ t('key') | tojson }}`) or a JSON `<script>` block.
- The maintainer works by stages and screenshots: they send a list of things to polish
  with screenshots; group related items into one version, explain the plan briefly,
  then implement, verify in a browser, and open a PR.
- **Every change ships as a branch + PR to `main`**, never a direct push to `main`.
  After CI passes, ask whether to **"Fusionar y publicar"** (squash-merge, then tag and
  release) or **"Solo fusionar"** (merge only, publish later). Do not tag/publish
  without that go-ahead: a tag publishes a public Docker image.

## Versioning and release

- Version lives in `pyproject.toml` (`6.2.5.N`); bump N once per PR and add a
  `## [6.2.5.N]` entry at the top of `CHANGELOG.md` explaining the *why*, not just the
  what (that's the established style - read a few entries first).
- PR descriptions in Spanish, ending with `🤖 Generated with [Claude Code](https://claude.com/claude-code)`;
  commits end with a `Co-Authored-By:` line for the model.
- Merge with `gh pr merge N --squash`. If a second PR was branched from the first, after
  squash-merging the first: `git rebase --onto origin/main <last-commit-of-first> <second>`
  and `git push --force-with-lease` before merging it.
- Publish: `gh release create 6.2.5.N --target <full SHA> --notes-file <notes>` (needs
  the **full** SHA). The tag triggers `.github/workflows/docker.yml`: tests, then a
  multi-arch build (amd64, arm64, arm/v7, arm/v6) pushed as `6.2.5.N` and `latest`.
  It also rebuilds `latest` every Monday.
- If Docker Hub login fails with "malformed HTTP Authorization header", a repo secret
  (`DOCKERHUB_USERNAME` / `DOCKERHUB_TOKEN`) has a stray newline/space. Only the
  maintainer can reset secrets (`gh secret set ...`); then `gh run rerun <id> --failed`.

## CI and automation

- `tests.yml` - full pytest suite on every push/PR (Python 3.14, ~5 min).
- `security.yml` - on PRs and weekly: `pip-audit -r requirements.txt` and a Trivy scan
  of the built image (fails on fixable CRITICAL/HIGH); also checks pip is not in the
  image and lists urllib3 copies.
- `docker.yml` - publish on tags / weekly (see above). `dockerhub-description.yml`
  syncs `DOCKERHUB.md` to Docker Hub.
- **Dependabot** (`.github/dependabot.yml`) opens weekly PRs for pip and the base
  image, monthly for actions. Review: check CI, read the changelog of majors.

## Running locally (Windows dev machine)

- System Python is 3.15, which **cannot install `zstandard==0.25.0`** (no wheel, needs
  Visual Studio). Use a Python 3.13 venv (e.g. `uv venv --python 3.13`, then
  `uv pip install -r requirements.txt pytest`).
- Run tests with `PYTHONUTF8=1` (some tests open files without an encoding and fail
  under cp1252): `PYTHONUTF8=1 python -m pytest -q -p no:cacheprovider -W ignore`.
  The full suite (~2,300 tests) takes ~20 min on Windows; run the affected test files
  first, the full suite in the background before committing.
- Run the app: `python -m ownfoil.cli <data-dir> --no-browser` (serves on port 8465;
  `USER_ADMIN_NAME` / `USER_ADMIN_PASSWORD` env vars create an admin). On Linux/Docker
  the entrypoint is `app/run.py` (gunicorn + worker pool).
- No Docker on the dev machine: image changes are verified by `security.yml` in the PR.
- Verify UI changes in a browser (desktop and 375px mobile, light and dark theme)
  before opening the PR.

## Architecture (app/)

Flask + SQLAlchemy (SQLite, WAL) + Strawberry GraphQL, with a task queue run by worker
processes. Modules use **flat imports** (`from db import *`, `import tasks`), not a
package - `tests/conftest.py` puts `app/` on `sys.path`.

- `app.py` - Flask app, routes (web pages, REST `/api/...`, `/metrics`, `/sw.js`,
  `/manifest.webmanifest`), shop handshake. `/api/graphql` -> `gql/`.
- `auth.py` - users, login (rate-limited, safe `next`), `access_required('admin'|'shop')`,
  Basic Auth for console clients.
- `db.py` - models (`Files`, `Apps`, `Titles`, `Task`, `TaskHistory`, `DownloadEvent`,
  ...) and DB helpers. Schema changes need an **Alembic migration** in
  `app/migrations/versions/` (current head: `d5e6f7a8b9c0`) *and* the model change
  (new installs use `create_all`). `tests/test_download_history.py` asserts the head.
- `tasks.py` / `worker.py` / `worker_pool.py` - task registry (`@register_task`),
  enqueue/dedup, scheduled tasks via `run_after` (stored in **UTC**; use
  `tasks.utc_offset()` for local time), daily `scheduled_maintenance`.
- `library.py`, `titles.py`, `titledb/` - identification, organizer, TitleDB.
- `clients/` - Tinfoil, Sphaira, CyberFoil shop protocols (captured fixtures in
  `tests/captures/`).
- `settings.py` + `constants.py` (`DEFAULT_SETTINGS`) - `settings.yaml`; new keys go in
  `DEFAULT_SETTINGS` (unknown keys are pruned on load).
- Feature modules: `notifications.py` (Discord/Telegram/ntfy/webhook, batched),
  `backups.py`, `uploads.py` (resumable chunked uploads), `metrics.py` (Prometheus),
  `media.py` (local artwork), `discovery.py` (LAN UDP).
- Front-end: Jinja templates + Bootstrap 5.3 + jQuery, **vendored** in
  `app/static/vendor/` (no CDNs - the UI must work offline on a LAN). Shared JS in
  `app/static/js/` (`theme.js`, `search.js`, `pwa.js`, `upload.js`, `scroll-limit.js`,
  `library-common.js`, `charts.js`, `format.js`), and each big page's own script there
  too (`library.js`, `game.js`, `stats.js`, `dashboard.js`, `files.js`, `tasks.js`,
  `settings.js`). Colors are design tokens in `app/static/css/tokens.css`; styles in
  `app/static/style.css`.

## Conventions and gotchas

- **One bare inline `<script>` per page.** Several tests (`test_*_i18n.py`) assert each
  page has exactly one `<script>...</script>` without attributes, holding its `I18N`
  object and server values; the page's logic lives in `app/static/js/<page>.js`,
  loaded after it, and data goes in `<script type="application/json" id="...">` blocks.
  Tests that check page JS read the static file.
- Two theme axes on `<html>`: `data-bs-theme` (light/dark, dark default) and
  `data-style` (joycon/ownfoil/neon; the admin's default from settings, each browser
  can pick its own). Every color is a `--op-*` token in `tokens.css` with one meaning
  (ok green, wait amber, fav gold, danger red, info blue; `--op-nav` is the style's
  accent) - never hard-code colors. Cards use `.surface`; game cards `game-surface`.
- Long lists: `limitVisibleRows(container, rowSelector, n)` from `scroll-limit.js`.
- Settings sections have anchor ids (`#Authentication`, `#Maintenance`,
  `#Notifications`, ...) used by the dashboard and the Ctrl+K search
  (`templates/nav.html` holds the searchable page list - update it with new sections).
- Secrets never in code: Flask `SECRET_KEY` comes from `OWNFOIL_SECRET_KEY` or
  `config/.secret_key`. `/metrics` needs admin or `OWNFOIL_METRICS_TOKEN`.
- `requirements.txt` and `pyproject.toml` must pin **identical** versions
  (`tests/test_dependency_security.py` checks it).
- The Dockerfile installs and cleans up in one `RUN` and uninstalls pip at the end;
  keep `apk upgrade` (tested in `test_docker_hardening.py`).
- Write files with LF line endings; on Windows don't rewrite files with Python text
  mode without `newline=''` (it produced CRLF diffs before).
- `.gitignore` ignores `/app/data/*` except `app/data/titledb/languages.json`, which
  must stay tracked (Settings reads it before TitleDB downloads).

## Docs to keep in sync

`CHANGELOG.md` (every PR), `Usage.md` (user-facing behavior and settings reference),
`Install.md` (env vars, reverse proxy, Prometheus), `DOCKERHUB.md` / `README.md`
(feature lists, occasionally).

## Status and pending work

Done through 6.2.5.47: security hardening, CI, health check, offline UI, notifications,
daily maintenance + backups, download history, resumable web uploads, dashboard, PWA,
light/dark theme, Ctrl+K search, mobile layout, DB indexes, Prometheus metrics, UI
polish, dependency/image vulnerability fixes, Dependabot, the SLMW-inspired redesign
(tokens, three styles, flat nav, library, game page, stats/dashboard, admin pages,
Settings index) with every big page's JS moved to `app/static/js/`.

Postponed - **remind the maintainer of these when a round of work wraps up**:

1. **Save backups from Sphaira** - the `backup_access` permission and the handshake's
   `save_backup` / `resumable_upload` features are placeholders; depends on the client
   supporting it.

Not yet verified by a person: installing the PWA in a real Chrome/Edge (on
`localhost` or HTTPS), and JPEG artwork end-to-end on an arm/v6-v7 device.
