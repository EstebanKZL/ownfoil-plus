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

let itemsPerPage = 20;      // the page size in use: pageTarget fitted to the columns shown
let pageTarget = 20;        // what was chosen: 10, 20 ... 100
let currentPage = 1;
// Only the signed-in user's favourites (the star), on top of the other filters.
let onlyFavorites = storageGet('libraryFavorites') === '1';
let favoriteIds = new Set();     // the user's starred title ids (/api/favorites)
// The console the cards show: '' both, 'switch', 'switch2' (remembered per browser).
let activeConsole = ['switch', 'switch2'].includes(storageGet('libraryConsole')) ? storageGet('libraryConsole') : '';
let totalItems = 0;
let currentView = 'card'; // Default view is 'card'
let fetchSeq = 0;    // guards against an older request answering after a newer one
let searchDebounce;

// Active filters
let activeOwnershipFilter = "";
let activeUpdateFilter = "";
let activeCompletionFilter = "";

// Sorting: the fields both the `apps` (cards, icons) and `titles` (list) queries sort
// on. ADDED_AT exists in the schema but only applies to `files`.
const SORT_FIELDS = ['NAME', 'RELEASE_DATE', 'REGION', 'SIZE', 'ADDED_AT', 'ID'];
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
    $('.sort-direction-btn').each(function () {
        const on = this.dataset.direction === librarySort.direction;
        $(this).toggleClass('active', on).attr('aria-pressed', on ? 'true' : 'false');
    });
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
                $owned: Boolean, $upToDate: Boolean, $complete: Boolean, $orderBy: OrderBy,
                $console: String, $favorite: Boolean) {
        apps(groupByAppId: true, orderBy: $orderBy, page: $page, pageSize: $pageSize,
             appType: $appType, search: $search, owned: $owned,
             upToDate: $upToDate, complete: $complete, console: $console, favorite: $favorite) {
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
                title { titleId name ownership { haveBase upToDate complete dlcOwned dlcTotal } }
                downloadableFile { format }
            }
        }
    }`;

const ICONS_QUERY = `
    query Icons($page: Int!, $pageSize: Int!, $appType: [AppType!], $search: String,
                $owned: Boolean, $upToDate: Boolean, $complete: Boolean, $orderBy: OrderBy,
                $console: String, $favorite: Boolean) {
        apps(groupByAppId: true, orderBy: $orderBy, page: $page, pageSize: $pageSize,
             appType: $appType, search: $search, owned: $owned,
             upToDate: $upToDate, complete: $complete, console: $console, favorite: $favorite) {
            total
            items {
                appId
                appType
                titledb {
                    name description developer publisher releaseDate iconUrl
                    category numberOfPlayers rating languages size
                    screenshots { url }
                }
                title { titleId name ownership { haveBase upToDate complete dlcOwned dlcTotal } }
                downloadableFile { format }
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
// (this lists games the library has *something* for). It takes the same filters
// and pills as the cards: ownership, updates and DLC (TitleFilter's upToDate and
// complete). `files.id` is what a download button targets;
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
    query TitlesList($page: Int!, $pageSize: Int!, $search: String, $owned: Boolean, $filter: TitleFilter,
                     $orderBy: OrderBy, $favorite: Boolean, $console: String) {
        titles(owned: $owned, search: $search, filter: $filter, orderBy: $orderBy, favorite: $favorite,
               console: $console,
               page: $page, pageSize: $pageSize) {
            total
            items {
                titleId name intro description developer publisher releaseDate
                bannerUrl iconUrl size category numberOfPlayers rating languages
                requiredFirmware
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
    // Cards and Icons are one per game: the base game speaks for its updates and DLC
    // (the game page lists them). A game known only by its DLC or an update still
    // shows, through its base game - missing, in gray.
    const appType = ['BASE'];
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
        console: activeConsole || null,
        favorite: onlyFavorites || null,
    };
}

/** The List view takes the same filters as the cards: what you have (or, with
 *  "Missing", the catalogue's games you don't), up to date or not, complete or not. */
function listFilter() {
    const filter = {};
    if (activeUpdateFilter) filter.upToDate = activeUpdateFilter === 'Up to date';
    if (activeCompletionFilter) filter.complete = activeCompletionFilter === 'Complete';
    return Object.keys(filter).length ? filter : null;
}

function listQueryVariables() {
    const search = ($('#textFilter').val() || '').trim();
    return {
        page: currentPage,
        pageSize: itemsPerPage,
        search: search || null,
        owned: activeOwnershipFilter !== 'Missing',
        filter: listFilter(),
        orderBy: librarySort,
        favorite: onlyFavorites || null,
        console: activeConsole || null,
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

    // The Compact view is a grid of its own; Cards and List lay out in Bootstrap's row.
    $('#gameGrid').toggleClass('compact-grid', currentView === 'icon');
    if (!totalItems) {
        showLibraryState(anyFilterOrSearch() ? 'libraryEmpty' : 'libraryEmptyLibrary');
    } else {
        showLibraryState(null);
    }
    if (currentView === 'list') {
        renderListView(data.titles.items);
    } else if (currentView === 'icon') {
        renderCompactView(data.apps.items.map(cardModel));
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
            ownedTitles completeTitles upToDateTitles currentTitles missingDlc totalFiles totalSize
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

    $('#libraryCount').text(owned.toLocaleString()).prop('hidden', false);

    // "Up to date" means nothing missing: the latest update and every DLC.
    const pct = Math.round(100 * stats.currentTitles / owned);

    // (value, label, note, icon, tone, pill it applies, share for a small bar or null).
    // Pending updates count base games only; DLC count only under missing DLC. The same
    // for every role: no file figures here (they were admin only).
    const tiles = [
        [owned.toLocaleString(), I18N.tileGames, null, 'bi-controller', 'nav', 'all', null],
        [pending.toLocaleString(), I18N.tileUpdates, null, 'bi-arrow-up-circle', 'wait', 'outdated', null],
        [stats.missingDlc.toLocaleString(), I18N.tileDlcMissing, null, 'bi-puzzle', 'action', 'missingDlc', null],
        [stats.currentTitles.toLocaleString(), I18N.tileUpToDate.replace('{pct}', pct), null,
         'bi-check-circle', 'ok', 'upToDate', pct],
    ];

    const box = $('#libraryTiles').empty();
    tiles.forEach(([value, label, note, icon, tone, pill, share]) => {
        const tile = $('<button type="button">').addClass(`stat-tile stat-tile--${tone}`);
        tile.append($('<span class="stat-tile__icon">').append($('<i>').addClass(`bi ${icon}`)),
                    $('<div class="stat-tile__value">').text(value),
                    $('<div class="stat-tile__label">').text(label));
        if (note) tile.append($('<div class="stat-tile__note">').text(note));
        if (share !== null) {
            const bar = $('<div class="stat-tile__bar" role="img">').attr('aria-label', label);
            bar.append($('<span class="stat-tile__bar-fill">').css('width', share + '%'));
            tile.append(bar);
        }
        if (pill) {
            tile.attr('data-pill', pill).on('click', () => {
                applyPill(pill);
            });
        }
        box.append(tile);
    });
    box.prop('hidden', false);
}

// What each card/icon pill sets: the update, completion and ownership filter groups.
// The state pills cover owned games only, like the header tiles that apply them: an
// unowned DLC or game is never "up to date", so without it "Update pending" would
// list the whole catalogue of missing content.
const CARD_PILLS = {
    all: {update: '', completion: '', ownership: ''},
    outdated: {update: 'Outdated', completion: '', ownership: 'Owned'},
    missingDlc: {update: '', completion: 'Missing DLC', ownership: 'Owned'},
    // Up to date: nothing missing - the latest update and every DLC.
    upToDate: {update: 'Up to date', completion: 'Complete', ownership: 'Owned'},
};


// The console pills' counts (Both / Switch / Switch 2), with the view's own filters.
const CARD_COUNTS_QUERY = `
    query CardCounts($appType: [AppType!], $search: String, $owned: Boolean, $upToDate: Boolean,
                     $complete: Boolean, $favorite: Boolean) {
        consoleAll: apps(groupByAppId: true, appType: $appType, search: $search, owned: $owned, upToDate: $upToDate, complete: $complete, favorite: $favorite, page: 1, pageSize: 1) { total }
        consoleSwitch: apps(groupByAppId: true, appType: $appType, search: $search, owned: $owned, upToDate: $upToDate, complete: $complete, favorite: $favorite, console: "switch", page: 1, pageSize: 1) { total }
        consoleSwitch2: apps(groupByAppId: true, appType: $appType, search: $search, owned: $owned, upToDate: $upToDate, complete: $complete, favorite: $favorite, console: "switch2", page: 1, pageSize: 1) { total }
    }`;

const LIST_COUNTS_QUERY = `
    query ListCounts($search: String, $owned: Boolean, $filter: TitleFilter, $favorite: Boolean) {
        consoleAll: titles(owned: $owned, search: $search, filter: $filter, favorite: $favorite, page: 1, pageSize: 1) { total }
        consoleSwitch: titles(owned: $owned, search: $search, filter: $filter, favorite: $favorite, console: "switch", page: 1, pageSize: 1) { total }
        consoleSwitch2: titles(owned: $owned, search: $search, filter: $filter, favorite: $favorite, console: "switch2", page: 1, pageSize: 1) { total }
    }`;

let pillSeq = 0;      // like fetchSeq: an older count request never overwrites a newer one
let pillCounts = {};

async function loadPillCounts() {
    const seq = ++pillSeq;
    const list = currentView === 'list';
    let vars;
    if (list) {
        const l = listQueryVariables();
        vars = {search: l.search, owned: l.owned, filter: l.filter, favorite: l.favorite};
    } else {
        const g = queryVariables();
        vars = {appType: g.appType, search: g.search, owned: g.owned, upToDate: g.upToDate,
                complete: g.complete, favorite: g.favorite};
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
    const exact = Object.keys(CARD_PILLS).find(k =>
        CARD_PILLS[k].update === activeUpdateFilter && CARD_PILLS[k].completion === activeCompletionFilter
        && CARD_PILLS[k].ownership === activeOwnershipFilter);
    if (exact) return exact;
    // "All" is every game whatever its state: with no update or DLC filter on it stays
    // lit, also when the Filters menu narrows ownership (only mine, only missing).
    return !activeUpdateFilter && !activeCompletionFilter ? 'all' : null;
}

/** The cover's bottom-left: the console ("Switch" or "Switch 2") and the file's format. */
function coverFormat(game) {
    const box = $('<span class="library-cover-format">');
    box.append($('<span class="library-cover-console">').text(game.switch2 ? 'Switch 2' : 'Switch'));
    if (game.format) box.append($('<span>').text(game.format));
    return box;
}

function renderConsolePills() {
    const row = $('#libraryConsole').empty();
    [['', I18N.consoleAll, 'consoleAll', 'bi-collection'], ['switch', 'Switch', 'consoleSwitch', 'bi-nintendo-switch'],
     ['switch2', 'Switch 2', 'consoleSwitch2', 'bi-nintendo-switch']].forEach(([value, label, key, icon]) => {
        const pill = $('<button type="button" class="filter-pill filter-pill--console">')
            .toggleClass('active', activeConsole === value)
            .attr('aria-pressed', activeConsole === value ? 'true' : 'false')
            .append($('<i aria-hidden="true">').addClass(`bi ${icon}`), $('<span>').text(label));
        if (pillCounts[key] !== undefined) {
            pill.append($('<span class="filter-pill__count">').text(pillCounts[key].toLocaleString()));
        }
        pill.on('click', () => {
            activeConsole = value;
            if (value) storageSet('libraryConsole', value); else storageRemove('libraryConsole');
            resetToFirstPage();
        });
        row.append(pill);
    });
}

/** The pills row holds the console choice only: every other filter is in the toolbar's
 *  Filters menu (the tiles at the top still apply the common ones). */
function renderPills() {
    renderConsolePills();
}

/** The star on a card: marks or unmarks the game as one of the user's favourites. */
function favoriteButton(game) {
    if (!CAN_FAVORITE || !game.title_id) return null;
    const btn = $('<button type="button" class="library-fav">');
    const paint = () => {
        const on = favoriteIds.has(game.title_id);
        btn.toggleClass('is-on', on).attr({'aria-pressed': on ? 'true' : 'false',
                                           title: on ? I18N.favoriteRemove : I18N.favoriteAdd,
                                           'aria-label': on ? I18N.favoriteRemove : I18N.favoriteAdd})
            .html(`<i class="bi ${on ? 'bi-star-fill' : 'bi-star'}" aria-hidden="true"></i>`);
    };
    paint();
    btn.on('click', async event => {
        event.preventDefault();
        event.stopPropagation();
        const adding = !favoriteIds.has(game.title_id);
        btn.prop('disabled', true);
        try {
            const r = adding
                ? await fetch('/api/favorites', {method: 'POST', credentials: 'same-origin',
                                                 headers: {'Content-Type': 'application/json'},
                                                 body: JSON.stringify({title_id: game.title_id})})
                : await fetch(`/api/favorites/${game.title_id}`, {method: 'DELETE', credentials: 'same-origin'});
            if (!r.ok) throw new Error(`HTTP ${r.status}`);
            if (adding) favoriteIds.add(game.title_id); else favoriteIds.delete(game.title_id);
            paint();
            loadPillCounts();
            if (onlyFavorites && !adding) loadPage();
        } catch (e) {
            console.error(e);
        } finally {
            btn.prop('disabled', false);
        }
    });
    return btn;
}

async function loadFavorites() {
    if (!CAN_FAVORITE) return;
    try {
        const r = await fetch('/api/favorites', {credentials: 'same-origin'});
        if (r.ok) favoriteIds = new Set((await r.json()).title_ids || []);
    } catch (e) { /* no stars this time */ }
}

/** Set the filters a pill (or a header tile) stands for, through the same radios the
 *  Filters menu uses, so both always agree. */
function applyPill(name) {
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
    // Only coming back (Back/Forward): any other visit - a nav link, a reload - starts
    // at the top, and the saved position is dropped either way.
    const nav = (performance.getEntriesByType('navigation') || [])[0];
    if (nav && nav.type === 'back_forward') {
        scrollToRestore = parseInt(sessionStorage.getItem('libraryScroll'));
        // ...and the page of the grid it was on.
        const page = parseInt(sessionStorage.getItem('libraryPage'));
        if (page > 1) currentPage = page;
    }
    sessionStorage.removeItem('libraryScroll');
    sessionStorage.removeItem('libraryPage');
} catch (e) { /* storage unavailable: start at the top */ }
window.addEventListener('pagehide', () => {
    try {
        sessionStorage.setItem('libraryScroll', String(Math.round(window.scrollY)));
        sessionStorage.setItem('libraryPage', String(currentPage));
    } catch (e) { /* ignore */ }
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

/** The metadata object for one app, kept on each card model (cardModel - the Cards
 *  and Compact views). `id` is the title's own id for a BASE app (its own metadata is
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

/** The game page for an app: a game's own page, a DLC's game's page scrolled to that
 *  DLC, or - for a DLC whose game the library doesn't know - the DLC's own id. */
function gameUrl(app) {
    const title = app.title || {};
    if (app.appType === 'BASE') return `/game/${title.titleId || app.appId}`;
    return title.titleId ? `/game/${title.titleId}?dlc=${app.appId}` : `/game/${app.appId}`;
}

/** One card: a base game, speaking for its title (ownership comes from the title, since
 *  an update ships under its own app id). */
function cardModel(app) {
    const meta = app.titledb || {};
    const title = app.title || {};
    const ownership = title.ownership || {haveBase: false};
    const recognized = !!title.name;
    // Straight off `titledb.bannerUrl`/`iconUrl` - already resolved server-side
    // to /api/media/... or the titledb hotlink (see gql/resolvers.py's
    // _local_media_urls). Empty when titledb has nothing for this app at all: the
    // card then draws its own placeholder (no external image service).
    return {
        id: recognized ? title.titleId : title.titleId + ' ' + I18N.notFoundInTitledb,
        name: title.name || I18N.unrecognized,
        bannerUrl: meta.bannerUrl || '',
        iconUrl: meta.iconUrl || '',
        owned: ownership.haveBase,
        format: (app.downloadableFile || {}).format || null,
        switch2: /^04/i.test(title.titleId || app.appId || ''),
        update_pending: Boolean(ownership.haveBase) && ownership.upToDate === false,
        dlc_owned: ownership.dlcOwned || 0,
        dlc_total: ownership.dlcTotal || 0,
        title_id: recognized ? title.titleId : null,
        meta: metaFromApp(app, title.name || I18N.unrecognized),
        url: gameUrl(app),
    };
}

/** "DLC 1/2", or "No DLC" for a game without any: text only, no bar. */
function dlcCountText(owned, total) {
    if (!total) return I18N.noDlc;
    return I18N.dlcCount.replace('{owned}', owned).replace('{total}', total);
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

        const card = $('<div class="card game-surface game-card library-card"></div>')
            .toggleClass('is-missing', game.owned === false);
        if (game.title_id) card.attr('data-firmware-title', game.title_id);

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

        // The card is the game alone: its updates and DLC are on its page. The one
        // state shown is a base game the library doesn't hold (only its DLC or an
        // update), in gray like a missing game in Sagas.
        const badges = $('<div class="library-badges">');
        if (game.owned === false) {
            badges.append(statusBadge('wait', 'bi-dash-circle', I18N.baseMissing).attr('title', I18N.baseMissing));
        }
        coverWrap.append(badges);
        coverWrap.append(favoriteButton(game));
        // Along the cover's bottom: the file's format on the left, and on the right a
        // mark when the game has a newer update than the library's.
        coverWrap.append(coverFormat(game));
        if (game.update_pending) {
            coverWrap.append($('<span class="library-cover-update">')
                .attr({title: I18N.updateAvailable, role: 'img', 'aria-label': I18N.updateAvailable})
                .append('<i class="bi bi-arrow-up-circle-fill" aria-hidden="true"></i>'));
        }
        card.append(coverWrap);

        const body = $('<div class="library-card-body">');
        const name = game.name;
        body.append($('<h5 class="game-title library-card-title">').append(
            $('<a class="stretched-link library-card-link">').attr('href', game.url).text(name).attr('title', name)));
        const metaLine = cardMetaLine(game.meta);
        if (metaLine) body.append($('<p class="library-card-meta">').text(metaLine));

        const foot = $('<div class="library-card-foot">');
        foot.append($('<small class="library-card-id">').text(game.id),
                    $('<small class="library-card-dlc">').text(dlcCountText(game.dlc_owned, game.dlc_total)));
        body.append(foot);

        card.append(body);
        gameCol.append(card);
        gameGrid.append(gameCol);
    });
    markCardFirmware();
}

/** "Needs firmware X": a game the user's console (My account) is too old for. */
function firmwareBadge(needed) {
    // The words also as the tooltip: on a phone the cover shows just the icon.
    const label = I18N.needsNewerFirmware.replace('{needed}', needed);
    return statusBadge('firmware', 'bi-cpu', label).attr('title', label);
}

/** Cards come from a grouped apps query without the firmware: once they are drawn, one
 *  request asks for it for every game on screen. Only when the user set theirs. */
async function markCardFirmware() {
    if (!CONSOLE_FIRMWARE) return;
    const cards = [...document.querySelectorAll('#gameGrid [data-firmware-title]')];
    const ids = [...new Set(cards.map(c => c.dataset.firmwareTitle.toUpperCase()))]
        .filter(id => /^[0-9A-F]{16}$/.test(id)).slice(0, 200);
    if (!ids.length) return;
    let data;
    try {
        data = await gqlFetch('{ ' + ids.map((id, i) => `t${i}: title(titleId: "${id}") { titleId requiredFirmware }`).join(' ') + ' }');
    } catch (e) {
        return;   // no badge rather than a broken page
    }
    const needs = {};
    Object.values(data || {}).forEach(t => { if (t && t.requiredFirmware) needs[t.titleId.toUpperCase()] = t.requiredFirmware; });
    cards.forEach(card => {
        const needed = needs[card.dataset.firmwareTitle.toUpperCase()];
        if (firmwareTooOld(needed, CONSOLE_FIRMWARE)) $(card).find('.library-badges').append(firmwareBadge(needed));
    });
}

/** The Compact view: narrower cards, five or six a row - the game's square cover, its
 *  name, publisher and year, title id and DLC count, with the same marks as a card. */
function renderCompactView(games) {
    const gameGrid = $('#gameGrid');
    gameGrid.empty();
    games.forEach(game => {
        const card = $('<div class="card game-surface compact-card">').toggleClass('is-missing', game.owned === false);
        if (game.title_id) card.attr('data-firmware-title', game.title_id);

        const cover = $('<a class="compact-cover" tabindex="-1" aria-hidden="true">').attr('href', game.url);
        cover.append(game.iconUrl
            ? $('<img class="compact-cover__img" loading="lazy" alt="">').attr('src', game.iconUrl)
                .on('error', function () {
                    $(this).replaceWith('<span class="compact-cover__img library-cover--empty"><i class="bi bi-controller" aria-hidden="true"></i></span>');
                })
            : $('<span class="compact-cover__img library-cover--empty"><i class="bi bi-controller" aria-hidden="true"></i></span>'));
        const badges = $('<div class="library-badges">');
        if (game.owned === false) {
            badges.append(statusBadge('wait', 'bi-dash-circle', I18N.baseMissing).attr('title', I18N.baseMissing));
        }
        cover.append(badges);
        cover.append(coverFormat(game));
        if (game.update_pending) {
            cover.append($('<span class="library-cover-update">')
                .attr({title: I18N.updateAvailable, role: 'img', 'aria-label': I18N.updateAvailable})
                .append('<i class="bi bi-arrow-up-circle-fill" aria-hidden="true"></i>'));
        }

        const body = $('<div class="compact-card__body">');
        body.append($('<h6 class="game-title library-card-title">').append(
            $('<a class="stretched-link library-card-link">').attr('href', game.url).text(game.name).attr('title', game.name)));
        const metaLine = cardMetaLine(game.meta);
        if (metaLine) body.append($('<p class="library-card-meta">').text(metaLine));
        body.append($('<div class="library-card-foot">').append(
            $('<small class="library-card-id">').text(game.id),
            $('<small class="library-card-dlc">').text(dlcCountText(game.dlc_owned, game.dlc_total))));

        gameGrid.append(card.append(cover, body, favoriteButton(game)));
    });
    adjustCompactSizes();
    markCardFirmware();
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
        if (firmwareTooOld(t.requiredFirmware, CONSOLE_FIRMWARE)) titleLine.append(firmwareBadge(t.requiredFirmware));
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
/** Cards: at most four a row - two on a phone, three on a tablet, four from 1200px. */
function cardColumnClasses() {
    return 'col-6 col-md-4 col-xl-3';
}

/** How many cards a row of the current view holds at this width, the same rule the CSS
 *  follows (Bootstrap's breakpoints for Cards, the compact grid's auto-fill for Compact). */
function gridColumns() {
    if (currentView === 'list') return 1;
    const width = window.innerWidth;
    if (currentView === 'card') return width >= 1200 ? 4 : width >= 768 ? 3 : 2;
    const grid = document.getElementById('gameGrid');
    const rem = parseFloat(getComputedStyle(document.documentElement).fontSize) || 16;
    const gap = .85 * rem;
    const minCard = parseFloat(COMPACT_CARD_MIN) * rem;
    const space = (grid && grid.clientWidth) || width;
    return Math.max(2, Math.floor((space + gap) / (minCard + gap)));
}

/** The page sizes offered: 10, 20 ... 100, each rounded to whole rows of `columns` (the
 *  nearest multiple above, or below when that passes 100), so no row is left short. */
function pageSizeOptions(columns) {
    const sizes = [];
    for (let target = 10; target <= 100; target += 10) {
        let size = Math.ceil(target / columns) * columns;
        if (size > 100) size = Math.floor(100 / columns) * columns;
        if (size >= columns && !sizes.includes(size)) sizes.push(size);
    }
    return sizes;
}

/** The page size for the chosen target at this width: its option in pageSizeOptions. */
function fittedPageSize(target, columns) {
    const sizes = pageSizeOptions(columns);
    const index = Math.max(0, Math.min(sizes.length - 1, Math.round(target / 10) - 1));
    return sizes[Math.min(index, sizes.length - 1)];
}

function renderPageSizeOptions() {
    const columns = gridColumns();
    const box = $('#pageSizeOptions').empty();
    pageSizeOptions(columns).forEach((size, i) => {
        const target = (i + 1) * 10;
        box.append($('<button type="button" class="page-size-option">')
            .toggleClass('active', size === itemsPerPage)
            .attr('aria-pressed', size === itemsPerPage ? 'true' : 'false')
            .text(size)
            .on('click', () => {
                pageTarget = target;
                storageSet('pageTarget', String(target));
                itemsPerPage = size;
                renderPageSizeOptions();
                resetToFirstPage();
            }));
    });
}

/** Re-fit the page size to the columns now shown (a resize, another view): a different
 *  size reloads the page, so every row stays full. */
function refitPageSize(reload) {
    const size = fittedPageSize(pageTarget, gridColumns());
    const changed = size !== itemsPerPage;
    itemsPerPage = size;
    renderPageSizeOptions();
    if (changed && reload) loadPage();
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

/** The Compact view's card width for the size slider: the smallest a card may be, the
 *  grid fitting as many as that allows (about six a row at the middle size). */
function adjustCompactSizes() {
    // One size, not chosen: the Compact view's cards stay legible (Vista hides the slider).
    document.getElementById('gameGrid').style.setProperty('--compact-min', COMPACT_CARD_MIN);
}

const COMPACT_CARD_MIN = '12rem';

function saveFiltersToStorage() {
    storageSet('activeFilters', JSON.stringify({
        ownership: activeOwnershipFilter,
        update: activeUpdateFilter,
        completion: activeCompletionFilter,
    }));
}

function loadFiltersFromStorage() {
    let filters = null;
    try { filters = JSON.parse(storageGet('activeFilters') || 'null'); } catch (e) { /* unreadable: no filters */ }
    // What's stored is the whole state: the browser refills form fields by itself when
    // coming back to a page, and that must not bring back filters that were cleared.
    ['#ownershipAll', '#updateAll', '#completionAll'].forEach(id => $(id).prop('checked', true));
    $(onlyFavorites ? '#favoriteOnly' : '#favoriteAll').prop('checked', true);
    if (filters && typeof filters === 'object') {

        $('#ownershipOwned').prop('checked', filters.ownership === 'Owned');
        $('#ownershipMissing').prop('checked', filters.ownership === 'Missing');

        $('#updateUpToDate').prop('checked', filters.update === 'Up to date');
        $('#updateMissingUpdate').prop('checked', filters.update === 'Outdated');

        $('#completionComplete').prop('checked', filters.completion === 'Complete');
        $('#completionMissingDlc').prop('checked', filters.completion === 'Missing DLC');

    }
    updateFilter();

    const savedSearch = storageGet('searchTerm');
    $('#textFilter').val(savedSearch || '');
    // ?q= from the global search (Ctrl+K) wins over the remembered search.
    const urlSearch = new URLSearchParams(location.search).get('q');
    if (urlSearch) {
        $('#textFilter').val(urlSearch);
    }
}

/** Read the filter controls into the active* variables the query is built from. */
function updateFilter() {
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
    onlyFavorites = CAN_FAVORITE && $('#favoriteOnly').is(':checked');
    if (onlyFavorites) storageSet('libraryFavorites', '1'); else storageRemove('libraryFavorites');
    if ($('#completionComplete').is(":checked")) {
        activeCompletionFilter = 'Complete';
    } else if ($('#completionMissingDlc').is(":checked")) {
        activeCompletionFilter = 'Missing DLC';
    } else {
        activeCompletionFilter = '';
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
    return !!(search || activeOwnershipFilter || activeUpdateFilter || activeCompletionFilter);
}

/** "Clear filters": every filter group back to All, the search emptied - both
 *  remembered that way - and back to page 1. */
function clearAllFilters() {
    ['#ownershipAll', '#updateAll', '#completionAll'].forEach(id => $(id).prop('checked', true));
    onlyFavorites = false;
    storageRemove('libraryFavorites');
    $('#favoriteAll').prop('checked', true);
    $('#textFilter').val('');
    storageRemove('searchTerm');
    updateFilter();
    saveFiltersToStorage();
    updateFiltersDot();
    resetToFirstPage();
}

// Back from a game page the Library is as it was left: the same filters and search
// (remembered in storage), the same page and scroll (kept per tab on pagehide, see
// scrollToRestore). From the browser's back-forward cache it is simply shown again.

function onFilterChange() {
    updateFilter();
    saveFiltersToStorage();
    updateFiltersDot();
    resetToFirstPage();
}

/** The Filters button's dot: some filter that applies to the current view is set. */
function updateFiltersDot() {
    const active = !!(activeOwnershipFilter || activeUpdateFilter || activeCompletionFilter || onlyFavorites);
    $('#filtersActiveDot').prop('hidden', !active);
}

/** Every view takes the same filters; the dot says whether one is set. */
function applyViewToToolbar() {
    updateFiltersDot();
}

$(document).ready(function () {
    // Only sensible values are taken back: a bad page size or an unknown view would
    // otherwise reach the server as a failing query.
    const savedTarget = parseInt(storageGet('pageTarget'));
    if (savedTarget >= 10 && savedTarget <= 100 && savedTarget % 10 === 0) pageTarget = savedTarget;

    const savedCurrentView = storageGet('currentView');
    if (['card', 'icon', 'list'].includes(savedCurrentView)) {
        currentView = savedCurrentView;
        $('.view-toggle-btn').removeClass("active");
        $(`.view-toggle-btn[data-view="${currentView}"]`).addClass("active");
        applyViewToToolbar();
    }

    refitPageSize(false);
    if (!CAN_FAVORITE) onlyFavorites = false;

    loadFiltersFromStorage();
    updateFiltersDot();
    loadSortFromStorage();
    $('#sortField').on('change', function () { setSort(this.value, librarySort.direction); });
    $('.sort-direction-btn').on('click', function () { setSort(librarySort.field, this.dataset.direction); });
    // The stars first: the cards are drawn with them.
    loadFavorites().finally(loadPage);
    loadLibraryStats();
    loadPillCounts();
    $('#clearFiltersBtn').on('click', clearAllFilters);
    $('#libraryRetryBtn').on('click', () => { loadPage(); loadLibraryStats(); loadPillCounts(); });

    // A narrower or wider window can hold another number of cards a row: the page size
    // follows, so the last row is never left with one card.
    let resizeTimer = null;
    window.addEventListener('resize', () => {
        clearTimeout(resizeTimer);
        resizeTimer = setTimeout(() => refitPageSize(true), 250);
    });
    $('#filtersClearBtn').on('click', clearAllFilters);

    // Event listener for view buttons
    $('.view-toggle-btn').click(function () {
        $('.view-toggle-btn').removeClass("active");
        $(this).addClass("active");
        currentView = $(this).data('view');
        storageSet('currentView', currentView);
        applyViewToToolbar();
        refitPageSize(false);
        // The views page different things (every card vs one icon per game), so the
        // page number from the previous view means nothing here.
        resetToFirstPage();
    });

    $('.ownership-toggle, .update-toggle, .completion-toggle, .favorite-toggle').change(onFilterChange);

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
