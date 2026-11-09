// One game's page (templates/game.html). The page renders TITLE_ID, the viewer flags
// and the I18N strings in its one inline script; library-common.js brings the shared
// GraphQL and badge helpers.

// One request for everything the page shows. `files` is admin only: the schema
// answers null to anyone else, and `downloadableFile` is the narrow version every
// shop-access viewer may see (what a download button needs, nothing more).
const GAME_QUERY = `
    query Game($titleId: ID!) {
        title(titleId: $titleId) {
            titleId name intro description developer publisher releaseDate
            bannerUrl iconUrl size category numberOfPlayers rating languages region
            requiredFirmware
            availableVersions { version requiredFirmware }
            screenshots { url }
            ownership { haveBase upToDate complete }
            apps(owned: true) {
                appId appType appVersion releaseDate
                downloadableFile { id size verificationStatus format contents }
                files { id filename size extension }
            }
            updateApps: apps(appType: [UPDATE]) {
                appId appVersion releaseDate owned
                downloadableFile { id size verificationStatus format contents }
            }
            availableDlc {
                appId version
                titledb { name description iconUrl bannerUrl releaseDate size }
            }
        }
    }`;

let game = null;     // the loaded title, for the actions (download all, edit)

/** Show one of the page's states - loading, not found, error - or the game itself. */
function gameState(state) {
    $('#gameLoading').prop('hidden', state !== 'loading');
    $('#gameNotFound').prop('hidden', state !== 'notFound');
    $('#gameError').prop('hidden', state !== 'error');
    $('#gameHero, #gameFacts, #gameSections').prop('hidden', state !== 'game');
}

async function loadGame() {
    if (!TITLE_ID) {
        gameState('notFound');
        return;
    }
    gameState('loading');
    let data;
    try {
        data = await gqlFetch(GAME_QUERY, {titleId: TITLE_ID});
    } catch (e) {
        console.error(e);
        gameState('error');
        $('#gameError').prop('hidden', false);
        return;
    }
    if (!data.title) {
        gameState('notFound');
        $('#gameNotFound').prop('hidden', false);
        return;
    }
    game = data.title;
    renderGame(game);
    gameState('game');
    // Only now: a hidden row can't be scrolled to.
    highlightDlcFromUrl();
}

function renderGame(t) {
    const name = t.name || I18N.unrecognized;
    document.title = `${document.title.split(' | ')[0]} | ${name}`;
    $('#gameBreadcrumbName').text(name);
    renderHero(t);
    renderFacts(t);
    loadSagas(t);
    loadSaves(t);
    renderSections(t);
}

// --- versions -------------------------------------------------------------------------

/** The highest version the library holds: the newest owned update, else the base. */
function installedVersion(t) {
    const owned = (t.apps || []).filter(a => a.appType === 'UPDATE' || a.appType === 'BASE')
        .map(a => Number(a.appVersion) || 0);
    return owned.length ? Math.max(...owned) : null;
}

/** The highest version ownfoil knows for this game, owned or not. */
function latestVersion(t) {
    const known = (t.updateApps || []).map(a => Number(a.appVersion) || 0);
    return known.length ? Math.max(...known) : 0;
}

function ownedDlcIds(t) {
    return new Set((t.apps || []).filter(a => a.appType === 'DLC').map(a => a.appId));
}

/** What the library holds of a game besides its base: the DLC owned and the newest
 *  owned update, for a game whose base game is missing. */
function ownedExtras(t) {
    const updates = (t.apps || []).filter(a => a.appType === 'UPDATE').map(a => Number(a.appVersion) || 0);
    return {dlc: ownedDlcIds(t).size, update: updates.length ? Math.max(...updates) : null};
}

function missingDlcCount(t) {
    const owned = ownedDlcIds(t);
    return (t.availableDlc || []).filter(d => !owned.has(d.appId)).length;
}

// --- hero -----------------------------------------------------------------------------

function renderHero(t) {
    const hero = $('#gameHero').empty();
    const name = t.name || I18N.unrecognized;
    const own = t.ownership;

    // The banner, blurred, behind everything; the style's glows when there is none.
    const backdrop = $('<div class="game-hero__backdrop" aria-hidden="true">');
    if (t.bannerUrl) backdrop.css('background-image', `url(${JSON.stringify(t.bannerUrl)})`);
    hero.append(backdrop);

    // A base game the library doesn't hold is drawn in gray, like a missing game in
    // Sagas or on its Library card.
    const cover = $('<div class="game-hero__cover">').toggleClass('is-missing', !(own && own.haveBase));
    // The game's square cover, like the eShop's; the banner only when there's none (it
    // stays as the blurred backdrop either way).
    const art = t.iconUrl || t.bannerUrl;
    cover.append(art
        ? $('<img alt="">').attr('src', art)
        : $('<div class="library-cover--empty"><i class="bi bi-controller" aria-hidden="true"></i></div>'));
    hero.append(cover);

    const body = $('<div class="game-hero__body">');
    const badges = $('<div class="library-badges game-hero__badges">');
    if (own && own.haveBase) {
        badges.append(statusBadge('ok', 'bi-check-circle', I18N.inLibrary));
        // From the DLC list this page shows, so the hero never contradicts its own
        // DLC section (the stored "complete" flag lags until titles are re-checked).
        const missingDlc = missingDlcCount(t) > 0;
        if (!own.upToDate) badges.append(statusBadge('wait', 'bi-arrow-up-circle', I18N.badgeUpdate));
        if (missingDlc) badges.append(statusBadge('dlc', 'bi-puzzle', I18N.badgeMissingDlc));
        if (own.upToDate && !missingDlc) badges.append(statusBadge('ok', 'bi-stars', I18N.badgeComplete));
        // The game's own file is a bundle: "Bundle 1G+1U+5D".
        const base = (t.apps || []).find(a => a.appType === 'BASE' && a.downloadableFile);
        badges.append(bundleBadge(base && base.downloadableFile.contents, I18N.bundle));
    } else {
        badges.append(statusBadge('', 'bi-dash-circle', I18N.notInLibrary));
    }
    body.append(badges);
    body.append($('<h1 class="game-hero__title">').text(name));
    const year = String(t.releaseDate || '').match(/\d{4}/);
    const meta = [t.publisher, year && year[0]].filter(Boolean).join(' · ');
    if (meta) body.append($('<p class="game-hero__meta">').text(meta));
    // Its DLC or an update without the game: say what's there and what's missing.
    const extras = ownedExtras(t);
    if (!(own && own.haveBase) && (extras.dlc || extras.update !== null)) {
        const have = [extras.dlc && I18N.ownedDlcCount.replace('{n}', extras.dlc),
                      extras.update !== null && I18N.ownedUpdate.replace('{version}', `v${extras.update}`)]
            .filter(Boolean).join(' · ');
        body.append($('<div class="game-notice game-notice--base" role="status">').append(
            $('<i class="bi bi-exclamation-circle" aria-hidden="true"></i>'),
            $('<span>').text(I18N.baseMissingNotice.replace('{have}', have))));
    }
    body.append($('<div class="game-hero__actions" id="gameActions">'));
    hero.append(body);
    renderActions(t);
}

// --- fact tiles -----------------------------------------------------------------------

function renderFacts(t) {
    const list = v => Array.isArray(v) ? v.join(', ') : v;
    const owned = t.ownership && t.ownership.haveBase;
    const installed = owned ? installedVersion(t) : null;
    const latest = latestVersion(t);
    const facts = [
        ['bi-upc-scan', I18N.titleId, t.titleId, 'game-fact--mono'],
        ['bi-calendar-event', I18N.releaseDate, formatTitledbDate(t.releaseDate)],
        ['bi-globe2', I18N.region, t.region],
        ['bi-translate', I18N.languages, list(t.languages)],
        ['bi-tags', I18N.genre, list(t.category)],
        ['bi-people', I18N.players, t.numberOfPlayers],
        ['bi-shield-check', I18N.rating, t.rating],
        ['bi-hdd', I18N.size, formatTitledbSize(t.size)],
        ['bi-box-seam', I18N.installedVersion, installed !== null ? `v${installed}` : null],
        ['bi-arrow-up-circle', I18N.latestVersion, (owned || latest) ? `v${latest}` : null],
        // The newest version's; a console older than that can't run it up to date.
        ['bi-cpu', I18N.requiredFirmware, t.requiredFirmware,
         firmwareTooOld(t.requiredFirmware, CONSOLE_FIRMWARE) ? 'game-fact--firmware' : ''],
    ].filter(([, , value]) => value !== null && value !== undefined && value !== '');

    const box = $('#gameFacts').empty();
    facts.forEach(([icon, label, value, extra]) => {
        const fact = $('<div class="game-fact">').addClass(extra || '');
        fact.append($('<div class="game-fact__label">')
            .append($('<i aria-hidden="true">').addClass(`bi ${icon}`), $('<span>').text(label)));
        fact.append($('<div class="game-fact__value">').text(value));
        if (extra === 'game-fact--firmware') {
            fact.append($('<div class="game-fact__note">').text(I18N.firmwareTooOld
                .replace('{mine}', CONSOLE_FIRMWARE).replace('{needed}', t.requiredFirmware)));
        }
        box.append(fact);
    });
}

/** "Saga: The Legend of Zelda (4 of 6)" among the facts, each saga linking to its page.
 *  Asked apart: the facts don't wait for it, and a game without a saga adds nothing. */
async function loadSagas(t) {
    let sagas;
    try {
        const r = await fetch(`/api/sagas/of/${t.titleId}`, {credentials: 'same-origin'});
        if (!r.ok) return;
        sagas = (await r.json()).sagas || [];
    } catch (e) {
        return;
    }
    if (!sagas.length) return;
    const fact = $('<div class="game-fact game-fact--saga">');
    fact.append($('<div class="game-fact__label">')
        .append($('<i class="bi bi-collection" aria-hidden="true">'), $('<span>').text(I18N.sagaOf)));
    const value = $('<div class="game-fact__value">');
    sagas.forEach((s, i) => {
        if (i) value.append(document.createTextNode(', '));
        value.append($('<a class="game-saga-link">').attr('href', `/sagas/${s.id}`).text(s.name),
                     $('<span class="game-saga-count">')
                         .text(` (${I18N.sagaCount.replace('{owned}', s.owned).replace('{total}', s.total)})`));
    });
    $('#gameFacts').append(fact.append(value));
}

/** "Saved games: 3 backups, the latest 2 Nov 2026" among the facts, linking to /saves. */
async function loadSaves(t) {
    if (!CAN_SEE_SAVES) return;
    let saves;
    try {
        const r = await fetch(`/api/saves/of/${t.titleId}`, {credentials: 'same-origin'});
        if (!r.ok) return;
        saves = await r.json();
    } catch (e) {
        return;
    }
    if (!saves.count) return;
    const latest = new Date(saves.latest).toLocaleDateString(document.documentElement.lang || undefined,
                                                             {day: 'numeric', month: 'short', year: 'numeric'});
    const fact = $('<div class="game-fact">');
    fact.append($('<div class="game-fact__label">')
        .append($('<i class="bi bi-safe" aria-hidden="true">'), $('<span>').text(I18N.saves)));
    fact.append($('<div class="game-fact__value">').append($('<a class="game-saga-link" href="/saves">')
        .text((saves.count === 1 ? I18N.savesValueOne : I18N.savesValue)
            .replace('{count}', saves.count).replace('{when}', latest))));
    $('#gameFacts').append(fact);
}

/** The firmware a given update version needs, from the catalogue's versions. */
function versionFirmware(t, version) {
    const v = (t.availableVersions || []).find(x => Number(x.version) === Number(version));
    return v ? v.requiredFirmware : null;
}

// --- sections -------------------------------------------------------------------------

/** Downloads follow the route's own gate (app.py's download_library_file): shop
 *  access plus Settings > web downloads. The endpoint re-checks both regardless. */
function canDownload() {
    return IS_SHOP && WEB_DOWNLOADS_ENABLED;
}

/** One section block: a titled .surface, or nothing when it has no content. */
function section(id, icon, title, content) {
    if (!content) return null;
    const block = $('<section class="surface game-section">').attr('id', id);
    block.append($('<h2 class="game-section__title">')
        .append($('<i aria-hidden="true">').addClass(`bi ${icon}`), $('<span>').text(title)));
    return block.append(content);
}

function ownedBadge(owned) {
    return owned ? statusBadge('ok', 'bi-check-circle', I18N.owned)
                 : statusBadge('wait', 'bi-dash-circle', I18N.missing);
}

function renderSections(t) {
    const box = $('#gameSections').empty();
    [renderDescription(t), renderScreenshots(t), renderUpdates(t), renderDlc(t)]
        .filter(Boolean).forEach(s => box.append(s));
}

function renderDescription(t) {
    if (!t.intro && !t.description) return null;
    const content = $('<div class="game-description">');
    if (t.intro) content.append($('<p class="lead">').text(t.intro));
    if (t.description) content.append($('<p>').text(t.description));
    return section('gameDescription', 'bi-text-paragraph', I18N.description, content);
}

/** A sideways gallery; a click opens the shot full size in #shotModal. */
function renderScreenshots(t) {
    const shots = (t.screenshots || []).filter(s => s && s.url);
    if (!shots.length) return null;
    const gallery = $('<div class="game-shots">');
    shots.forEach((shot, i) => {
        const btn = $('<button type="button" class="game-shot">')
            .attr('aria-label', `${I18N.screenshots} ${i + 1}`)
            .append($('<img loading="lazy" alt="">').attr('src', shot.url));
        btn.on('click', () => {
            $('#shotModalImg').attr('src', shot.url);
            bootstrap.Modal.getOrCreateInstance(document.getElementById('shotModal')).show();
        });
        gallery.append(btn);
    });
    return section('gameScreenshots', 'bi-images', I18N.screenshots, gallery);
}

/** One row: what it is, when, and whether it's in the library - plus, for an owned
 *  file, its size, verification and (when allowed) a download button. All text goes
 *  through .text(): names are real (untrusted) catalogue data. */
function contentRow({icon, iconUrl, name, sub, owned, file, dataAttrs, details}) {
    const row = $('<li class="game-row">');
    if (dataAttrs) row.attr(dataAttrs);
    const lead = $('<div class="game-row__lead">');
    if (iconUrl) {
        lead.append($('<img class="game-row__icon" loading="lazy" alt="">').attr('src', iconUrl));
    } else {
        lead.append($('<span class="game-row__icon game-row__icon--glyph">')
            .append($('<i aria-hidden="true">').addClass(`bi ${icon}`)));
    }
    const text = $('<div class="game-row__text">').append($('<div class="game-row__name">').text(name));
    if (sub) text.append($('<div class="game-row__sub">').text(sub));
    lead.append(text);
    const tail = $('<div class="game-row__tail">').append(ownedBadge(owned));
    if (owned && file && file.contents && file.contents.length > 1) {
        // Inside a Multi file: listed, but downloaded with the whole file.
        tail.append(multiChip(I18N.bundle));
    } else if (owned && file) {
        if (file.size) tail.append($('<span class="game-row__size">').text(formatBytes(file.size)));
        const ver = verificationBadge(file.verificationStatus);
        if (ver) tail.append(ver);
        if (canDownload()) tail.append(downloadButton(file.id, name));
    }
    row.append(lead, tail);
    if (details) {
        // More about it (a DLC's description), folded away under its row.
        const panel = $('<div class="game-row__details" hidden>').text(details);
        const toggle = $('<button type="button" class="icon-btn game-row__more" aria-expanded="false">')
            .attr({title: I18N.details, 'aria-label': I18N.details})
            .append('<i class="bi bi-chevron-down" aria-hidden="true"></i>');
        toggle.on('click', () => {
            const open = panel.prop('hidden');
            panel.prop('hidden', !open);
            toggle.attr('aria-expanded', String(open)).toggleClass('is-open', open);
        });
        tail.append(toggle);
        row.append(panel);
    }
    return row;
}

function renderUpdates(t) {
    const updates = (t.updateApps || []).slice()
        .sort((a, b) => (Number(b.appVersion) || 0) - (Number(a.appVersion) || 0));
    const owned = t.ownership && t.ownership.haveBase;
    if (!updates.length) {
        return owned ? section('gameUpdates', 'bi-arrow-up-circle', I18N.updates,
                               $('<p class="text-secondary mb-0">').text(I18N.noUpdates)) : null;
    }
    const content = $('<div>');
    const latest = updates[0];
    if (owned && !latest.owned) {
        content.append($('<div class="game-notice" role="status">').append(
            $('<i class="bi bi-arrow-up-circle" aria-hidden="true"></i>'),
            $('<span>').text(I18N.updateMissing
                .replace('{version}', `v${latest.appVersion}`)
                .replace('{installed}', `v${installedVersion(t) || 0}`))));
    }
    const list = $('<ul class="game-rows">');
    updates.forEach(u => {
        // Each update tells the firmware it needs, marked when the console is older.
        const needs = versionFirmware(t, u.appVersion);
        const sub = [formatTitledbDate(u.releaseDate), needs && I18N.firmwareVersion.replace('{version}', needs)]
            .filter(Boolean).join(' · ');
        const row = contentRow({icon: 'bi-arrow-up-circle', name: `v${u.appVersion}`, sub,
                                owned: u.owned, file: u.downloadableFile});
        if (firmwareTooOld(needs, CONSOLE_FIRMWARE)) {
            $(row).addClass('game-row--firmware').attr('title', I18N.firmwareTooOld
                .replace('{mine}', CONSOLE_FIRMWARE).replace('{needed}', needs));
        }
        list.append(row);
    });
    return section('gameUpdates', 'bi-arrow-up-circle', I18N.updates, content.append(list));
}

function renderDlc(t) {
    const ownedIds = ownedDlcIds(t);
    const ownedApps = Object.fromEntries((t.apps || []).filter(a => a.appType === 'DLC').map(a => [a.appId, a]));
    // The catalogue's DLC plus the ones you have that it doesn't list (newer than the
    // catalogue, say): the same set the Library card counts, so "35 / 35" reads the same
    // here - never "35 / 32".
    const listed = new Set((t.availableDlc || []).map(d => d.appId));
    const extra = [...ownedIds].filter(id => !listed.has(id)).map(id => {
        const file = ((ownedApps[id] || {}).files || [])[0];
        return {appId: id, titledb: {name: file ? file.filename : null}};
    });
    const dlc = (t.availableDlc || []).concat(extra);
    if (!dlc.length) return null;
    // Owned first, then what is missing.
    const sorted = dlc.slice().sort((a, b) => Number(ownedIds.has(b.appId)) - Number(ownedIds.has(a.appId)));
    const list = $('<ul class="game-rows">');
    sorted.forEach(d => {
        const meta = d.titledb || {};
        const owned = ownedIds.has(d.appId);
        // Its own catalogue facts: release date, size, id - and its description below.
        const sub = [formatTitledbDate(meta.releaseDate), formatTitledbSize(meta.size), d.appId]
            .filter(Boolean).join(' · ');
        list.append(contentRow({
            icon: 'bi-puzzle', iconUrl: meta.iconUrl, name: meta.name || d.appId, sub, owned,
            file: owned ? (ownedApps[d.appId] || {}).downloadableFile : null,
            dataAttrs: {'data-dlc': d.appId},
            details: meta.description || I18N.noDescription,
        }));
    });
    return section('gameDlc', 'bi-puzzle', `${I18N.dlc} (${ownedIds.size} / ${dlc.length})`, list);
}

/** `?dlc=<appId>` (a DLC card in the Library) scrolls to that DLC and marks it. */
function highlightDlcFromUrl() {
    const id = new URLSearchParams(location.search).get('dlc');
    if (!id || !/^[0-9A-F]{16}$/i.test(id)) return;
    const row = document.querySelector(`[data-dlc="${id.toUpperCase()}"]`);
    if (!row) return;
    row.classList.add('is-highlighted');
    const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
    row.scrollIntoView({block: 'center', behavior: reduce ? 'auto' : 'smooth'});
}

// --- actions --------------------------------------------------------------------------

/** Every file of the game the viewer may download, for the Files dialog. An admin sees
 *  each file by its name (`files`, admin only); anyone else one file per owned base,
 *  update and DLC (`downloadableFile`), named after what it holds. */
function gameFiles(t) {
    const dlcNames = Object.fromEntries((t.availableDlc || [])
        .map(d => [d.appId, (d.titledb || {}).name || d.appId]));
    const label = a => a.appType === 'BASE' ? t.name || t.titleId
        : a.appType === 'DLC' ? dlcNames[a.appId] || a.appId : `v${a.appVersion}`;
    const typeName = a => ({BASE: I18N.typeBase, UPDATE: I18N.typeUpdate, DLC: I18N.typeDlc})[a.appType] || a.appType;
    const order = {BASE: 0, UPDATE: 1, DLC: 2};
    const icons = {BASE: 'bi-controller', UPDATE: 'bi-arrow-up-circle', DLC: 'bi-puzzle'};
    const apps = (t.apps || []).concat((t.updateApps || []).filter(a => a.owned)
        .map(a => Object.assign({appType: 'UPDATE'}, a)));
    const verification = {};
    apps.forEach(a => {
        if (a.downloadableFile) verification[a.downloadableFile.id] = a.downloadableFile.verificationStatus;
    });
    // What each file holds: a NUP or a multi-content file carries the game, updates and DLC.
    const parts = {};
    apps.forEach(a => {
        const ids = CAN_VIEW_ADMIN && a.files ? a.files.map(f => f.id) : a.downloadableFile ? [a.downloadableFile.id] : [];
        ids.forEach(id => {
            const list = parts[id] = parts[id] || [];
            const label = `${typeName(a)} v${a.appVersion}`;
            if (!list.includes(label)) list.push(label);
        });
    });
    const seen = new Set();
    const rows = [];
    apps.forEach(a => {
        const files = CAN_VIEW_ADMIN && a.files ? a.files
            : a.downloadableFile ? [Object.assign({extension: a.downloadableFile.format}, a.downloadableFile)] : [];
        files.forEach(f => {
            if (seen.has(f.id)) return;
            seen.add(f.id);
            rows.push({
                id: f.id, size: f.size, verificationStatus: verification[f.id],
                name: f.filename || label(a), icon: icons[a.appType] || 'bi-file-earmark-zip',
                tone: (a.appType || '').toLowerCase(),
                sub: [(parts[f.id] || []).length > 1 ? parts[f.id].join(', ') : `${typeName(a)} v${a.appVersion}`,
                      (f.extension || '').toUpperCase()].filter(Boolean).join(' · '),
                order: a.appType in order ? order[a.appType] : 3,
            });
        });
    });
    return rows.sort((a, b) => a.order - b.order);
}

function renderActions(t) {
    const box = $('#gameActions').empty();
    const files = canDownload() ? gameFiles(t) : [];
    if (files.length) {
        box.append($('<button type="button" class="btn btn-primary" id="gameFilesBtn">')
            .append($('<i class="bi bi-hdd-stack" aria-hidden="true"></i>'),
                    $('<span>').text(` ${I18N.files} (${files.length})`))
            .on('click', () => openFiles(files)));
    }
    if (IS_ADMIN) {
        box.append($('<button type="button" class="btn btn-outline-secondary">')
            .append($('<i class="bi bi-pencil-square" aria-hidden="true"></i>'),
                    $('<span>').text(` ${I18N.editMetadata}`))
            .on('click', () => openEdit(t)));
    }
    if (CAN_FAVORITE && t.titleId) box.append(favoriteAction(t.titleId));
    box.append($('<button type="button" class="btn btn-outline-secondary">')
        .append($('<i class="bi bi-clipboard" aria-hidden="true"></i>'),
                $('<span>').text(` ${I18N.copyTitleId}`))
        .on('click', () => copyTitleId(t.titleId)));
}

/** Favourite: the signed-in user's own star, the same list as the Library's. */
function favoriteAction(titleId) {
    let on = false;
    const btn = $('<button type="button" class="btn btn-outline-secondary game-fav-btn">');
    const paint = () => btn.toggleClass('is-on', on).attr('aria-pressed', on ? 'true' : 'false').empty()
        .append($('<i aria-hidden="true">').addClass(`bi ${on ? 'bi-star-fill' : 'bi-star'}`),
                $('<span>').text(` ${on ? I18N.favoriteRemove : I18N.favoriteAdd}`));
    paint();
    fetch('/api/favorites', {credentials: 'same-origin'})
        .then(r => r.ok ? r.json() : {title_ids: []})
        .then(d => { on = (d.title_ids || []).includes(titleId.toUpperCase()); paint(); })
        .catch(() => {});
    btn.on('click', async () => {
        btn.prop('disabled', true);
        try {
            const r = on
                ? await fetch(`/api/favorites/${titleId}`, {method: 'DELETE', credentials: 'same-origin'})
                : await fetch('/api/favorites', {method: 'POST', credentials: 'same-origin',
                                                 headers: {'Content-Type': 'application/json'},
                                                 body: JSON.stringify({title_id: titleId})});
            if (r.ok) { on = !on; paint(); }
        } finally {
            btn.prop('disabled', false);
        }
    });
    return btn;
}

/** The Files dialog: each file with its size, check and its own download link, and
 *  "Download all" at the foot. Every download is the browser's own (a plain link to
 *  the route, which answers with Content-Disposition: attachment). */
function openFiles(files) {
    const list = $('#gameFilesList').empty();
    files.forEach(f => {
        const lead = $('<div class="game-row__lead">').append(
            $('<span class="game-row__icon game-row__icon--glyph">')
                .addClass(f.tone ? `game-row__icon--${f.tone}` : '')
                .append($('<i aria-hidden="true">').addClass(`bi ${f.icon}`)),
            $('<div class="game-row__text">').append(
                $('<div class="game-row__name">').text(f.name),
                $('<div class="game-row__sub">').text(f.sub)));
        const tail = $('<div class="game-row__tail">');
        if (f.size) tail.append($('<span class="game-row__size">').text(formatBytes(f.size)));
        const ver = verificationBadge(f.verificationStatus);
        if (ver) tail.append(ver);
        tail.append($('<a class="btn btn-sm icon-btn p-0" download>')
            .attr({href: `/api/library/download/${f.id}`, title: I18N.downloadTooltip,
                   'aria-label': I18N.downloadAria.replace('{name}', f.name)})
            .append('<i class="bi bi-download" aria-hidden="true"></i>'));
        list.append($('<li class="game-row">').append(lead, tail));
    });
    $('#gameFilesDownloadAll').off('click').on('click', () => downloadAll(files.map(f => f.id)))
        .find('span').text(` ${I18N.downloadAll} (${files.length})`);
    bootstrap.Modal.getOrCreateInstance(document.getElementById('gameFilesModal')).show();
}

/** One file after another: each is a normal download through the existing route
 *  (which re-checks access), spaced so the browser doesn't drop any of them. */
function downloadAll(fileIds) {
    fileIds.forEach((id, i) => setTimeout(() => {
        const a = document.createElement('a');
        a.href = `/api/library/download/${id}`;
        a.download = '';
        document.body.appendChild(a);
        a.click();
        a.remove();
    }, i * 800));
}

async function copyTitleId(titleId) {
    try {
        await navigator.clipboard.writeText(titleId);
    } catch (e) {
        // Plain-http LAN addresses have no Clipboard API: fall back to a selection.
        const area = $('<textarea class="visually-hidden">').val(titleId).appendTo('body');
        area.get(0).select();
        try { document.execCommand('copy'); } catch (err) { /* nothing more to try */ }
        area.remove();
    }
    showToast(I18N.copied.replace('{id}', titleId));
}

function showToast(text) {
    const toast = document.getElementById('gameToast');
    if (!toast) return;
    $('#gameToastText').text(text);
    bootstrap.Toast.getOrCreateInstance(toast, {delay: 2500}).show();
}

// --- metadata edit (admins) -----------------------------------------------------------
// The setTitleOverride / deleteTitleOverride mutations: a blank field is sent as
// omitted, not as an empty string, so it defers to what titledb (or a lower-priority
// override) already has instead of blanking it out.

const SET_TITLE_OVERRIDE_MUTATION = `
    mutation SetOverride($id: ID!, $record: String!) {
        setTitleOverride(titleId: $id, record: $record) { titleId }
    }`;
const DELETE_TITLE_OVERRIDE_MUTATION = `
    mutation DeleteOverride($id: ID!) {
        deleteTitleOverride(titleId: $id)
    }`;

const EDIT_FIELDS = [
    ['name', 'gameEditName'], ['developer', 'gameEditDeveloper'], ['publisher', 'gameEditPublisher'],
    ['releaseDate', 'gameEditReleaseDate'], ['description', 'gameEditDescription'],
];

function openEdit(t) {
    EDIT_FIELDS.forEach(([key, id]) => $(`#${id}`).val(t[key] || ''));
    bootstrap.Modal.getOrCreateInstance(document.getElementById('gameEditModal')).show();
}

async function saveEdit() {
    const btn = $('#gameEditSaveBtn').prop('disabled', true);
    const record = {};
    EDIT_FIELDS.forEach(([key, id]) => {
        const value = ($(`#${id}`).val() || '').trim();
        if (value) record[key] = value;
    });
    try {
        await gqlMutate(SET_TITLE_OVERRIDE_MUTATION, {id: TITLE_ID, record: JSON.stringify(record)});
        bootstrap.Modal.getOrCreateInstance(document.getElementById('gameEditModal')).hide();
        loadGame();
    } catch (e) {
        console.error(e);
        alert(I18N.saveFailed);
    } finally {
        btn.prop('disabled', false);
    }
}

async function resetEdit() {
    const btn = $('#gameEditResetBtn').prop('disabled', true);
    try {
        await gqlMutate(DELETE_TITLE_OVERRIDE_MUTATION, {id: TITLE_ID});
        bootstrap.Modal.getOrCreateInstance(document.getElementById('gameEditModal')).hide();
        loadGame();
    } catch (e) {
        console.error(e);
        alert(I18N.saveFailed);
    } finally {
        btn.prop('disabled', false);
    }
}

// --- start ----------------------------------------------------------------------------

$(function () {
    // "Library" goes back when the Library is where we came from, so its filters,
    // sort, page and scroll are as they were left.
    $('#gameBackLink').on('click', function (e) {
        try {
            if (document.referrer && new URL(document.referrer).origin === location.origin
                && new URL(document.referrer).pathname === '/' && history.length > 1) {
                e.preventDefault();
                history.back();
            }
        } catch (err) { /* malformed referrer: follow the link */ }
    });
    $('#gameRetryBtn').on('click', loadGame);
    $('#gameEditSaveBtn').on('click', saveEdit);
    $('#gameEditResetBtn').on('click', resetEdit);
    loadGame();
});
