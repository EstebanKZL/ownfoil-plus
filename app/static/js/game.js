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
                appId appType appVersion displayVersion releaseDate
                downloadableFile { id size verificationStatus format contents }
                files { id filename size extension }
            }
            updateApps: apps(appType: [UPDATE]) {
                appId appVersion displayVersion releaseDate owned
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
    // Which console it is for: Switch 2 games have ids starting with 04.
    badges.append(statusBadge('', 'bi-nintendo-switch', String(t.titleId || TITLE_ID).startsWith('04') ? 'Switch 2' : 'Switch')
        .addClass('console-badge'));
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
        // Behind the newest update: the fact wears the update's amber, the same way
        // the firmware one wears its violet when the console is too old.
        ['bi-arrow-up-circle', I18N.latestVersion, (owned || latest) ? `v${latest}` : null,
         owned && installed !== null && latest !== null && latest > installed ? 'game-fact--update' : ''],
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

/** Copy a row's own id (a DLC's), right beside where it reads. */
function copyIdButton(id) {
    return $('<button type="button" class="game-row__id-copy ms-1">')
        .attr({title: I18N.copyTitleId, 'aria-label': I18N.copyTitleId})
        .append('<i class="bi bi-clipboard" aria-hidden="true"></i>')
        .on('click', () => copyTitleId(id));
}

/** The web knows what a version changed; titledb doesn't. One search, Switch Library
 *  Manager's "novedades" - only the icon, opening in its own tab. */
function updateNotesUrl(t, u) {
    const q = `${t.name || t.titleId} switch update ${u.displayVersion || `v${u.appVersion}`}`;
    return `https://www.google.com/search?q=${encodeURIComponent(q)}`;
}

/** One row: what it is, when, and whether it's in the library - plus, for an owned
 *  file, its size, verification and (when allowed) a download button. A name with
 *  `onName` opens something (a DLC's card); `newsUrl` adds the release-notes icon
 *  before the download; `copyId` puts a copy button beside the id in the sub line.
 *  All text goes through .text(): names are real (untrusted) catalogue data. */
function contentRow({icon, iconUrl, name, sub, owned, file, dataAttrs, details, onName, newsUrl, copyId, iconTone}) {
    const row = $('<li class="game-row">');
    if (dataAttrs) row.attr(dataAttrs);
    const lead = $('<div class="game-row__lead">');
    if (iconUrl) {
        lead.append($('<img class="game-row__icon" loading="lazy" alt="">').attr('src', iconUrl));
    } else {
        const glyph = $('<span class="game-row__icon game-row__icon--glyph">');
        if (iconTone) glyph.addClass(`game-row__icon--${iconTone}`);
        lead.append(glyph.append($('<i aria-hidden="true">').addClass(`bi ${icon}`)));
    }
    const nameEl = onName
        ? $('<button type="button" class="game-row__name-btn">').text(name).attr('title', name).on('click', onName)
        : $('<div class="game-row__name">').text(name);
    const text = $('<div class="game-row__text">').append(nameEl);
    if (sub || copyId) {
        const subEl = $('<div class="game-row__sub"></div>');
        if (sub) subEl.append(document.createTextNode(sub));
        if (copyId) subEl.append(copyIdButton(copyId));
        text.append(subEl);
    }
    lead.append(text);
    const multi = owned && file && file.contents && file.contents.length > 1;
    const tail = $('<div class="game-row__tail">').append(ownedBadge(owned));
    if (multi) {
        // Inside a Multi file: listed, but downloaded with the whole file.
        tail.append(multiChip(I18N.bundle));
    } else if (owned && file) {
        if (file.size) tail.append($('<span class="game-row__size">').text(formatBytes(file.size)));
        const ver = verificationBadge(file.verificationStatus);
        if (ver) tail.append(ver);
    }
    if (owned && file && !multi && canDownload()) tail.append(downloadButton(file.id, name));
    if (newsUrl) {
        // The release notes, after the download (asked for) - only the icon.
        tail.append($('<a class="btn btn-sm icon-btn p-0" target="_blank" rel="noopener">')
            .attr({href: newsUrl, title: I18N.updateNotes, 'aria-label': I18N.updateNotes})
            .append('<i class="bi bi-box-arrow-up-right" aria-hidden="true"></i>'));
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
        // Both ways of naming a version, "3.0.0 · v1048576" (the game page and the
        // Library's List view read the same).
        const label = u.displayVersion ? `${u.displayVersion} · v${u.appVersion}` : `v${u.appVersion}`;
        const row = contentRow({icon: 'bi-arrow-up-circle', name: label, sub,
                                owned: u.owned, file: u.downloadableFile,
                                newsUrl: updateNotesUrl(t, u), iconTone: 'update'});
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
        // Its own catalogue facts: release date and id (the size rides in its pill at
        // the row's end, the full card has it too) - and its description below.
        const sub = [formatTitledbDate(meta.releaseDate), d.appId].filter(Boolean).join(' · ');
        list.append(contentRow({
            icon: 'bi-puzzle', iconUrl: meta.iconUrl, name: meta.name || d.appId, sub, owned,
            iconTone: 'dlc',
            file: owned ? (ownedApps[d.appId] || {}).downloadableFile : null,
            dataAttrs: {'data-dlc': d.appId},
            onName: () => openDlcModal(t, d, owned, (ownedApps[d.appId] || {}).downloadableFile),
            copyId: d.appId,
            details: meta.description || I18N.noDescription,
        }));
    });
    return section('gameDlc', 'bi-puzzle', `${I18N.dlc} (${ownedIds.size} / ${dlc.length})`, list);
}

/** A DLC's own card (the row's name opens it): the game's art beside the DLC's facts
 *  - id with a copy button, release date, size - and its description. Everything goes
 *  through .text(): names are real (untrusted) catalogue data. */
function openDlcModal(t, d, owned, file) {
    const meta = d.titledb || {};
    const art = meta.bannerUrl || meta.iconUrl || t.bannerUrl || t.iconUrl || '';
    $('#dlcModalImg').attr('src', art).toggleClass('d-none', !art);
    $('#dlcModalName').text(meta.name || d.appId);
    $('#dlcModalBadge').empty().append(ownedBadge(owned));
    const facts = $('#dlcModalFacts').empty();
    const fact = (label, value, extra) => {
        if (value === null || value === undefined || value === '') return;
        const dd = $('<dd class="mb-0"></dd>').text(value);
        if (extra) dd.append(' ', extra);
        facts.append($('<div class="dlc-modal__fact">').append($('<dt>').text(label), dd));
    };
    fact(I18N.titleId, d.appId, copyIdButton(d.appId).removeClass('ms-1'));
    fact(I18N.releaseDate, formatTitledbDate(meta.releaseDate));
    fact(I18N.size, file && file.size ? formatBytes(file.size) : formatTitledbSize(meta.size));
    $('#dlcModalDesc').text(meta.description || I18N.noDescription);
    bootstrap.Modal.getOrCreateInstance(document.getElementById('dlcModal')).show();
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
    coverOpen(t);
    bootstrap.Modal.getOrCreateInstance(document.getElementById('gameEditModal')).show();
}

// --- the cover in Edit: eShop search, an image chosen or pasted, a square crop --------

const COVER_OUT = 1024;          // the side of the saved crop, in pixels
let coverTitle = null;           // the title being edited
let coverOriginal = false;       // "Use the original" pressed: dropped on Save
let crop = null;                 // {img, w, h, scale, x, y, min, max} while cropping

function coverOpen(t) {
    coverTitle = t;
    coverOriginal = false;
    cropClose();
    $('#gameEditCoverSearch').prop('hidden', true);
    $('#gameEditCoverResults').empty();
    $('#gameEditCoverNote').text(I18N.coverPasteHint);
    coverShow(t.iconUrl || t.bannerUrl || '');
}

function coverShow(url) {
    $('#gameEditCoverImg').attr('src', url || '').prop('hidden', !url);
    $('#gameEditCoverEmpty').prop('hidden', !!url);
}

/** A URL the crop can read: our own, or Nintendo's through the server (a canvas can't
 *  export an image from another site). */
function coverReadable(url) {
    if (!url) return null;
    if (url.startsWith('/') || url.startsWith(location.origin)) return url;
    return '/api/covers/image?url=' + encodeURIComponent(url);
}

function cropStart(src) {
    const img = new Image();
    img.onload = () => {
        const stage = document.getElementById('gameEditCrop');
        $('#gameEditCoverImg, #gameEditCoverEmpty').prop('hidden', true);
        stage.hidden = false;
        $('#gameEditCropTools').prop('hidden', false);
        const side = stage.clientWidth;
        const w = img.naturalWidth, h = img.naturalHeight;
        const fit = Math.min(side / w, side / h), fill = Math.max(side / w, side / h);
        crop = {img, w, h, side, fit, fill, min: fit, max: fill * 4, scale: fill, x: 0, y: 0};
        document.getElementById('gameEditCropImg').src = img.src;
        cropReset();
        coverOriginal = false;
    };
    img.onerror = () => $('#gameEditCoverNote').text(I18N.coverLoadFailed);
    img.src = src;
}

function cropClose() {
    crop = null;
    $('#gameEditCrop, #gameEditCropTools').prop('hidden', true);
    if (coverTitle) coverShow(coverOriginal ? '' : (coverTitle.iconUrl || coverTitle.bannerUrl || ''));
}

/** Keep the square covered (or, zoomed out past it, the image centred in it). */
function cropClamp() {
    const c = crop;
    const w = c.w * c.scale, h = c.h * c.scale;
    c.x = w >= c.side ? Math.min(0, Math.max(c.side - w, c.x)) : (c.side - w) / 2;
    c.y = h >= c.side ? Math.min(0, Math.max(c.side - h, c.y)) : (c.side - h) / 2;
}

function cropPaint() {
    if (!crop) return;
    cropClamp();
    const el = document.getElementById('gameEditCropImg');
    el.style.width = `${crop.w * crop.scale}px`;
    el.style.height = `${crop.h * crop.scale}px`;
    el.style.transform = `translate(${crop.x}px, ${crop.y}px)`;
    const t = (crop.scale - crop.min) / (crop.max - crop.min);
    document.getElementById('gameEditCropZoom').value = String(Math.round(Math.sqrt(Math.max(0, t)) * 1000));
}

/** Zoom to `scale`, keeping the point under (cx, cy) of the square still. */
function cropZoom(scale, cx = crop.side / 2, cy = crop.side / 2) {
    const next = Math.min(crop.max, Math.max(crop.min, scale));
    crop.x = cx - (cx - crop.x) * next / crop.scale;
    crop.y = cy - (cy - crop.y) * next / crop.scale;
    crop.scale = next;
    cropPaint();
}

function cropReset() {
    crop.scale = crop.fill;
    crop.x = (crop.side - crop.w * crop.scale) / 2;
    crop.y = (crop.side - crop.h * crop.scale) / 2;
    cropPaint();
}

function cropFit() {
    crop.scale = crop.fit;
    cropPaint();
}

/** The square as a JPEG blob, COVER_OUT a side (white behind a transparent image). */
function cropBlob() {
    const canvas = document.createElement('canvas');
    canvas.width = canvas.height = COVER_OUT;
    const ctx = canvas.getContext('2d');
    const r = COVER_OUT / crop.side;
    ctx.fillStyle = '#fff';
    ctx.fillRect(0, 0, COVER_OUT, COVER_OUT);
    ctx.imageSmoothingQuality = 'high';
    ctx.drawImage(crop.img, crop.x * r, crop.y * r, crop.w * crop.scale * r, crop.h * crop.scale * r);
    return new Promise(resolve => canvas.toBlob(resolve, 'image/jpeg', 0.92));
}

function coverFromBlob(blob) {
    if (!blob || !blob.type.startsWith('image/')) return;
    cropStart(URL.createObjectURL(blob));
}

async function coverSearch() {
    const query = ($('#gameEditCoverQuery').val() || '').trim();
    const results = $('#gameEditCoverResults').empty();
    const state = $('#gameEditCoverSearchState').prop('hidden', true);
    $('#gameEditCoverWeb').attr('href', 'https://www.google.com/search?tbm=isch&q='
        + encodeURIComponent(`${query} Nintendo Switch cover`));
    if (!query) return;
    const lang = (document.documentElement.lang || 'en').slice(0, 2);
    const switch2 = TITLE_ID.startsWith('04') ? '1' : '0';
    try {
        const r = await fetch(`/api/covers/search?q=${encodeURIComponent(query)}&lang=${lang}&switch2=${switch2}`,
                              {credentials: 'same-origin'});
        const data = await r.json();
        if (!r.ok) throw new Error(data.error || r.status);
        if (!data.results.length) state.text(I18N.coverNoneFound).prop('hidden', false);
        data.results.forEach(item => {
            const pick = $('<button type="button" class="cover-search__item">').attr('title', item.title)
                .append($('<img loading="lazy" alt="">').attr('src', item.image),
                        $('<span>').text(item.title));
            pick.on('click', () => cropStart(coverReadable(item.image)));
            results.append(pick);
        });
    } catch (e) {
        console.error(e);
        state.text(I18N.coverSearchFailed).prop('hidden', false);
    }
}

/** The cover changes made in Edit, before its text is saved. */
async function coverSave() {
    if (crop) {
        const blob = await cropBlob();
        const form = new FormData();
        form.append('image', blob, 'cover.jpg');
        const r = await fetch(`/api/titles/${TITLE_ID}/cover`, {method: 'POST', body: form, credentials: 'same-origin'});
        if (!r.ok) throw new Error(I18N.coverSaveFailed);
    } else if (coverOriginal) {
        const r = await fetch(`/api/titles/${TITLE_ID}/cover`, {method: 'DELETE', credentials: 'same-origin'});
        if (!r.ok) throw new Error(I18N.coverSaveFailed);
    }
}

function wireCover() {
    $('#gameEditCoverSearchBtn').on('click', () => {
        const panel = $('#gameEditCoverSearch');
        const open = panel.prop('hidden');
        panel.prop('hidden', !open);
        if (open) {
            $('#gameEditCoverQuery').val(($('#gameEditName').val() || (coverTitle && coverTitle.name) || '').trim());
            coverSearch();
        }
    });
    $('#gameEditCoverQueryBtn').on('click', coverSearch);
    $('#gameEditCoverQuery').on('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); coverSearch(); } });
    $('#gameEditCoverFile').on('change', function () {
        coverFromBlob(this.files && this.files[0]);
        this.value = '';
    });
    $('#gameEditCoverCropBtn').on('click', () => {
        const url = coverTitle && (coverTitle.iconUrl || coverTitle.bannerUrl);
        if (url) cropStart(coverReadable(url));
    });
    $('#gameEditCoverOriginalBtn').on('click', () => {
        cropClose();
        coverOriginal = true;
        coverShow('');
        $('#gameEditCoverNote').text(I18N.coverOriginalNote);
    });
    $('#gameEditCropFit').on('click', cropFit);
    $('#gameEditCropReset').on('click', cropReset);
    $('#gameEditCropCancel').on('click', cropClose);
    $('#gameEditCropZoom').on('input', function () {
        const t = (Number(this.value) / 1000) ** 2;
        cropZoom(crop.min + t * (crop.max - crop.min));
    });
    const stage = document.getElementById('gameEditCrop');
    let drag = null;
    stage.addEventListener('pointerdown', e => {
        if (!crop) return;
        drag = {x: e.clientX - crop.x, y: e.clientY - crop.y};
        stage.setPointerCapture(e.pointerId);
        stage.classList.add('is-dragging');
    });
    stage.addEventListener('pointermove', e => {
        if (!drag) return;
        crop.x = e.clientX - drag.x;
        crop.y = e.clientY - drag.y;
        cropPaint();
    });
    const end = () => { drag = null; stage.classList.remove('is-dragging'); };
    stage.addEventListener('pointerup', end);
    stage.addEventListener('pointercancel', end);
    stage.addEventListener('wheel', e => {
        if (!crop) return;
        e.preventDefault();
        const box = stage.getBoundingClientRect();
        cropZoom(crop.scale * (e.deltaY < 0 ? 1.1 : 1 / 1.1), e.clientX - box.left, e.clientY - box.top);
    }, {passive: false});
    stage.addEventListener('keydown', e => {
        if (!crop) return;
        const step = {ArrowLeft: [10, 0], ArrowRight: [-10, 0], ArrowUp: [0, 10], ArrowDown: [0, -10]}[e.key];
        if (step) { e.preventDefault(); crop.x += step[0]; crop.y += step[1]; cropPaint(); }
        if (e.key === '+' || e.key === '=') cropZoom(crop.scale * 1.1);
        if (e.key === '-') cropZoom(crop.scale / 1.1);
    });
    // An image pasted anywhere in the dialog (Ctrl+V) goes to the crop.
    document.getElementById('gameEditModal').addEventListener('paste', e => {
        const item = [...(e.clipboardData || {}).items || []].find(i => i.type.startsWith('image/'));
        if (item) { e.preventDefault(); coverFromBlob(item.getAsFile()); }
    });
}

async function saveEdit() {
    const btn = $('#gameEditSaveBtn').prop('disabled', true);
    const record = {};
    EDIT_FIELDS.forEach(([key, id]) => {
        const value = ($(`#${id}`).val() || '').trim();
        if (value) record[key] = value;
    });
    try {
        await coverSave();
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
    if (document.getElementById('gameEditModal')) wireCover();
    $('#gameEditResetBtn').on('click', resetEdit);
    loadGame();
});
