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
            screenshots { url }
            ownership { haveBase upToDate complete }
            apps(owned: true) {
                appId appType appVersion releaseDate
                downloadableFile { id size verificationStatus }
                files { id filename size extension }
            }
            updateApps: apps(appType: [UPDATE]) {
                appId appVersion releaseDate owned
                downloadableFile { id size verificationStatus }
            }
            availableDlc {
                appId version
                titledb { name iconUrl bannerUrl releaseDate }
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
}

function renderGame(t) {
    const name = t.name || I18N.unrecognized;
    document.title = `${document.title.split(' | ')[0]} | ${name}`;
    $('#gameBreadcrumbName').text(name);
    renderHero(t);
    renderFacts(t);
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

// --- hero -----------------------------------------------------------------------------

function renderHero(t) {
    const hero = $('#gameHero').empty();
    const name = t.name || I18N.unrecognized;
    const own = t.ownership;

    // The banner, blurred, behind everything; the style's glows when there is none.
    const backdrop = $('<div class="game-hero__backdrop" aria-hidden="true">');
    if (t.bannerUrl) backdrop.css('background-image', `url(${JSON.stringify(t.bannerUrl)})`);
    hero.append(backdrop);

    const cover = $('<div class="game-hero__cover">');
    const art = t.bannerUrl || t.iconUrl;
    cover.append(art
        ? $('<img alt="">').attr('src', art)
        : $('<div class="library-cover--empty"><i class="bi bi-controller" aria-hidden="true"></i></div>'));
    hero.append(cover);

    const body = $('<div class="game-hero__body">');
    const badges = $('<div class="library-badges game-hero__badges">');
    if (own && own.haveBase) {
        badges.append(statusBadge('ok', 'bi-check-circle', I18N.inLibrary));
        const hasDlc = (t.availableDlc || []).length > 0;
        if (!own.upToDate) badges.append(statusBadge('wait', 'bi-arrow-up-circle', I18N.badgeUpdate));
        if (hasDlc && !own.complete) badges.append(statusBadge('dlc', 'bi-puzzle', I18N.badgeMissingDlc));
        if (own.upToDate && (own.complete || !hasDlc)) badges.append(statusBadge('ok', 'bi-stars', I18N.badgeComplete));
    } else {
        badges.append(statusBadge('', 'bi-dash-circle', I18N.notInLibrary));
    }
    body.append(badges);
    body.append($('<h1 class="game-hero__title">').text(name));
    const year = String(t.releaseDate || '').match(/\d{4}/);
    const meta = [t.publisher, year && year[0]].filter(Boolean).join(' · ');
    if (meta) body.append($('<p class="game-hero__meta">').text(meta));
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
    ].filter(([, , value]) => value !== null && value !== undefined && value !== '');

    const box = $('#gameFacts').empty();
    facts.forEach(([icon, label, value, extra]) => {
        const fact = $('<div class="game-fact">').addClass(extra || '');
        fact.append($('<div class="game-fact__label">')
            .append($('<i aria-hidden="true">').addClass(`bi ${icon}`), $('<span>').text(label)));
        fact.append($('<div class="game-fact__value">').text(value));
        box.append(fact);
    });
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
    [renderDescription(t), renderScreenshots(t), renderUpdates(t), renderDlc(t), renderFiles(t)]
        .filter(Boolean).forEach(s => box.append(s));
    highlightDlcFromUrl();
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
function contentRow({icon, iconUrl, name, sub, owned, file, dataAttrs}) {
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
    if (owned && file) {
        if (file.size) tail.append($('<span class="game-row__size">').text(formatBytes(file.size)));
        const ver = verificationBadge(file.verificationStatus);
        if (ver) tail.append(ver);
        if (canDownload()) tail.append(downloadButton(file.id, name));
    }
    return row.append(lead, tail);
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
    updates.forEach(u => list.append(contentRow({
        icon: 'bi-arrow-up-circle', name: `v${u.appVersion}`, sub: formatTitledbDate(u.releaseDate),
        owned: u.owned, file: u.downloadableFile,
    })));
    return section('gameUpdates', 'bi-arrow-up-circle', I18N.updates, content.append(list));
}

function renderDlc(t) {
    const dlc = t.availableDlc || [];
    if (!dlc.length) return null;
    const ownedIds = ownedDlcIds(t);
    const ownedApps = Object.fromEntries((t.apps || []).filter(a => a.appType === 'DLC').map(a => [a.appId, a]));
    // Owned first, then what is missing.
    const sorted = dlc.slice().sort((a, b) => Number(ownedIds.has(b.appId)) - Number(ownedIds.has(a.appId)));
    const list = $('<ul class="game-rows">');
    sorted.forEach(d => {
        const meta = d.titledb || {};
        const owned = ownedIds.has(d.appId);
        list.append(contentRow({
            icon: 'bi-puzzle', iconUrl: meta.iconUrl, name: meta.name || d.appId, sub: d.appId, owned,
            file: owned ? (ownedApps[d.appId] || {}).downloadableFile : null,
            dataAttrs: {'data-dlc': d.appId},
        }));
    });
    return section('gameDlc', 'bi-puzzle', `${I18N.dlc} (${ownedIds.size} / ${dlc.length})`, list);
}

/** Every file the library holds for this game. Admin only: `files` is null for
 *  anyone else, and the section is not drawn. */
function renderFiles(t) {
    if (!IS_ADMIN) return null;
    const rows = [];
    (t.apps || []).forEach(a => (a.files || []).forEach(f => rows.push({app: a, file: f})));
    if (!rows.length) return null;
    const verification = Object.fromEntries((t.apps || []).filter(a => a.downloadableFile)
        .map(a => [a.downloadableFile.id, a.downloadableFile.verificationStatus]));
    const list = $('<ul class="game-rows">');
    rows.forEach(({app, file}) => {
        const sub = [app.appType, `v${app.appVersion}`, (file.extension || '').toUpperCase()]
            .filter(Boolean).join(' · ');
        list.append(contentRow({
            icon: 'bi-file-earmark-zip', name: file.filename, sub, owned: true,
            file: {id: file.id, size: file.size, verificationStatus: verification[file.id]},
        }));
    });
    return section('gameFiles', 'bi-hdd-stack', I18N.files, list);
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

/** Every downloadable file of the game: the base, its updates and its DLC. */
function downloadableFileIds(t) {
    const ids = new Set();
    (t.apps || []).forEach(a => { if (a.downloadableFile) ids.add(a.downloadableFile.id); });
    (t.updateApps || []).forEach(a => { if (a.owned && a.downloadableFile) ids.add(a.downloadableFile.id); });
    return [...ids];
}

function renderActions(t) {
    const box = $('#gameActions').empty();
    const fileIds = downloadableFileIds(t);
    if (canDownload() && fileIds.length) {
        box.append($('<button type="button" class="btn btn-primary">')
            .append($('<i class="bi bi-download" aria-hidden="true"></i>'),
                    $('<span>').text(` ${I18N.downloadAll} (${fileIds.length})`))
            .on('click', () => downloadAll(fileIds)));
    }
    if (IS_ADMIN) {
        box.append($('<button type="button" class="btn btn-outline-secondary">')
            .append($('<i class="bi bi-pencil-square" aria-hidden="true"></i>'),
                    $('<span>').text(` ${I18N.editMetadata}`))
            .on('click', () => openEdit(t)));
    }
    box.append($('<button type="button" class="btn btn-outline-secondary">')
        .append($('<i class="bi bi-clipboard" aria-hidden="true"></i>'),
                $('<span>').text(` ${I18N.copyTitleId}`))
        .on('click', () => copyTitleId(t.titleId)));
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
