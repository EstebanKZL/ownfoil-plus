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

// --- sections and actions: filled in below --------------------------------------------

function renderSections(t) {
    $('#gameSections').empty();
}

function renderActions(t) {
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
    loadGame();
});
