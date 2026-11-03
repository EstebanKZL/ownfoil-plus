// The Library page (templates/index.html). The page itself renders the server-fed
// constants (IS_ADMIN, IS_SHOP, WEB_DOWNLOADS_ENABLED, SHOW_GAME_BACKGROUND_IMAGE) and
// the I18N strings in its one inline script, then loads this file.

// Remembered preferences. Storage can be missing (private windows, blocked site data)
// or hold anything (an older version, a hand edit): every access goes through these.
function storageGet(key) {
    try { return localStorage.getItem(key); } catch (e) { return null; }
}

function storageSet(key, value) {
    try { localStorage.setItem(key, value); } catch (e) { /* this page only */ }
}

function storageRemove(key) {
    try { localStorage.removeItem(key); } catch (e) { /* this page only */ }
}

let itemsPerPage = 12;
let currentPage = 1;
let totalItems = 0;
let cardSize = 3; // Default card size
let currentView = 'card'; // Default view is 'card'
let fetchSeq = 0;    // guards against an older request answering after a newer one
let searchDebounce;

// Active filters
let activeTypeFilter = "";
let activeOwnershipFilter = "";
let activeUpdateFilter = "";
let activeCompletionFilter = "";
let activeHealthFilter = "";

// Sorting: the fields both the `apps` (cards, icons) and `titles` (list) queries sort
// on. ADDED_AT exists in the schema but only applies to `files`.
const SORT_FIELDS = ['NAME', 'RELEASE_DATE'];
const SORT_DIRECTIONS = ['ASC', 'DESC'];
let librarySort = {field: 'NAME', direction: 'ASC'};

/** A stored sort from an older version or a hand edit falls back to the default
 *  instead of sending the server an enum value it rejects. */
function loadSortFromStorage() {
    try {
        const saved = JSON.parse(storageGet('librarySort') || 'null');
        if (saved && SORT_FIELDS.includes(saved.field) && SORT_DIRECTIONS.includes(saved.direction)) {
            librarySort = {field: saved.field, direction: saved.direction};
        }
    } catch (e) { /* unreadable or blocked storage: keep the default */ }
    renderSortControls();
}

function renderSortControls() {
    $('#sortField').val(librarySort.field);
    const asc = librarySort.direction === 'ASC';
    const kind = librarySort.field === 'NAME' ? 'alpha' : 'numeric';
    $('#sortDirection')
        .attr('data-direction', librarySort.direction)
        .attr('title', asc ? I18N.sortAsc : I18N.sortDesc)
        .attr('aria-label', asc ? I18N.sortAsc : I18N.sortDesc)
        .find('i').attr('class', `bi bi-sort-${kind}-${asc ? 'down' : 'up'}`);
}

function setSort(field, direction) {
    librarySort = {field, direction};
    storageSet('librarySort', JSON.stringify(librarySort));
    renderSortControls();
    resetToFirstPage();
}

// groupByAppId: one item per app id rather than per (app id, version), so a card
// is an item and `pageSize` really is the number of cards on the page.
//
// bannerUrl/iconUrl come straight off `titledb` - already /api/media/... when
// Local artworks has a copy, the titledb hotlink otherwise (see
// gql/resolvers.py's _local_media_urls) - the same URLs a shop client reads.
// There is no separate local-cache proxy to go through here any more.
const CARDS_QUERY = `
    query Cards($page: Int!, $pageSize: Int!, $appType: [AppType!], $search: String,
                $owned: Boolean, $upToDate: Boolean, $complete: Boolean, $orderBy: OrderBy) {
        apps(groupByAppId: true, orderBy: $orderBy, page: $page, pageSize: $pageSize,
             appType: $appType, search: $search, owned: $owned,
             upToDate: $upToDate, complete: $complete) {
            total
            items {
                appId
                appType
                owned
                titledb {
                    name description developer publisher releaseDate bannerUrl iconUrl
                    category numberOfPlayers rating languages size
                    screenshots { url }
                }
                title { titleId name ownership { haveBase upToDate complete } }
                versions { version owned releaseDate }
            }
        }
    }`;

const ICONS_QUERY = `
    query Icons($page: Int!, $pageSize: Int!, $appType: [AppType!], $search: String,
                $owned: Boolean, $upToDate: Boolean, $complete: Boolean, $orderBy: OrderBy) {
        apps(groupByAppId: true, orderBy: $orderBy, page: $page, pageSize: $pageSize,
             appType: $appType, search: $search, owned: $owned,
             upToDate: $upToDate, complete: $complete) {
            total
            items {
                appId
                appType
                titledb {
                    name description developer publisher releaseDate iconUrl
                    category numberOfPlayers rating languages size
                    screenshots { url }
                }
                title { titleId name }
            }
        }
    }`;

// One row per game (title), with its owned base/update/DLC apps nested - this is
// what lets the list view show Base Game, Updates and DLC unified under one cover,
// instead of one card per app the way card/icon view do. `files` is admin-only and
// reads null for a shop-only viewer; the renderer falls back to titledb's own
// (coarser, title-level) size string in that case.
// One row per game (title), with its full catalogue picture nested underneath -
// every update and DLC titledb knows about, cross-referenced against what's
// actually owned in `apps`. Deliberately always `owned: true` at the title level
// (this lists games the library has *something* for). The toolbar's
// type/ownership/update/completion filters don't apply here (those are Card/Icon-
// only) - the List view's own filter is `libraryHealth` instead, which buckets a
// title by the worst state among *every* app it owns (base, update, and DLC
// together), not just the base. `files.id` is what a download button targets;
// `files` itself is admin-only and reads null for a shop-only viewer.
//
// Updates come from `updateApps` (ownfoil's own tracked apps, owned or not) rather
// than `availableVersions` (titledb's raw version catalogue): titledb sometimes
// lists a "v0" version entry that's really just documenting the base release's own
// version, not a real separate update package - the same distinction
// `Titles.up_to_date` (the server-computed "Latest Version" checkmark) is already
// based on. Sourcing from the raw catalogue instead produced a contradiction a user
// reported: a green "up to date" checkmark next to an Updates section showing that
// same version as Missing, because titledb's catalogue disagreed with what ownfoil
// itself considers a real update.
const LIST_QUERY = `
    query TitlesList($page: Int!, $pageSize: Int!, $search: String, $libraryHealth: LibraryHealth, $orderBy: OrderBy) {
        titles(owned: true, search: $search, libraryHealth: $libraryHealth, orderBy: $orderBy, page: $page, pageSize: $pageSize) {
            total
            items {
                titleId name intro description developer publisher releaseDate
                bannerUrl iconUrl size category numberOfPlayers rating languages
                screenshots { url }
                ownership { haveBase upToDate complete }
                apps(owned: true) {
                    appId appType appVersion releaseDate
                    downloadableFile { id size verificationStatus }
                }
                updateApps: apps(appType: [UPDATE]) {
                    appId appVersion releaseDate owned
                    downloadableFile { id size verificationStatus }
                }
                availableDlc {
                    appId version
                    titledb {
                        name description developer publisher releaseDate bannerUrl iconUrl
                        size category numberOfPlayers rating languages
                        screenshots { url }
                    }
                }
            }
        }
    }`;

function queryVariables() {
    let appType = null;
    if (activeTypeFilter) {
        appType = [activeTypeFilter];
    } else if (currentView === 'icon') {
        appType = ['BASE'];  // the icon wall is one icon per game, as it has always been
    } else {
        appType = ['BASE', 'DLC'];
    }
    const search = ($('#textFilter').val() || '').trim();
    return {
        page: currentPage,
        pageSize: itemsPerPage,
        appType: appType,
        search: search || null,
        owned: activeOwnershipFilter ? activeOwnershipFilter === 'Owned' : null,
        upToDate: activeUpdateFilter ? activeUpdateFilter === 'Up to date' : null,
        complete: activeCompletionFilter ? activeCompletionFilter === 'Complete' : null,
        orderBy: librarySort,
    };
}

/** The List view ignores the toolbar's type/ownership/update/completion filters
 *  entirely - only paging, the search box, and its own health filter carry over. */
function listQueryVariables() {
    const search = ($('#textFilter').val() || '').trim();
    return {
        page: currentPage,
        pageSize: itemsPerPage,
        search: search || null,
        libraryHealth: activeHealthFilter || null,
        orderBy: librarySort,
    };
}

async function loadPage() {
    const seq = ++fetchSeq;
    let data;
    try {
        if (currentView === 'list') {
            data = await gqlFetch(LIST_QUERY, listQueryVariables());
        } else if (currentView === 'icon') {
            data = await gqlFetch(ICONS_QUERY, queryVariables());
        } else {
            data = await gqlFetch(CARDS_QUERY, queryVariables());
        }
    } catch (e) {
        console.error(e);
        if (seq === fetchSeq) showLibraryState('libraryError');
        return;
    }
    if (seq !== fetchSeq) return; // a newer request is already on its way back

    const total = currentView === 'list' ? data.titles.total : data.apps.total;
    totalItems = total;
    const totalPages = Math.max(1, Math.ceil(totalItems / itemsPerPage));
    if (currentPage > totalPages) { // filters shrank the result under our feet
        currentPage = totalPages;
        return loadPage();
    }

    $('#cardSizeRange').val(cardSize);
    if (!totalItems) {
        showLibraryState(anyFilterOrSearch() ? 'libraryEmpty' : 'libraryEmptyLibrary');
    } else {
        showLibraryState(null);
    }
    if (currentView === 'list') {
        renderListView(data.titles.items);
    } else if (currentView === 'icon') {
        renderIconView(data.apps.items);
    } else {
        renderCardView(data.apps.items.map(cardModel));
    }
    updatePaginationControls(totalPages);
    restoreLibraryScroll();

    // init version tooltips
    const tooltipTriggerList = document.querySelectorAll('[data-bs-toggle="tooltip"]')
    const tooltipList = [...tooltipTriggerList].map(tooltipTriggerEl => new bootstrap.Tooltip(tooltipTriggerEl))

    // init version popovers
    const popoverTriggerList = document.querySelectorAll('[data-bs-toggle="popover"]')
    const popoverList = [...popoverTriggerList].map(popoverTriggerEl => new bootstrap.Popover(popoverTriggerEl))
}

// Library-wide, so the header stays put while filters and search move the grid.
const LIBRARY_STATS_QUERY = `
    query LibraryStats {
        stats {
            ownedTitles completeTitles upToDateTitles totalFiles totalSize
        }
    }`;

async function loadLibraryStats() {
    let stats;
    try {
        stats = (await gqlFetch(LIBRARY_STATS_QUERY)).stats;
    } catch (e) {
        console.error(e);
        return;
    }
    renderLibraryStats(stats);
}

/** The header's count, the four tiles and the "up to date" bar. These count games
 *  (titles); the pills under the toolbar count what the grid shows. */
function renderLibraryStats(stats) {
    // An empty install, or a visitor without shop access reading zeros: nothing to say.
    if (!stats.ownedTitles) return;
    const owned = stats.ownedTitles;
    const pending = stats.ownedTitles - stats.upToDateTitles;
    const missingDlc = stats.ownedTitles - stats.completeTitles;

    $('#libraryCount').text(owned.toLocaleString()).prop('hidden', false);

    // (value, label, icon, tone, pill it applies or null)
    const tiles = [
        [owned.toLocaleString(), I18N.tileGames, 'bi-controller', 'ok', null],
        [pending.toLocaleString(), I18N.tileUpdates, 'bi-arrow-up-circle', 'wait', 'outdated'],
        [missingDlc.toLocaleString(), I18N.tileMissingDlc, 'bi-puzzle', 'nav', 'missingDlc'],
    ];
    // File figures are admin only and read zero for every other role, which is what
    // keeps the library's storage footprint off a shop user's screen.
    if (stats.totalFiles) {
        tiles.push([formatBytes(stats.totalSize), I18N.tileSize, 'bi-hdd-stack', 'action', null]);
    }

    const box = $('#libraryTiles').empty();
    tiles.forEach(([value, label, icon, tone, pill]) => {
        const tile = $(pill ? '<button type="button">' : '<div>').addClass(`stat-tile stat-tile--${tone}`);
        tile.append($('<span class="stat-tile__icon">').append($('<i>').addClass(`bi ${icon}`)),
                    $('<div class="stat-tile__value">').text(value),
                    $('<div class="stat-tile__label">').text(label));
        if (pill) {
            tile.attr('data-pill', pill).on('click', () => {
                // These filters belong to the cards and icons: leave the list view first.
                if (currentView === 'list') $('#view-toggle-btn-card').trigger('click');
                applyPill(pill);
            });
        }
        box.append(tile);
    });
    box.prop('hidden', false);

    const pct = Math.round(100 * stats.upToDateTitles / owned);
    $('#libraryProgressLabel').text(I18N.progress
        .replace('{pct}', pct).replace('{n}', stats.upToDateTitles.toLocaleString())
        .replace('{total}', owned.toLocaleString()));
    $('#libraryProgress .progress').attr('aria-valuenow', pct);
    $('#libraryProgress .progress-bar').css('width', pct + '%');
    $('#libraryProgress').prop('hidden', false);
}

// What each card/icon pill sets: the update, completion and ownership filter groups.
// The state pills cover owned games only, like the header tiles that apply them: an
// unowned DLC or game is never "up to date", so without it "Update pending" would
// list the whole catalogue of missing content.
const CARD_PILLS = {
    all: {update: '', completion: '', ownership: ''},
    outdated: {update: 'Outdated', completion: '', ownership: 'Owned'},
    missingDlc: {update: '', completion: 'Missing DLC', ownership: 'Owned'},
    upToDate: {update: 'Up to date', completion: '', ownership: 'Owned'},
};

// What each list-view pill sets: the list's own health filter.
const LIST_PILLS = {all: '', complete: 'COMPLETE', incomplete: 'INCOMPLETE', corrupt: 'CORRUPT', repack: 'REPACK'};

// One request for every pill's count, with the grid's own variables minus the filter
// the pills set - so each count is exactly what clicking that pill returns.
const CARD_COUNTS_QUERY = `
    query CardCounts($appType: [AppType!], $search: String, $owned: Boolean) {
        all: apps(groupByAppId: true, appType: $appType, search: $search, owned: $owned, page: 1, pageSize: 1) { total }
        outdated: apps(groupByAppId: true, appType: $appType, search: $search, owned: true, upToDate: false, page: 1, pageSize: 1) { total }
        missingDlc: apps(groupByAppId: true, appType: $appType, search: $search, owned: true, complete: false, page: 1, pageSize: 1) { total }
        upToDate: apps(groupByAppId: true, appType: $appType, search: $search, owned: true, upToDate: true, page: 1, pageSize: 1) { total }
    }`;

const LIST_COUNTS_QUERY = `
    query ListCounts($search: String) {
        all: titles(owned: true, search: $search, page: 1, pageSize: 1) { total }
        complete: titles(owned: true, search: $search, libraryHealth: COMPLETE, page: 1, pageSize: 1) { total }
        incomplete: titles(owned: true, search: $search, libraryHealth: INCOMPLETE, page: 1, pageSize: 1) { total }
        corrupt: titles(owned: true, search: $search, libraryHealth: CORRUPT, page: 1, pageSize: 1) { total }
        repack: titles(owned: true, search: $search, libraryHealth: REPACK, page: 1, pageSize: 1) { total }
    }`;

let pillSeq = 0;      // like fetchSeq: an older count request never overwrites a newer one
let pillCounts = {};

async function loadPillCounts() {
    const seq = ++pillSeq;
    const list = currentView === 'list';
    let vars;
    if (list) {
        vars = {search: listQueryVariables().search};
    } else {
        const grid = queryVariables();
        vars = {appType: grid.appType, search: grid.search, owned: grid.owned};
    }
    let data;
    try {
        data = await gqlFetch(list ? LIST_COUNTS_QUERY : CARD_COUNTS_QUERY, vars);
    } catch (e) {
        console.error(e);
        data = null;
    }
    if (seq !== pillSeq) return;
    pillCounts = {};
    if (data) Object.keys(data).forEach(k => { pillCounts[k] = data[k].total; });
    renderPills();
}

/** The pill matching the current filters, or null when the Filters menu holds a
 *  combination no pill stands for (e.g. "Complete"). */
function activePill() {
    if (currentView === 'list') {
        return Object.keys(LIST_PILLS).find(k => LIST_PILLS[k] === activeHealthFilter) || null;
    }
    return Object.keys(CARD_PILLS).find(k =>
        CARD_PILLS[k].update === activeUpdateFilter && CARD_PILLS[k].completion === activeCompletionFilter
        && CARD_PILLS[k].ownership === activeOwnershipFilter) || null;
}

function renderPills() {
    const names = currentView === 'list' ? Object.keys(LIST_PILLS) : Object.keys(CARD_PILLS);
    const active = activePill();
    const row = $('#libraryPills').empty();
    names.forEach(name => {
        const pill = $('<button type="button" class="filter-pill">')
            .toggleClass('active', name === active)
            .attr('aria-pressed', name === active ? 'true' : 'false')
            .append($('<span>').text(I18N.pills[name]));
        if (pillCounts[name] !== undefined) {
            pill.append($('<span class="filter-pill__count">').text(pillCounts[name].toLocaleString()));
        }
        pill.on('click', () => applyPill(name));
        row.append(pill);
    });
}

/** Set the filters a pill (or a header tile) stands for, through the same radios the
 *  Filters menu uses, so both always agree. */
function applyPill(name) {
    if (currentView === 'list') {
        if (!(name in LIST_PILLS)) return;
        const health = LIST_PILLS[name];
        $('#healthAll').prop('checked', !health);
        $('#healthComplete').prop('checked', health === 'COMPLETE');
        $('#healthIncomplete').prop('checked', health === 'INCOMPLETE');
        $('#healthCorrupt').prop('checked', health === 'CORRUPT');
        $('#healthRepack').prop('checked', health === 'REPACK');
        onFilterChange();
        return;
    }
    const pill = CARD_PILLS[name];
    if (!pill) return;
    $('#updateAll').prop('checked', !pill.update);
    $('#updateUpToDate').prop('checked', pill.update === 'Up to date');
    $('#updateMissingUpdate').prop('checked', pill.update === 'Outdated');
    $('#completionAll').prop('checked', !pill.completion);
    $('#completionComplete').prop('checked', pill.completion === 'Complete');
    $('#completionMissingDlc').prop('checked', pill.completion === 'Missing DLC');
    $('#ownershipAll').prop('checked', !pill.ownership);
    $('#ownershipOwned').prop('checked', pill.ownership === 'Owned');
    $('#ownershipMissing').prop('checked', false);
    onFilterChange();
}

// Back from a game page, the browser can't restore the scroll position itself: the
// grid is drawn after its data arrives. The position is kept per tab when leaving and
// put back once, after the first grid is on screen.
let scrollToRestore = null;
try {
    scrollToRestore = parseInt(sessionStorage.getItem('libraryScroll'));
    sessionStorage.removeItem('libraryScroll');
} catch (e) { /* storage unavailable: start at the top */ }
window.addEventListener('pagehide', () => {
    try { sessionStorage.setItem('libraryScroll', String(Math.round(window.scrollY))); } catch (e) { /* ignore */ }
});

function restoreLibraryScroll() {
    if (!(scrollToRestore > 0)) return;
    const y = scrollToRestore;
    scrollToRestore = null;
    // The header tiles and pills arrive on their own requests: until they do, the
    // page may be too short to reach y. Try for about a second, then give up.
    let tries = 0;
    const attempt = () => {
        const reachable = document.documentElement.scrollHeight - window.innerHeight >= y;
        if (reachable || tries >= 10) {
            window.scrollTo(0, y);
            return;
        }
        tries += 1;
        setTimeout(attempt, 100);
    };
    // A timer, not an animation-frame callback: those don't run in a background tab.
    setTimeout(attempt, 0);
}

function goToPage(page) {
    currentPage = page;
    loadPage();
}

/** Search, filters, view, sort or page size changed: back to page 1, and the pill
 *  counts follow (paging alone never changes them). */
function resetToFirstPage() {
    currentPage = 1;
    loadPage();
    loadPillCounts();
}

/** The metadata-modal object for one app - shared by cardModel (Card view) and
 *  iconMeta (Icon view), so both open the same modal with the same data on a
 *  cover click. `id` is the title's own id for a BASE app (its own metadata is
 *  the title's), or the app's own id for an UPDATE/DLC. */
function metaFromApp(app, name) {
    const meta = app.titledb || {};
    const title = app.title || {};
    return {
        id: app.appType === 'BASE' ? title.titleId : app.appId,
        name: name,
        developer: meta.developer, publisher: meta.publisher, releaseDate: meta.releaseDate,
        description: meta.description, category: meta.category,
        numberOfPlayers: meta.numberOfPlayers, rating: meta.rating, languages: meta.languages,
        size: meta.size, screenshots: meta.screenshots, appType: app.appType,
        bannerUrl: meta.bannerUrl, iconUrl: meta.iconUrl,
    };
}

/**
 * One card from one app. A BASE app speaks for its title: ownership and the update
 * history come from the title, since a Switch update ships under its own app id.
 * A DLC app speaks for itself, and is up to date when its highest known version is
 * the one owned.
 */

/** The game page for an app: a game's own page, a DLC's game's page scrolled to that
 *  DLC, or - for a DLC whose game the library doesn't know - the DLC's own id. */
function gameUrl(app) {
    const title = app.title || {};
    if (app.appType === 'BASE') return `/game/${title.titleId || app.appId}`;
    return title.titleId ? `/game/${title.titleId}?dlc=${app.appId}` : `/game/${app.appId}`;
}

function cardModel(app) {
    const meta = app.titledb || {};
    const title = app.title || {};
    const ownership = title.ownership || {haveBase: false, upToDate: false, complete: false};
    const versions = (app.versions || []).map(v => ({
        version: v.version,
        owned: v.owned,
        release_date: v.releaseDate || 'Unknown',
    }));
    const isBase = app.appType === 'BASE';
    const recognized = isBase ? !!title.name : !!meta.name;
    // Straight off `titledb.bannerUrl`/`iconUrl` - already resolved server-side
    // to /api/media/... or the titledb hotlink (see gql/resolvers.py's
    // _local_media_urls). Empty when titledb has nothing for this app at all: the
    // card then draws its own placeholder (no external image service).
    const bannerUrl = meta.bannerUrl || '';
    const iconUrl = meta.iconUrl || '';

    if (isBase) {
        return {
            id: recognized ? title.titleId : title.titleId + ' ' + I18N.notFoundInTitledb,
            title_id_name: title.name || I18N.unrecognized,
            name: title.name || I18N.unrecognized,
            bannerUrl: bannerUrl,
            iconUrl: iconUrl,
            app_type: 'BASE',
            owned: ownership.haveBase,
            has_latest_version: ownership.haveBase && ownership.upToDate,
            has_all_dlcs: ownership.complete,
            version: versions,
            meta: metaFromApp(app, title.name || I18N.unrecognized),
            url: gameUrl(app),
        };
    }

    const ownedVersions = versions.filter(v => v.owned).map(v => v.version);
    const highest = versions.length ? Math.max(...versions.map(v => v.version)) : 0;
    return {
        id: recognized ? app.appId : app.appId + ' ' + I18N.notFoundInTitledb,
        title_id_name: title.name || I18N.unrecognized,
        name: meta.name || I18N.unrecognized,
        bannerUrl: bannerUrl,
        iconUrl: iconUrl,
        app_type: app.appType,
        owned: app.owned,
        has_latest_version: ownedVersions.length > 0 && Math.max(...ownedVersions) >= highest,
        version: versions,
        meta: metaFromApp(app, meta.name || I18N.unrecognized),
        url: gameUrl(app),
    };
}

/** "Publisher · 2021" (either part may be missing), from the catalogue's metadata. */
function cardMetaLine(meta) {
    const year = String(meta.releaseDate || '').match(/\d{4}/);
    return [meta.publisher, year && year[0]].filter(Boolean).join(' · ');
}

function renderCardView(games) {
    const gameGrid = $('#gameGrid');
    gameGrid.empty(); // Clear existing games

    games.forEach(function (game) {
        const gameCol = $('<div class="col game-col"></div>').addClass(cardColumnClasses());
        const isDlc = game.app_type === 'DLC';

        const card = $('<div class="card game-surface game-card library-card"></div>')
            .toggleClass('is-missing', game.owned === false);

        const coverWrap = $('<div class="library-cover-wrap">');
        const cover = game.bannerUrl
            ? $('<img class="library-cover" loading="lazy" alt="">').attr('src', game.bannerUrl)
            : $('<div class="library-cover library-cover--empty"><i class="bi bi-controller" aria-hidden="true"></i></div>');
        // An artwork URL that fails to load shows the same placeholder.
        cover.filter('img').on('error', function () {
            $(this).replaceWith($('<div class="library-cover library-cover--empty"><i class="bi bi-controller" aria-hidden="true"></i></div>'));
        });
        // The cover is a real link: middle-click and "open in a new tab" work.
        coverWrap.append($('<a class="library-cover-link" tabindex="-1" aria-hidden="true">')
            .attr('href', game.url).append(cover));

        // State badges, one fixed color per meaning (design tokens).
        const badges = $('<div class="library-badges">');
        if (isDlc) badges.append(statusBadge('', 'bi-puzzle', I18N.badgeDlc));
        if (game.owned === false) {
            badges.append(statusBadge('wait', 'bi-dash-circle', I18N.missing));
        } else {
            const outdated = game.has_latest_version === false;
            const missingDlc = game.has_all_dlcs === false;
            if (outdated) badges.append(statusBadge('wait', 'bi-arrow-up-circle', I18N.badgeUpdate));
            if (missingDlc) badges.append(statusBadge('dlc', 'bi-puzzle', I18N.badgeMissingDlc));
            if (!outdated && !missingDlc) badges.append(statusBadge('ok', 'bi-check-circle', I18N.badgeComplete));
        }
        coverWrap.append(badges);
        card.append(coverWrap);

        const body = $('<div class="library-card-body">');
        // A DLC card is named after the DLC, with its game underneath; a game card
        // after the game.
        const name = isDlc ? game.name : (game.title_id_name || game.name);
        body.append($('<h5 class="game-title library-card-title">').append(
            $('<a class="stretched-link library-card-link">').attr('href', game.url).text(name).attr('title', name)));
        const metaLine = isDlc ? game.title_id_name : cardMetaLine(game.meta);
        if (metaLine) body.append($('<p class="library-card-meta">').text(metaLine));

        const foot = $('<div class="library-card-foot">');
        foot.append($('<small class="library-card-id">').text(game.id));
        if (Array.isArray(game.version) && game.version.length) {
            // Built via .text() per line, not string-interpolated into HTML directly -
            // release dates and version numbers are real (untrusted) catalogue data,
            // and this keeps them escaped even though the popover renders HTML for
            // the line breaks.
            const list = $('<div class="version-popover-list"></div>');
            game.version.forEach(version => {
                list.append($('<div></div>').text(
                    `${version.release_date}: v${version.version} — ${version.owned ? I18N.owned : I18N.missing}`
                ));
            });
            const versions = $('<button type="button" class="icon-btn library-versions">')
                .attr({title: I18N.versions, 'aria-label': I18N.versions})
                .append('<i class="bi bi-clock-history"></i>');
            versions.popover({content: list.html(), html: true, trigger: 'click', placement: 'top'});
            foot.append(versions);
        }
        body.append(foot);

        card.append(body);
        gameCol.append(card);
        gameGrid.append(gameCol);
    });
}

/** Icon view's equivalent of cardModel - much less display data (just the icon
 *  image itself), but the same metadata-modal object on click. */
function iconModel(app) {
    const meta = app.titledb || {};
    const title = app.title || {};
    const name = app.appType === 'BASE' ? (title.name || I18N.unrecognized) : (meta.name || I18N.unrecognized);
    return {
        iconUrl: meta.iconUrl || '',
        name: name,
        url: gameUrl(app),
    };
}

function renderIconView(apps) {
    const gameGrid = $('#gameGrid');
    gameGrid.empty(); // Clear existing games

    apps.map(iconModel).forEach(icon => {
        const img = $('<img class="game-icon library-icon" loading="lazy" alt="">').attr('src', icon.iconUrl);
        gameGrid.append($('<a class="library-icon-link">').attr({href: icon.url, title: icon.name, 'aria-label': icon.name})
            .append(img));
    });

    // Adjust icon sizes based on the slider value
    adjustIconSizes(cardSize);
}

// --- List view: one row per game, with Base/Updates/DLC unified underneath ---
// Always shows the full catalogue picture (every update and DLC titledb knows
// about, owned or not) for every title the library has at least something for -
// deliberately independent of the toolbar filters, which only make sense for the
// per-app Card/Icon views. Ownership/verification/size come from the library's own
// data; nothing here is invented.

/** An app's file size, verification status, and downloadable id - all sourced
 *  from `downloadableFile`, which (unlike the full `files` connection) is visible
 *  to any shop-access viewer, not just an admin. Null across the board when the
 *  app isn't owned. */
function appSize(app) {
    const f = app && app.downloadableFile;
    return f ? f.size : null;
}

function appVerification(app) {
    const f = app && app.downloadableFile;
    return f ? f.verificationStatus : null;
}

/** The owned file id for an app, or null - what a download button targets. */
function appFileId(app) {
    const f = app && app.downloadableFile;
    return f ? f.id : null;
}

// --- Metadata modal: one shared modal, populated per click --------------------

/** A small info-circle link to the game page (`meta.url`) - distinct from the
 *  verification icon, which uses a question mark for a different meaning
 *  (unverified). */
function metadataButton(meta) {
    if (!meta || !meta.url) return null;
    return $('<a class="btn btn-sm icon-btn p-0"><i class="bi bi-info-circle"></i></a>')
        .attr({href: meta.url, title: I18N.detailsTooltip, 'aria-label': I18N.detailsTooltip});
}

/** One row inside a Base Game / Updates / DLC group: a label on the left, an
 *  Owned/Missing badge, size, verification, metadata and (when enabled) download
 *  controls on the right. All text goes through .text(), never raw HTML, since it
 *  can carry a game's real (untrusted) name. */
function buildContentRow({label, sub, owned, size, verification, fileId, meta}) {
    const li = $('<li class="list-group-item bg-transparent d-flex justify-content-between align-items-center flex-wrap gap-2"></li>');
    const left = $('<span class="text-break"></span>').text(label);
    if (sub) {
        left.append($('<small class="text-secondary ms-1"></small>').text(`(${sub})`));
    }
    const right = $('<span class="d-flex align-items-center gap-2 flex-shrink-0"></span>');
    right.append($('<span class="badge rounded-pill"></span>')
        .addClass(owned ? 'text-bg-success' : 'text-bg-warning')
        .text(owned ? I18N.owned : I18N.missing));
    if (size != null) {
        right.append($('<span class="badge text-bg-secondary"></span>').text(formatBytes(size)));
    }
    if (owned) {
        const verBadge = verificationBadge(verification);
        if (verBadge) right.append(verBadge);
    }
    const metaBtn = metadataButton(meta);
    if (metaBtn) right.append(metaBtn);
    if (owned && fileId != null && IS_SHOP && WEB_DOWNLOADS_ENABLED) {
        right.append(downloadButton(fileId, label));
    }
    return li.append(left).append(right);
}

let listSectionSeq = 0;

/** A collapsible "Updates" or "DLC" group: a header row with a count badge and a
 *  chevron that flips on expand (see .list-section-trigger in style.css), holding
 *  the individual content rows underneath. */
function buildCollapsibleSection(sectionTitle, count, rows) {
    const id = `listSection${listSectionSeq++}`;
    const li = $('<li class="list-group-item bg-transparent"></li>');
    const trigger = $('<p class="my-1 d-flex justify-content-between align-items-center list-section-trigger" role="button" aria-expanded="false"></p>')
        .attr('data-bs-toggle', 'collapse')
        .attr('data-bs-target', `#${id}`)
        .attr('aria-controls', id);
    trigger.append($('<strong></strong>').text(sectionTitle));
    const right = $('<span class="d-flex align-items-center gap-2"></span>');
    right.append($('<span class="badge text-bg-secondary"></span>').text(count));
    right.append($('<i class="bi bi-chevron-down list-chevron"></i>'));
    trigger.append(right);
    li.append(trigger);

    const collapseDiv = $('<div class="collapse"></div>').attr('id', id);
    const innerList = $('<ul class="list-group list-group-flush mt-1"></ul>');
    rows.forEach(r => innerList.append(r));
    collapseDiv.append(innerList);
    li.append(collapseDiv);
    return li;
}

/** A further-nested "N older versions" disclosure, collapsed by default, sitting
 *  as the last row *inside* an already-expanded Updates section - not moved out
 *  to a separate section. Only versions older than the highest one owned end up
 *  behind this toggle; anything newer than what's owned (including everything, if
 *  nothing is owned yet) stays directly visible, since that's the actionable part
 *  of a 26-version update history, not the 25 old ones nobody needs to see by
 *  default. */
function buildOlderVersionsToggle(rows) {
    const id = `listOlder${listSectionSeq++}`;
    const li = $('<li class="list-group-item bg-transparent"></li>');
    const trigger = $('<p class="my-1 d-flex align-items-center gap-2 list-section-trigger list-older-trigger" role="button" aria-expanded="false"></p>')
        .attr('data-bs-toggle', 'collapse')
        .attr('data-bs-target', `#${id}`)
        .attr('aria-controls', id);
    trigger.append($('<i class="bi bi-chevron-down list-chevron"></i>'));
    trigger.append($('<small></small>').text(
        (rows.length === 1 ? I18N.olderVersionsOne : I18N.olderVersionsMany).replace('{n}', rows.length)));
    li.append(trigger);

    const collapseDiv = $('<div class="collapse"></div>').attr('id', id);
    const innerList = $('<ul class="list-group list-group-flush mt-1"></ul>');
    rows.forEach(r => innerList.append(r));
    collapseDiv.append(innerList);
    li.append(collapseDiv);
    return li;
}

function renderListView(titles) {
    const gameGrid = $('#gameGrid');
    gameGrid.empty();

    titles.forEach(function (t) {
        const apps = t.apps || [];
        const baseApp = apps.find(a => a.appType === 'BASE');
        const ownedDlcByAppId = new Map(
            apps.filter(a => a.appType === 'DLC').map(a => [a.appId, a]));

        // Every update ownfoil itself tracks for this title, owned or not - the
        // same source `ownership.upToDate` is computed from server-side, so the
        // "Latest Version" checkmark and this list never disagree with each other.
        const updateApps = (t.updateApps || [])
            .slice().sort((a, b) => b.appVersion - a.appVersion);
        // titledb's own DLC catalogue - whichever entries it happens to know
        // about. Merged below with what's actually owned (ownfoil identifies a
        // DLC directly from the file, independent of titledb), since relying on
        // this alone would hide a DLC the library actually has whenever titledb's
        // catalogue for this title is incomplete.
        const availableDlc = t.availableDlc || [];

        const ownership = t.ownership || {haveBase: false, upToDate: false, complete: false};

        const col = $('<div class="col-12"></div>');
        const card = $('<div class="card game-surface list-game-card mb-3"></div>');
        if (t.titleId && t.bannerUrl && SHOW_GAME_BACKGROUND_IMAGE) {
            // Sits behind the whole card - see .list-card-body's own gradient in
            // style.css for the fixed-pixel fade zone that keeps contrast readable
            // even on a tall expanded card (the fade has to live there, in front,
            // not on this element - see that class's comment for why). Straight
            // off `titles.items.bannerUrl` - already resolved server-side to
            // /api/media/... or the titledb hotlink. Skipped entirely when the
            // Organizer's "show background image" setting is off; .list-cover
            // (the cover icon) is appended unconditionally below, unaffected.
            card.append($('<div class="list-banner-strip"></div>')
                .css('background-image', `url("${t.bannerUrl}")`));
        }

        // .no-banner lightens the text-shadow (see style.css) when there's no banner
        // image behind the text to need heavy contrast against - full shadow stays
        // exactly as it is whenever the banner is showing.
        const body = $('<div class="card-body list-card-body"></div>')
            .toggleClass('no-banner', !SHOW_GAME_BACKGROUND_IMAGE);
        const headerRow = $('<div class="d-flex align-items-start gap-3"></div>');

        if (t.titleId && t.iconUrl) {
            headerRow.append($('<img class="list-cover rounded flex-shrink-0">')
                .attr('src', t.iconUrl));
        }

        const headerText = $('<div class="flex-grow-1 min-w-0 list-header-text"></div>');
        const titleLine = $('<h5 class="card-title mb-1 d-flex align-items-center gap-2"></h5>');
        titleLine.append($('<a class="list-title-link"></a>').attr('href', `/game/${t.titleId}`)
            .text(t.name || I18N.unrecognized));
        const titleMetaBtn = metadataButton({
            id: t.titleId, url: `/game/${t.titleId}`,
        });
        if (titleMetaBtn) titleLine.append(titleMetaBtn);
        headerText.append(titleLine);
        if (t.intro) {
            headerText.append($('<p class="card-text small text-secondary mb-1"></p>').text(t.intro));
        }

        const latestVersion = updateApps.length ? updateApps[0].appVersion : 0;
        const latestDate = updateApps.length ? updateApps[0].releaseDate : null;
        const versionLine = $('<p class="small mb-0 d-flex align-items-center gap-2"></p>');
        versionLine.append($('<strong></strong>').text(I18N.latestVersion));
        const versionBadge = $('<span class="badge rounded-pill"></span>')
            .addClass(ownership.upToDate ? 'text-bg-success' : 'text-bg-warning')
            .text(`v${latestVersion}`);
        versionLine.append(versionBadge);
        if (latestDate) {
            versionLine.append($('<span class="text-secondary"></span>').text(`(${latestDate})`));
        }
        versionLine.append($('<i class="bi"></i>').addClass(
            ownership.upToDate ? 'bi-check-circle-fill text-success' : 'bi-arrow-down-circle text-warning'));
        headerText.append(versionLine);

        headerRow.append(headerText);
        body.append(headerRow);

        // .list-top-group (not just .list-group-flush) scopes the "always show a
        // divider above the base-game row" CSS rule to this outer list only - the
        // nested Updates/DLC collapsible sections build their own
        // .list-group-flush below and must keep Bootstrap's normal behavior.
        const listGroup = $('<ul class="list-group list-group-flush list-top-group mt-3"></ul>');

        listGroup.append(buildContentRow({
            label: I18N.baseGame,
            owned: ownership.haveBase,
            size: appSize(baseApp),
            verification: appVerification(baseApp),
            fileId: appFileId(baseApp),
            meta: {id: t.titleId, url: `/game/${t.titleId}`},
        }));

        if (updateApps.length) {
            // Only versions *older* than the highest one owned get tucked behind
            // the nested toggle - anything newer than what's owned always shows
            // directly, since that's the part worth noticing. With nothing owned
            // yet there's no reference point, so everything shows directly.
            const ownedVersionNumbers = updateApps.filter(a => a.owned).map(a => a.appVersion);
            const highestOwned = ownedVersionNumbers.length ? Math.max(...ownedVersionNumbers) : null;
            const buildUpdateRow = a => buildContentRow({
                label: `v${a.appVersion}`,
                sub: a.releaseDate,
                owned: a.owned,
                size: appSize(a),
                verification: appVerification(a),
                fileId: appFileId(a),
            });

            const recentApps = highestOwned == null ? updateApps
                : updateApps.filter(a => a.appVersion >= highestOwned);
            const olderApps = highestOwned == null ? []
                : updateApps.filter(a => a.appVersion < highestOwned);

            const updateRows = recentApps.map(buildUpdateRow);
            if (olderApps.length) {
                updateRows.push(buildOlderVersionsToggle(olderApps.map(buildUpdateRow)));
            }
            listGroup.append(buildCollapsibleSection(I18N.updatesSection, updateApps.length, updateRows));
        }

        if (availableDlc.length || ownedDlcByAppId.size) {
            // Merge titledb's catalogue with what's actually owned: ownfoil
            // identifies a DLC straight from the file's own embedded data,
            // independent of titledb, so a title whose titledb catalogue entry is
            // incomplete (or missing entirely) for some of its DLC must still show
            // the ones actually organized on disk - never silently drop them just
            // because titledb doesn't know about them yet.
            const dlcByAppId = new Map();
            availableDlc.forEach(d => dlcByAppId.set(d.appId, d));
            ownedDlcByAppId.forEach((ownedApp, appId) => {
                if (!dlcByAppId.has(appId)) {
                    dlcByAppId.set(appId, {appId, version: ownedApp.appVersion, titledb: null});
                }
            });
            const allDlc = [...dlcByAppId.values()];

            listGroup.append(buildCollapsibleSection(I18N.dlcSection, allDlc.length,
                allDlc.map(d => {
                    const ownedApp = ownedDlcByAppId.get(d.appId);
                    const dlcMeta = d.titledb || {};
                    return buildContentRow({
                        label: dlcMeta.name || I18N.dlcFallbackName,
                        owned: !!ownedApp,
                        size: appSize(ownedApp),
                        verification: appVerification(ownedApp),
                        fileId: appFileId(ownedApp),
                        meta: {id: d.appId, url: `/game/${t.titleId}?dlc=${d.appId}`},
                    });
                })));
        }

        body.append(listGroup);
        card.append(body);
        col.append(card);
        gameGrid.append(col);
    });
}

/** The slider sets how many cards a row holds, but only from `md` up: below that
 *  the screen cannot carry six of them, and a card too narrow to fit its own title
 *  grows an overlay taller than the banner it sits on. */
function cardColumnClasses() {
    const columns = getColumnsForCardSize(cardSize);
    // Phones always get two columns: one card per row is a lot of scrolling.
    return `col-6 col-md-${12 / columns}`;
}

function getColumnsForCardSize(size) {
    switch (size) {
        case 1: return 1; // 2 columns
        case 2: return 2; // 3 columns
        case 3: return 3; // 4 columns
        case 4: return 4; // 6 columns
        case 5: return 6; // 8 columns
        default: return 4; // default to 3 columns
    }
}

/** Page numbers around the current one: the totals are server-side now, and a
 *  library of a few thousand apps would otherwise render a few hundred buttons. */
function pageWindow(totalPages) {
    const pages = new Set([1, totalPages]);
    for (let i = currentPage - 2; i <= currentPage + 2; i++) {
        if (i >= 1 && i <= totalPages) pages.add(i);
    }
    const sorted = [...pages].sort((a, b) => a - b);
    const out = [];
    let previous = 0;
    for (const p of sorted) {
        if (previous && p - previous > 1) out.push('...');
        out.push(p);
        previous = p;
    }
    return out;
}

/** Builds one set of pagination <li> elements (prev, page numbers, next) with
 *  their click handlers attached, appending clones of it into every target <ul>
 *  given - clones because a single DOM node can only live in one place, but the
 *  top and bottom pagination bars show the exact same state. `.clone(true)`
 *  copies the attached jQuery event handlers along with the markup, so every
 *  clone stays clickable. */
function updatePaginationControls(totalPages) {
    const targets = [$('#paginationControlsTop'), $('#paginationControlsBottom')];
    targets.forEach(t => t.empty());

    const items = [];

    // Previous button
    const prevButton = $('<li class="page-item"></li>').addClass(`page-item ${currentPage === 1 ? 'disabled' : ''}`).html(`
            <a class="page-link" href="#" aria-label="${I18N.previous}">
                <span aria-hidden="true">&laquo;</span>
            </a>`);
    prevButton.click(function (e) {
        e.preventDefault();
        if (currentPage > 1) {
            goToPage(currentPage - 1);
        }
    });
    items.push(prevButton);

    // Page numbers
    for (const entry of pageWindow(totalPages)) {
        if (entry === '...') {
            items.push($('<li class="page-item disabled"></li>').html('<span class="page-link">&hellip;</span>'));
            continue;
        }
        const pageButton = $('<li class="page-item"></li>').addClass(`page-item ${entry === currentPage ? 'active' : ''}`).html(`<a class="page-link" href="#">${entry}</a>`);
        pageButton.click(function (e) {
            e.preventDefault();
            goToPage(entry);
        });
        items.push(pageButton);
    }

    // Next button
    const nextButton = $('<li class="page-item"></li>').addClass(`page-item ${currentPage === totalPages ? 'disabled' : ''}`).html(`
            <a class="page-link" href="#" aria-label="${I18N.next}">
                <span aria-hidden="true">&raquo;</span>
            </a>`);
    nextButton.click(function (e) {
        e.preventDefault();
        if (currentPage < totalPages) {
            goToPage(currentPage + 1);
        }
    });
    items.push(nextButton);

    targets.forEach(target => {
        items.forEach(item => target.append(item.clone(true)));
    });
}

function adjustCardSizes() {
    const gameGrid = $('#gameGrid');
    const gameCols = gameGrid.find('.game-col');
    gameCols.each(function () {
        $(this).removeClass().addClass(`col game-col ${cardColumnClasses()}`);
    });
}

function adjustIconSizes() {
    // Calculate the size of the icons based on the slider value
    const iconSize = 100 / (cardSize + 3); // Assuming 100 is the maximum size

    // Update the CSS of the game icons
    $('.library-icon-link').css('width', `${iconSize}%`);
}

function saveFiltersToStorage() {
    storageSet('activeFilters', JSON.stringify({
        type: activeTypeFilter,
        ownership: activeOwnershipFilter,
        update: activeUpdateFilter,
        completion: activeCompletionFilter,
        health: activeHealthFilter,
    }));
}

function loadFiltersFromStorage() {
    let filters = null;
    try { filters = JSON.parse(storageGet('activeFilters') || 'null'); } catch (e) { /* unreadable: no filters */ }
    if (filters && typeof filters === 'object') {

        $('#typeBase').prop('checked', filters.type === 'BASE');
        $('#typeDlc').prop('checked', filters.type === 'DLC');

        $('#ownershipOwned').prop('checked', filters.ownership === 'Owned');
        $('#ownershipMissing').prop('checked', filters.ownership === 'Missing');

        $('#updateUpToDate').prop('checked', filters.update === 'Up to date');
        $('#updateMissingUpdate').prop('checked', filters.update === 'Outdated');

        $('#completionComplete').prop('checked', filters.completion === 'Complete');
        $('#completionMissingDlc').prop('checked', filters.completion === 'Missing DLC');

        $('#healthComplete').prop('checked', filters.health === 'COMPLETE');
        $('#healthIncomplete').prop('checked', filters.health === 'INCOMPLETE');
        $('#healthCorrupt').prop('checked', filters.health === 'CORRUPT');
        $('#healthRepack').prop('checked', filters.health === 'REPACK');

        updateFilter();
    }

    const savedSearch = storageGet('searchTerm');
    if (savedSearch) {
        $('#textFilter').val(savedSearch);
    }
    // ?q= from the global search (Ctrl+K) wins over the remembered search.
    const urlSearch = new URLSearchParams(location.search).get('q');
    if (urlSearch) {
        $('#textFilter').val(urlSearch);
    }
}

/** Read the filter controls into the active* variables the query is built from. */
function updateFilter() {
    if ($('#typeBase').is(":checked")) {
        activeTypeFilter = 'BASE';
    } else if ($('#typeDlc').is(":checked")) {
        activeTypeFilter = 'DLC';
    } else {
        activeTypeFilter = '';
    }
    if ($('#ownershipOwned').is(":checked")) {
        activeOwnershipFilter = 'Owned';
    } else if ($('#ownershipMissing').is(":checked")) {
        activeOwnershipFilter = 'Missing';
    } else {
        activeOwnershipFilter = '';
    }
    if ($('#updateUpToDate').is(":checked")) {
        activeUpdateFilter = 'Up to date';
    } else if ($('#updateMissingUpdate').is(":checked")) {
        activeUpdateFilter = 'Outdated';
    } else {
        activeUpdateFilter = '';
    }
    if ($('#completionComplete').is(":checked")) {
        activeCompletionFilter = 'Complete';
    } else if ($('#completionMissingDlc').is(":checked")) {
        activeCompletionFilter = 'Missing DLC';
    } else {
        activeCompletionFilter = '';
    }
    if ($('#healthComplete').is(":checked")) {
        activeHealthFilter = 'COMPLETE';
    } else if ($('#healthIncomplete').is(":checked")) {
        activeHealthFilter = 'INCOMPLETE';
    } else if ($('#healthCorrupt').is(":checked")) {
        activeHealthFilter = 'CORRUPT';
    } else if ($('#healthRepack').is(":checked")) {
        activeHealthFilter = 'REPACK';
    } else {
        activeHealthFilter = '';
    }
}

/** Show one of the grid's stand-ins (or none), hiding the grid and paging with it. */
function showLibraryState(id) {
    ['libraryEmpty', 'libraryEmptyLibrary', 'libraryError'].forEach(state => {
        $('#' + state).prop('hidden', state !== id);
    });
    $('#gridContainer, #paginationControlsTop, #paginationControlsBottom').toggleClass('d-none', !!id);
}

/** Is anything narrowing the current view's results? */
function anyFilterOrSearch() {
    const search = ($('#textFilter').val() || '').trim();
    if (currentView === 'list') return !!(search || activeHealthFilter);
    return !!(search || activeTypeFilter || activeOwnershipFilter || activeUpdateFilter || activeCompletionFilter);
}

/** "Clear filters": every filter group back to All, the search emptied - both
 *  remembered that way - and back to page 1. */
function clearAllFilters() {
    ['#typeAll', '#ownershipAll', '#updateAll', '#completionAll', '#healthAll'].forEach(id => $(id).prop('checked', true));
    $('#textFilter').val('');
    storageRemove('searchTerm');
    updateFilter();
    saveFiltersToStorage();
    updateFiltersDot();
    resetToFirstPage();
}

/** A typed page size as a whole number from 1 to 500 - the most the server returns
 *  for a list page - or null when it isn't a number. Larger values would page past
 *  rows the server never sends; fractions would make zero-sized pages. */
function clampPageSize(value) {
    const n = Math.floor(Number(value));
    if (!Number.isFinite(n) || n < 1) return null;
    return Math.min(500, n);
}

function onFilterChange() {
    updateFilter();
    saveFiltersToStorage();
    updateFiltersDot();
    resetToFirstPage();
}

/** The Filters button's dot: some filter that applies to the current view is set. */
function updateFiltersDot() {
    const active = currentView === 'list'
        ? !!activeHealthFilter
        : !!(activeTypeFilter || activeOwnershipFilter || activeUpdateFilter || activeCompletionFilter);
    $('#filtersActiveDot').prop('hidden', !active);
}

/** Show the toolbar parts that apply to the current view: card size for cards and
 *  icons, and each view's own filter groups. */
function applyViewToToolbar() {
    $('#cardSizeRangeCol').toggleClass('d-none', currentView === 'list');
    $('#filterDropdownCol').toggleClass('d-none', currentView === 'list');
    $('#listHealthFilterCol').toggleClass('d-none', currentView !== 'list');
    updateFiltersDot();
}

$(document).ready(function () {
    // Only sensible values are taken back: a bad page size or an unknown view would
    // otherwise reach the server as a failing query.
    const savedItemsPerPage = parseInt(storageGet('itemsPerPage'));
    if (savedItemsPerPage > 0 && savedItemsPerPage <= 500) {
        itemsPerPage = savedItemsPerPage;
    }

    const savedCurrentView = storageGet('currentView');
    if (['card', 'icon', 'list'].includes(savedCurrentView)) {
        currentView = savedCurrentView;
        $('.view-toggle-btn').removeClass("active");
        $(`.view-toggle-btn[data-view="${currentView}"]`).addClass("active");
        applyViewToToolbar();
    }

    const savedCardSize = parseInt(storageGet('cardSize'));
    if (savedCardSize >= 1 && savedCardSize <= 5) {
        cardSize = savedCardSize;
    }

    loadFiltersFromStorage();
    updateFiltersDot();
    loadSortFromStorage();
    $('#sortField').on('change', function () { setSort(this.value, librarySort.direction); });
    $('#sortDirection').on('click', () => setSort(librarySort.field, librarySort.direction === 'ASC' ? 'DESC' : 'ASC'));
    loadPage();
    loadLibraryStats();
    loadPillCounts();
    $('#clearFiltersBtn').on('click', clearAllFilters);
    $('#libraryRetryBtn').on('click', () => { loadPage(); loadLibraryStats(); loadPillCounts(); });

    // Event listeners for items per page dropdown
    $('.items-per-page').click(function () {
        itemsPerPage = $(this).data('value');
        storageSet('itemsPerPage', itemsPerPage);
        resetToFirstPage();
    });

    $('#applyCustomItemsPerPage').click(function () {
        const size = clampPageSize($('#customItemsPerPage').val());
        if (size) {
            itemsPerPage = size;
            $('#customItemsPerPage').val(size);
            storageSet('itemsPerPage', itemsPerPage);
            resetToFirstPage();
        }
    });

    // Event listener for card size slider
    $('#cardSizeRange').on('input', function () {
        cardSize = parseInt($(this).val());
        storageSet('cardSize', cardSize);
        if (currentView === 'icon') {
            adjustIconSizes(cardSize);
        } else {
            adjustCardSizes(cardSize);
        }
    });

    // Event listener for view buttons
    $('.view-toggle-btn').click(function () {
        $('.view-toggle-btn').removeClass("active");
        $(this).addClass("active");
        currentView = $(this).data('view');
        storageSet('currentView', currentView);
        applyViewToToolbar();
        // The views page different things (every card vs one icon per game), so the
        // page number from the previous view means nothing here.
        resetToFirstPage();
    });

    $('.type-toggle, .ownership-toggle, .update-toggle, .completion-toggle, .health-toggle').change(onFilterChange);

    // Listen to input changes in the text filter input
    $("#textFilter").on("input", function () {
        const attributeText = $(this).val();
        storageSet('searchTerm', attributeText);
        // Debounced: every keystroke would otherwise be its own query.
        clearTimeout(searchDebounce);
        searchDebounce = setTimeout(resetToFirstPage, 250);
    });

    // Close popovers
    $(document).on('click', function (e) {
        $('.popover').removeClass('show');
        $('.popover').remove();
    });

    // Add click event on the popover to stop propagation
    $(document).on('click', '.popover', function (e) {
        e.stopPropagation(); // Prevent the click event from bubbling up
    });

});
