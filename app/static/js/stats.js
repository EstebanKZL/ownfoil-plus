// The Statistics page (templates/stats.html). The page renders the I18N, DL and
// I18N_FILES_LABEL strings in its one inline script, then loads this file.

const STATS_QUERY = `
    query Stats {
        stats {
            totalFiles totalSize identifiedFiles unidentifiedFiles
            totalTitles ownedTitles completeTitles upToDateTitles
            totalApps ownedApps
            filesByExtension { key count size }
            filesByLibrary { key count size }
            filesByVerificationStatus { status count size }
            appsByType { key count owned }
        }
    }`;

function count(n) {
    return Number(n || 0).toLocaleString();
}

// (label, value, note under it, icon, tone, link or null) - the four figures that
// matter; the rest of the numbers live in their sections below.
function tiles(s) {
    return [
        [I18N.tileOwnedTitles, count(s.ownedTitles),
         I18N.tileGamesNote.replace('{complete}', count(s.completeTitles)).replace('{uptodate}', count(s.upToDateTitles)),
         'bi-controller', 'ok', '/'],
        [I18N_FILES_LABEL, count(s.totalFiles), I18N.tileFilesNote.replace('{n}', count(s.identifiedFiles)),
         'bi-file-earmark', 'nav', '/admin/files'],
        // Unidentified before the size (asked for): what needs a look outranks a figure.
        [I18N.tileUnidentified, count(s.unidentifiedFiles), I18N.tileUnidentifiedNote,
         'bi-question-circle', 'wait', '/admin/files#unidentified'],
        [I18N.tileTotalSize, formatBytes(s.totalSize), I18N.tileTotalSizeNote, 'bi-hdd-stack', 'action', null],
    ];
}

function renderTiles(s) {
    const container = document.getElementById('statTiles');
    container.innerHTML = '';
    tiles(s).forEach(([label, value, note, icon, tone, href]) => {
        const tile = document.createElement(href ? 'a' : 'div');
        tile.className = `stat-tile stat-tile--${tone}`;
        if (href) tile.href = href;
        const iconBox = document.createElement('span');
        iconBox.className = 'stat-tile__icon';
        iconBox.innerHTML = `<i class="bi ${icon}" aria-hidden="true"></i>`;
        tile.append(iconBox, textEl('div', 'stat-tile__value', value), textEl('div', 'stat-tile__label', label),
                    textEl('div', 'stat-tile__note', note));
        container.appendChild(tile);
    });
}

/** An element with a class and plain text - paths and names are never HTML. */
function textEl(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = text;
    return node;
}

/** The "nothing here" line every section shows when its data is empty. */
function emptyRow(list) {
    list.innerHTML = '';
    list.appendChild(textEl('li', 'chart-empty', I18N.nothingToReport));
}

/** One row: label on the left, figures on the right, an optional bar under them. */
function chartRow({label, sub, figures, pct, tone, swatch, onClick}) {
    const li = document.createElement('li');
    li.className = 'chart-row';
    const head = document.createElement('div');
    head.className = 'chart-row__head';
    const name = document.createElement('div');
    name.className = 'chart-row__label';
    if (swatch) {
        const dot = document.createElement('span');
        dot.className = 'chart-swatch';
        dot.style.background = swatch;
        name.appendChild(dot);
    }
    name.appendChild(textEl('span', 'chart-row__text', label));
    if (sub) name.appendChild(textEl('span', 'chart-row__sub', sub));
    head.append(name, textEl('div', 'chart-row__figures', figures));
    li.appendChild(head);
    if (pct !== undefined) li.appendChild(percentBar(pct, tone));
    if (onClick) {
        li.classList.add('is-clickable');
        li.tabIndex = 0;
        li.setAttribute('role', 'button');
        li.addEventListener('click', onClick);
        li.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onClick(); } });
    }
    return li;
}

/** VERIFICATION_FAILED -> its translated label, falling back to a humanized
 *  version of the raw key for any status I18N.statusLabels doesn't know about
 *  (future-proofing against a new enum value landing before the translation does). */
function humanize(key) {
    if (I18N.statusLabels[key]) return I18N.statusLabels[key];
    const words = key.replace(/_/g, ' ').toLowerCase();
    return words.charAt(0).toUpperCase() + words.slice(1);
}

/** Space by format: a donut of sizes, with the legend carrying count, size and share. */
function renderFormats(data) {
    const buckets = (data.filesByExtension || []).slice().sort((a, b) => (b.size || 0) - (a.size || 0));
    const total = buckets.reduce((sum, b) => sum + (b.size || 0), 0);
    document.getElementById('formatDonut').style.background = donutGradient(buckets.map(b => b.size));
    document.getElementById('formatDonutTotal').textContent = formatBytes(total);
    const list = document.getElementById('byExtension');
    if (!buckets.length) return emptyRow(list);
    list.innerHTML = '';
    buckets.forEach((b, i) => {
        list.appendChild(chartRow({
            label: (b.key || '(none)').toUpperCase(), sub: `(${count(b.count)})`,
            figures: `${formatBytes(b.size)} · ${percent(b.size, total)}%`,
            swatch: CHART_COLORS[Math.min(i, CHART_COLORS.length - 1)],
        }));
    });
}

/** Space by library: one bar each; a click opens the library's detail, as before. */
function renderLibraries(data) {
    const buckets = data.filesByLibrary || [];
    const total = buckets.reduce((sum, b) => sum + (b.size || 0), 0);
    const list = document.getElementById('byLibrary');
    if (!buckets.length) return emptyRow(list);
    list.innerHTML = '';
    buckets.forEach(b => list.appendChild(chartRow({
        label: b.key, sub: `(${count(b.count)})`,
        figures: `${formatBytes(b.size)} · ${percent(b.size, total)}%`,
        pct: percent(b.size, total), onClick: () => openLibraryDetail(b.key),
    })));
}

// One meaning per color: fine, waits for a look, broken, not checked yet.
const VERIFICATION_TONES = {
    VALID: 'ok', SIGNATURE_OK: 'ok', REPACK: 'wait', MODIFIED: 'wait',
    CORRUPT: 'danger', SIGNATURE_FAILED: 'danger', UNVERIFIED: '',
};

/** Verification: a ring with the share of files verified fine (VALID or
 *  SIGNATURE_OK), and a row per status that opens its files, as before. */
function renderVerification(data) {
    const buckets = data.filesByVerificationStatus || [];
    const total = buckets.reduce((sum, b) => sum + (b.count || 0), 0);
    const fine = buckets.filter(b => b.status === 'VALID' || b.status === 'SIGNATURE_OK')
        .reduce((sum, b) => sum + (b.count || 0), 0);
    const pct = percent(fine, total);
    document.getElementById('verificationRing').style.background = ringGradient(pct, 'var(--op-ok)');
    document.getElementById('verificationRingPct').textContent = total ? `${Math.round(pct)}%` : '–';
    const list = document.getElementById('byVerification');
    if (!buckets.length) return emptyRow(list);
    list.innerHTML = '';
    buckets.forEach(b => {
        const tone = VERIFICATION_TONES[b.status];
        list.appendChild(chartRow({
            label: humanize(b.status), sub: `(${count(b.count)})`, figures: formatBytes(b.size),
            pct: percent(b.count, total), tone: tone || undefined,
            onClick: () => openVerificationFiles(b.status, humanize(b.status)),
        }));
        list.lastChild.dataset.status = b.status;
    });
}

/** Content by type: owned out of tracked; a click lists what is missing, when
 *  something is. App types stay as the schema spells them (DLC, not "Dlc"). Each type
 *  wears its fixed color - base coral, update amber, DLC cyan - so the row is identified
 *  the same as everywhere else; the share itself says how complete it is. */
const TYPE_TONES = {BASE: 'base', UPDATE: 'wait', DLC: 'dlc'};

function renderTypes(data) {
    const buckets = data.appsByType || [];
    const list = document.getElementById('byAppType');
    if (!buckets.length) return emptyRow(list);
    list.innerHTML = '';
    buckets.forEach(b => list.appendChild(chartRow({
        label: b.key, figures: `${count(b.owned)} / ${count(b.count)}`,
        pct: percent(b.owned, b.count), tone: TYPE_TONES[b.key],
        swatch: TYPE_TONES[b.key] ? `var(--op-${TYPE_TONES[b.key]})` : undefined,
        onClick: b.count > b.owned ? () => openMissingAppType(b.key) : null,
    })));
}

// The ten largest files (admin page, admin query): each one leads to its game.
const LARGEST_FILES_QUERY = `
    query LargestFiles {
        files(orderBy: {field: SIZE, direction: DESC}, page: 1, pageSize: 10) {
            items { id filename size apps { appType titleId title { name } } }
        }
    }`;

async function loadLargestFiles() {
    try {
        const data = await gqlFetchStats(LARGEST_FILES_QUERY, {});
        renderLargestFiles(data.files.items || []);
    } catch (e) {
        console.error(e);
        emptyRow(document.getElementById('largestFiles'));
    }
}

function renderLargestFiles(files) {
    const list = document.getElementById('largestFiles');
    if (!files.length) return emptyRow(list);
    list.innerHTML = '';
    files.forEach(f => {
        const app = (f.apps || [])[0] || {};
        const name = (app.title && app.title.name) || '';
        const li = document.createElement('li');
        li.className = 'chart-row';
        const head = document.createElement('div');
        head.className = 'chart-row__head';
        const label = document.createElement('div');
        label.className = 'chart-row__label';
        // An identified file links to its game; an unidentified one is just its name.
        if (app.titleId) {
            const a = textEl('a', 'chart-row__text', name || f.filename);
            a.href = `/game/${app.titleId}`;
            label.appendChild(a);
        } else {
            label.appendChild(textEl('span', 'chart-row__text', f.filename));
        }
        if (name) label.appendChild(textEl('span', 'chart-row__sub', f.filename));
        head.append(label, textEl('div', 'chart-row__figures', formatBytes(f.size)));
        li.appendChild(head);
        list.appendChild(li);
    });
}

async function loadStats() {
    const button = $('#refreshStats').prop('disabled', true);
    let data;
    try {
        // GET, like the library grid: the endpoint ETags its responses, so a refresh
        // that changes nothing costs a 304.
        const params = new URLSearchParams({query: STATS_QUERY});
        const r = await fetch('/api/graphql?' + params.toString(), {
            headers: {'Accept': 'application/json'},
            credentials: 'same-origin',
        });
        if (!r.ok) throw new Error(`GraphQL HTTP ${r.status}`);
        const body = await r.json();
        if (body.errors && body.errors.length) {
            throw new Error('GraphQL errors: ' + JSON.stringify(body.errors));
        }
        data = body.data.stats;
    } catch (e) {
        console.error(e);
        return;
    } finally {
        button.prop('disabled', false);
    }

    renderTiles(data);
    renderFormats(data);
    renderLibraries(data);
    renderVerification(data);
    renderTypes(data);
}

loadStats();
loadLargestFiles();

// --- Verification status drill-down: which titles are behind each row above ---
const FILES_BY_STATUS_QUERY = `
    query FilesByStatus($status: [VerificationStatus!], $page: Int!, $pageSize: Int!, $search: String) {
        files(filter: {verificationStatus: $status, filename: {contains: $search}},
              page: $page, pageSize: $pageSize,
              orderBy: {field: ADDED_AT, direction: DESC}) {
            total
            items {
                filename
                size
                apps { appType title { titleId name iconUrl } }
            }
        }
    }`;

let verificationModal;
let verificationStatus = null;
let verificationPage = 1;
let verificationTotal = 0;
let verificationSearch = '';
let verificationSearchDebounce;
const VERIFICATION_PAGE_SIZE = 50;

/** The title behind a file: its base game's name, or the filename itself when
 *  nothing identified it (an unverified/unidentified file has no apps). */
function titleForFile(file) {
    const withTitle = (file.apps || []).find(a => a.title && a.title.name);
    return withTitle ? withTitle.title.name : file.filename;
}

/** One file as a list row: the game's icon and name, the filename, the size. */
function fileRow(file) {
    const title = ((file.apps || []).find(a => a.title && a.title.name) || {}).title || {};
    return titleListRow({main: titleForFile(file), sub: file.filename, side: formatBytes(file.size),
                         titleId: title.titleId, iconUrl: title.iconUrl});
}

async function loadVerificationFilesPage() {
    const list = document.getElementById('verificationFilesList');
    const empty = document.getElementById('verificationFilesEmpty');
    const loading = document.getElementById('verificationFilesLoading');
    const prevBtn = document.getElementById('verificationFilesPrev');
    const nextBtn = document.getElementById('verificationFilesNext');

    list.innerHTML = '';
    empty.classList.add('d-none');
    loading.classList.remove('d-none');
    prevBtn.disabled = true;
    nextBtn.disabled = true;

    let data;
    try {
        data = await gqlFetchStats(FILES_BY_STATUS_QUERY, {
            status: verificationStatus ? [verificationStatus] : null,
            page: verificationPage, pageSize: VERIFICATION_PAGE_SIZE,
            search: verificationSearch || null,
        });
    } catch (e) {
        console.error(e);
        loading.classList.add('d-none');
        empty.textContent = I18N.couldNotLoadFiles;
        empty.classList.remove('d-none');
        return;
    }

    loading.classList.add('d-none');
    verificationTotal = data.files.total;
    const items = data.files.items || [];

    if (!items.length) {
        empty.classList.remove('d-none');
    } else {
        items.forEach(f => list.appendChild(fileRow(f)));
    }

    const totalPages = Math.max(1, Math.ceil(verificationTotal / VERIFICATION_PAGE_SIZE));
    document.getElementById('verificationFilesCount').textContent = I18N.filesPageCount
        .replace('{count}', count(verificationTotal))
        .replace('{s}', pluralS(verificationTotal))
        .replace('{page}', verificationPage)
        .replace('{totalPages}', totalPages);
    prevBtn.disabled = verificationPage <= 1;
    nextBtn.disabled = verificationPage >= totalPages;
}

async function gqlFetchStats(query, variables) {
    const params = new URLSearchParams({query, variables: JSON.stringify(variables)});
    const r = await fetch('/api/graphql?' + params.toString(), {
        headers: {'Accept': 'application/json'},
        credentials: 'same-origin',
    });
    if (!r.ok) throw new Error(`GraphQL HTTP ${r.status}`);
    const body = await r.json();
    if (body.errors && body.errors.length) {
        throw new Error('GraphQL errors: ' + JSON.stringify(body.errors));
    }
    return body.data;
}

function openVerificationFiles(status, label) {
    verificationStatus = status;
    verificationPage = 1;
    verificationSearch = '';
    document.getElementById('verificationFilesSearch').value = '';
    document.getElementById('verificationFilesModalLabel').textContent = `${label} files`;
    if (!verificationModal) {
        verificationModal = new bootstrap.Modal(document.getElementById('verificationFilesModal'));
    }
    verificationModal.show();
    loadVerificationFilesPage();
}

document.getElementById('verificationFilesSearch').addEventListener('input', function () {
    verificationSearch = this.value;
    clearTimeout(verificationSearchDebounce);
    verificationSearchDebounce = setTimeout(() => {
        verificationPage = 1;
        loadVerificationFilesPage();
    }, 250);
});

document.getElementById('verificationFilesPrev').addEventListener('click', () => {
    if (verificationPage > 1) { verificationPage--; loadVerificationFilesPage(); }
});
document.getElementById('verificationFilesNext').addEventListener('click', () => {
    const totalPages = Math.max(1, Math.ceil(verificationTotal / VERIFICATION_PAGE_SIZE));
    if (verificationPage < totalPages) { verificationPage++; loadVerificationFilesPage(); }
});

// --- App types table: click a row to see which titles have that type tracked
// ("registered") without actually owning it - the gap the table's own two
// columns can't explain by themselves. ------------------------------------

const MISSING_APP_TYPE_QUERY = `
    query MissingAppType($type: AppType!, $page: Int!, $pageSize: Int!, $search: String) {
        titles(owned: true, missingAppType: $type, search: $search, page: $page, pageSize: $pageSize,
               orderBy: {field: NAME}) {
            total
            items { titleId name iconUrl }
        }
    }`;

let missingAppTypeModal;
let missingAppTypeValue = null;
let missingAppTypePage = 1;
let missingAppTypeTotal = 0;
let missingAppTypeSearch = '';
let missingAppTypeSearchDebounce;
const MISSING_APP_TYPE_PAGE_SIZE = 50;

async function loadMissingAppTypePage() {
    const list = document.getElementById('missingAppTypeList');
    const empty = document.getElementById('missingAppTypeEmpty');
    const loading = document.getElementById('missingAppTypeLoading');
    const prevBtn = document.getElementById('missingAppTypePrev');
    const nextBtn = document.getElementById('missingAppTypeNext');

    list.innerHTML = '';
    empty.classList.add('d-none');
    loading.classList.remove('d-none');
    prevBtn.disabled = true;
    nextBtn.disabled = true;

    let data;
    try {
        data = await gqlFetchStats(MISSING_APP_TYPE_QUERY, {
            type: missingAppTypeValue, page: missingAppTypePage, pageSize: MISSING_APP_TYPE_PAGE_SIZE,
            search: missingAppTypeSearch || null,
        });
    } catch (e) {
        console.error(e);
        loading.classList.add('d-none');
        empty.textContent = I18N.couldNotLoadFiles;
        empty.classList.remove('d-none');
        return;
    }

    loading.classList.add('d-none');
    missingAppTypeTotal = data.titles.total;
    const items = data.titles.items || [];

    if (!items.length) {
        empty.classList.remove('d-none');
    } else {
        items.forEach(t => list.appendChild(
            titleListRow({main: t.name, titleId: t.titleId, iconUrl: t.iconUrl})));
    }

    const totalPages = Math.max(1, Math.ceil(missingAppTypeTotal / MISSING_APP_TYPE_PAGE_SIZE));
    document.getElementById('missingAppTypeCount').textContent = I18N.filesPageCount
        .replace('{count}', count(missingAppTypeTotal))
        .replace('{s}', pluralS(missingAppTypeTotal))
        .replace('{page}', missingAppTypePage)
        .replace('{totalPages}', totalPages);
    prevBtn.disabled = missingAppTypePage <= 1;
    nextBtn.disabled = missingAppTypePage >= totalPages;
}

function openMissingAppType(appType) {
    missingAppTypeValue = appType;
    missingAppTypePage = 1;
    missingAppTypeSearch = '';
    document.getElementById('missingAppTypeSearch').value = '';
    document.getElementById('missingAppTypeModalLabel').textContent = `${appType} - ${I18N.missingTitles}`;
    if (!missingAppTypeModal) {
        missingAppTypeModal = new bootstrap.Modal(document.getElementById('missingAppTypeModal'));
    }
    missingAppTypeModal.show();
    loadMissingAppTypePage();
}

document.getElementById('missingAppTypeSearch').addEventListener('input', function () {
    missingAppTypeSearch = this.value;
    clearTimeout(missingAppTypeSearchDebounce);
    missingAppTypeSearchDebounce = setTimeout(() => {
        missingAppTypePage = 1;
        loadMissingAppTypePage();
    }, 250);
});

document.getElementById('missingAppTypePrev').addEventListener('click', () => {
    if (missingAppTypePage > 1) { missingAppTypePage--; loadMissingAppTypePage(); }
});
document.getElementById('missingAppTypeNext').addEventListener('click', () => {
    const totalPages = Math.max(1, Math.ceil(missingAppTypeTotal / MISSING_APP_TYPE_PAGE_SIZE));
    if (missingAppTypePage < totalPages) { missingAppTypePage++; loadMissingAppTypePage(); }
});

// --- Library detail: clicking a Libraries row shows every title with a file
// physically under it, List-view-style but without a download button, plus (if
// enabled in Settings) a per-item clean-record action. -----------------------

const LIBRARY_DETAIL_QUERY = `
    query LibraryDetail($path: String!, $page: Int!, $pageSize: Int!, $search: String) {
        titles(owned: true, libraryPath: $path, search: $search, page: $page, pageSize: $pageSize,
               orderBy: {field: NAME}) {
            total
            items {
                titleId
                name
                iconUrl
                apps(owned: true) {
                    id appId appType appVersion releaseDate
                    downloadableFile { size verificationStatus }
                    titledb { name }
                }
            }
        }
    }`;

const CLEAN_APP_MUTATION = `
    mutation CleanApp($id: ID!) { cleanAppRecord(appRowId: $id) }`;
const CLEAN_TITLE_MUTATION = `
    mutation CleanTitle($id: String!) { cleanTitleRecord(titleId: $id) }`;
const DELETE_APP_MUTATION = `
    mutation DeleteApp($id: ID!) { deleteAppRecord(appRowId: $id) }`;
const DELETE_TITLE_MUTATION = `
    mutation DeleteTitle($id: String!) { deleteTitleRecord(titleId: $id) }`;

async function gqlMutateStats(query, variables) {
    const r = await fetch('/api/graphql', {
        method: 'POST',
        headers: {'Content-Type': 'application/json', 'Accept': 'application/json'},
        credentials: 'same-origin',
        body: JSON.stringify({query, variables}),
    });
    if (!r.ok) throw new Error(`GraphQL HTTP ${r.status}`);
    const body = await r.json();
    if (body.errors && body.errors.length) {
        throw new Error('GraphQL errors: ' + JSON.stringify(body.errors));
    }
    return body.data;
}

let libraryDetailModal;
let libraryDetailPath = null;
let libraryDetailPage = 1;
let libraryDetailTotal = 0;
let libraryDetailSearch = '';
let libraryDetailSearchDebounce;
const LIBRARY_DETAIL_PAGE_SIZE = 20;

function libraryDetailAppLabel(app) {
    if (app.appType === 'BASE') return I18N.baseGame;
    if (app.appType === 'UPDATE') return `v${app.appVersion}`;
    return (app.titledb && app.titledb.name) || I18N.unrecognized;
}

/** The base game gets a two-step confirm (native confirm() only ever gives a
 *  binary choice, so a genuine three-way "clean base only / clean everything /
 *  do nothing" needs two of them in sequence): first, plain confirmation that
 *  cleaning is wanted at all (Cancel here = do nothing); then, whether to also
 *  sweep every update/DLC under the same title (Cancel here = base only). An
 *  update or DLC row is a single confirm, since there's nothing under it to
 *  cascade into. */
/** Shared by handleCleanClick and handleDeleteClick: the base game gets a
 *  two-step confirm (native confirm() only ever gives a binary choice, so a
 *  genuine three-way "just base / base+everything / do nothing" needs two of
 *  them in sequence) - first, plain confirmation the action is wanted at all
 *  (Cancel here = do nothing); then, whether to also sweep every update/DLC
 *  under the same title (Cancel here = base only). An update or DLC row is a
 *  single confirm, since there's nothing under it to cascade into. */
async function handleRecordAction(app, title, opts) {
    try {
        if (app.appType === 'BASE') {
            if (!window.confirm(opts.baseStep1.replace('{name}', title.name))) return;
            const cascade = window.confirm(opts.baseStep2.replace('{name}', title.name));
            if (cascade) {
                await gqlMutateStats(opts.titleMutation, {id: title.titleId});
            } else {
                await gqlMutateStats(opts.itemMutation, {id: app.id});
            }
        } else {
            const label = libraryDetailAppLabel(app);
            if (!window.confirm(opts.itemConfirm.replace('{name}', `${title.name} - ${label}`))) return;
            await gqlMutateStats(opts.itemMutation, {id: app.id});
        }
        loadLibraryDetailPage();
    } catch (e) {
        console.error(e);
        alert(opts.failed);
    }
}

/** Database-only: forgets the tracked row(s), never touches the real file. */
function handleCleanClick(app, title) {
    return handleRecordAction(app, title, {
        itemMutation: CLEAN_APP_MUTATION, titleMutation: CLEAN_TITLE_MUTATION,
        itemConfirm: I18N.cleanRecordItemConfirm, baseStep1: I18N.cleanRecordBaseStep1,
        baseStep2: I18N.cleanRecordBaseStep2, failed: I18N.cleanRecordFailed,
    });
}

/** Real, irreversible: deletes the file from disk *and* forgets the tracked
 *  row together - never asked separately, the database half always goes with
 *  the file. */
function handleDeleteClick(app, title) {
    return handleRecordAction(app, title, {
        itemMutation: DELETE_APP_MUTATION, titleMutation: DELETE_TITLE_MUTATION,
        itemConfirm: I18N.deleteRecordItemConfirm, baseStep1: I18N.deleteRecordBaseStep1,
        baseStep2: I18N.deleteRecordBaseStep2, failed: I18N.deleteRecordFailed,
    });
}

function buildLibraryDetailAppRow(app, title, label) {
    const li = document.createElement('li');
    li.className = 'list-group-item bg-transparent d-flex justify-content-between align-items-center flex-wrap gap-2';
    const left = document.createElement('span');
    left.textContent = label != null ? label : libraryDetailAppLabel(app);
    li.appendChild(left);

    const right = document.createElement('span');
    right.className = 'd-flex align-items-center gap-2 flex-shrink-0';
    const df = app.downloadableFile;
    if (df && df.size != null) {
        const sizeBadge = document.createElement('span');
        sizeBadge.className = 'badge text-bg-secondary';
        sizeBadge.textContent = formatBytes(df.size);
        right.appendChild(sizeBadge);
    }
    if (df && df.verificationStatus) {
        const statusBadge = document.createElement('span');
        statusBadge.className = 'badge text-bg-dark';
        statusBadge.textContent = I18N.statusLabels[df.verificationStatus] || df.verificationStatus;
        right.appendChild(statusBadge);
    }
    // Always available to the admin viewing this page - no settings toggle
    // gates these anymore. Two distinct actions, two distinct icons: cleaning
    // the tracked record (database-only, safe to undo with a rescan) is not
    // the same thing as deleting the real file, and they must never be
    // confusable at a glance.
    const cleanBtn = document.createElement('button');
    cleanBtn.type = 'button';
    cleanBtn.className = 'icon-btn stats-record-action';
    cleanBtn.title = I18N.cleanRecordTooltip;
    cleanBtn.innerHTML = '<i class="bi bi-database-x"></i>';
    cleanBtn.addEventListener('click', () => handleCleanClick(app, title));
    right.appendChild(cleanBtn);

    const deleteBtn = document.createElement('button');
    deleteBtn.type = 'button';
    deleteBtn.className = 'icon-btn text-danger stats-record-action';
    deleteBtn.title = I18N.deleteRecordTooltip;
    deleteBtn.innerHTML = '<i class="bi bi-trash"></i>';
    deleteBtn.addEventListener('click', () => handleDeleteClick(app, title));
    right.appendChild(deleteBtn);

    li.appendChild(right);
    return li;
}

let libraryDetailSectionSeq = 0;

/** A collapsible "Updates" or "DLC" group within the modal - same look as the
 *  List view's own collapsible sections (count badge + chevron that flips on
 *  expand), so a title with a dozen updates doesn't turn the modal into an
 *  unreadable wall of rows. */
function buildLibraryDetailSection(sectionTitle, rows) {
    const id = `libraryDetailSection${libraryDetailSectionSeq++}`;
    const li = document.createElement('li');
    li.className = 'list-group-item bg-transparent';

    const trigger = document.createElement('p');
    trigger.className = 'my-1 d-flex justify-content-between align-items-center list-section-trigger';
    trigger.setAttribute('role', 'button');
    trigger.setAttribute('aria-expanded', 'false');
    trigger.setAttribute('data-bs-toggle', 'collapse');
    trigger.setAttribute('data-bs-target', `#${id}`);
    trigger.setAttribute('aria-controls', id);
    const strong = document.createElement('strong');
    strong.textContent = sectionTitle;
    trigger.appendChild(strong);
    const triggerRight = document.createElement('span');
    triggerRight.className = 'd-flex align-items-center gap-2';
    const countBadge = document.createElement('span');
    countBadge.className = 'badge text-bg-secondary';
    countBadge.textContent = rows.length;
    triggerRight.appendChild(countBadge);
    triggerRight.innerHTML += '<i class="bi bi-chevron-down list-chevron"></i>';
    trigger.appendChild(triggerRight);
    li.appendChild(trigger);

    const collapseDiv = document.createElement('div');
    collapseDiv.className = 'collapse';
    collapseDiv.id = id;
    const innerList = document.createElement('ul');
    innerList.className = 'list-group list-group-flush mt-1';
    rows.forEach(r => innerList.appendChild(r));
    collapseDiv.appendChild(innerList);
    li.appendChild(collapseDiv);
    return li;
}

function buildLibraryDetailTitleCard(title) {
    const card = document.createElement('div');
    card.className = 'card game-surface mb-3';
    const body = document.createElement('div');
    body.className = 'card-body';
    // The game's icon before its name, like every other list of games.
    const h = document.createElement('h6');
    h.className = 'library-detail-title';
    const icon = document.createElement('span');
    icon.className = 'dash-list__icon';
    if (title.iconUrl) {
        const img = document.createElement('img');
        img.src = title.iconUrl;
        img.alt = '';
        img.loading = 'lazy';
        icon.appendChild(img);
    } else {
        icon.innerHTML = '<i class="bi bi-controller"></i>';
    }
    h.append(icon, document.createTextNode(title.name));
    body.appendChild(h);

    const apps = title.apps || [];
    const base = apps.filter(a => a.appType === 'BASE');
    const updates = apps.filter(a => a.appType === 'UPDATE');
    const dlc = apps.filter(a => a.appType === 'DLC');

    const list = document.createElement('ul');
    list.className = 'list-group list-group-flush';
    // The base game stays directly visible, same as the List view - only
    // Updates/DLC (which can run long) collapse behind a section.
    base.forEach(app => list.appendChild(buildLibraryDetailAppRow(app, title, I18N.baseGame)));
    if (updates.length) {
        list.appendChild(buildLibraryDetailSection(
            I18N.updatesSection, updates.map(app => buildLibraryDetailAppRow(app, title))));
    }
    if (dlc.length) {
        list.appendChild(buildLibraryDetailSection(
            I18N.dlcSection, dlc.map(app => buildLibraryDetailAppRow(app, title))));
    }
    body.appendChild(list);
    card.appendChild(body);
    return card;
}

async function loadLibraryDetailPage() {
    const container = document.getElementById('libraryDetailBody');
    const empty = document.getElementById('libraryDetailEmpty');
    const loading = document.getElementById('libraryDetailLoading');
    const prevBtn = document.getElementById('libraryDetailPrev');
    const nextBtn = document.getElementById('libraryDetailNext');

    container.innerHTML = '';
    empty.classList.add('d-none');
    loading.classList.remove('d-none');
    prevBtn.disabled = true;
    nextBtn.disabled = true;

    let data;
    try {
        data = await gqlFetchStats(LIBRARY_DETAIL_QUERY, {
            path: libraryDetailPath, page: libraryDetailPage, pageSize: LIBRARY_DETAIL_PAGE_SIZE,
            search: libraryDetailSearch || null,
        });
    } catch (e) {
        console.error(e);
        loading.classList.add('d-none');
        empty.textContent = I18N.couldNotLoadFiles;
        empty.classList.remove('d-none');
        return;
    }

    loading.classList.add('d-none');
    libraryDetailTotal = data.titles.total;
    const items = data.titles.items || [];

    if (!items.length) {
        empty.classList.remove('d-none');
    } else {
        items.forEach(t => container.appendChild(buildLibraryDetailTitleCard(t)));
    }

    const totalPages = Math.max(1, Math.ceil(libraryDetailTotal / LIBRARY_DETAIL_PAGE_SIZE));
    document.getElementById('libraryDetailCount').textContent = I18N.filesPageCount
        .replace('{count}', count(libraryDetailTotal))
        .replace('{s}', pluralS(libraryDetailTotal))
        .replace('{page}', libraryDetailPage)
        .replace('{totalPages}', totalPages);
    prevBtn.disabled = libraryDetailPage <= 1;
    nextBtn.disabled = libraryDetailPage >= totalPages;
}

function openLibraryDetail(path) {
    libraryDetailPath = path;
    libraryDetailPage = 1;
    libraryDetailSearch = '';
    document.getElementById('libraryDetailSearch').value = '';
    document.getElementById('libraryDetailModalLabel').textContent = path;
    if (!libraryDetailModal) {
        libraryDetailModal = new bootstrap.Modal(document.getElementById('libraryDetailModal'));
    }
    libraryDetailModal.show();
    loadLibraryDetailPage();
}

document.getElementById('libraryDetailSearch').addEventListener('input', function () {
    libraryDetailSearch = this.value;
    clearTimeout(libraryDetailSearchDebounce);
    libraryDetailSearchDebounce = setTimeout(() => {
        libraryDetailPage = 1;
        loadLibraryDetailPage();
    }, 250);
});

document.getElementById('libraryDetailPrev').addEventListener('click', () => {
    if (libraryDetailPage > 1) { libraryDetailPage--; loadLibraryDetailPage(); }
});
document.getElementById('libraryDetailNext').addEventListener('click', () => {
    const totalPages = Math.max(1, Math.ceil(libraryDetailTotal / LIBRARY_DETAIL_PAGE_SIZE));
    if (libraryDetailPage < totalPages) { libraryDetailPage++; loadLibraryDetailPage(); }
});

// --- Re-verify everything now: force a full re-check, bypassing the "already
// has a verdict" skip a plain verify pass (and the automatic pipeline) both use.
// Confirmed first - unlike a plain verify pass, this can mean re-reading a whole
// large library from disk, not just picking up what's new. ---------------------

// --- Verify pending files: pick up anything still unverified, without a full
// Scan (which also discovers new files and re-organizes). The automatic pipeline
// already does this on its own at startup - this is for triggering it on demand
// in between, e.g. right after adding new content without wanting to restart. ---

const VERIFY_LIBRARY_MUTATION = `
    mutation VerifyLibraryNow {
        verifyLibrary { id status }
    }`;

document.getElementById('verifyNowBtn').addEventListener('click', async function () {
    const btn = this;
    const originalHtml = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = `<i class="bi bi-hourglass-split"></i> ${I18N.verifying}`;
    try {
        const r = await fetch('/api/graphql', {
            method: 'POST',
            headers: {'Content-Type': 'application/json', 'Accept': 'application/json'},
            credentials: 'same-origin',
            body: JSON.stringify({query: VERIFY_LIBRARY_MUTATION}),
        });
        if (!r.ok) throw new Error(`GraphQL HTTP ${r.status}`);
        const body = await r.json();
        if (body.errors && body.errors.length) {
            throw new Error('GraphQL errors: ' + JSON.stringify(body.errors));
        }
        btn.innerHTML = `<i class="bi bi-check-lg"></i> ${I18N.verifyQueued}`;
    } catch (e) {
        console.error(e);
        btn.innerHTML = `<i class="bi bi-exclamation-triangle"></i> ${I18N.verifyFailed}`;
    } finally {
        setTimeout(() => {
            btn.disabled = false;
            btn.innerHTML = originalHtml;
        }, 3000);
    }
});

// --- Downloads: who took what, and when -----------------------------------------


/** A downloads list: one row per item, or the "none yet" line. */
function dlList(id, rows) {
    const list = document.getElementById(id);
    list.innerHTML = '';
    if (!rows.length) {
        list.appendChild(titleListEmpty(DL.none));
        return;
    }
    rows.forEach(row => list.appendChild(titleListRow(row)));
}

function renderDownloads(d) {
    // The same tiles as the top of the page: icon, figure, label, note.
    const tiles = document.getElementById('downloadTiles');
    tiles.innerHTML = '';
    [[DL.count, count(d.total), DL.countNote.replace('__DAYS__', d.days), 'bi-download', 'nav'],
     [DL.bytes, formatBytes(d.total_bytes), DL.bytesNote, 'bi-hdd-network', 'action'],
     [DL.allTime, count(d.all_time), DL.allTimeNote, 'bi-archive', 'ok']].forEach(([label, value, note, icon, tone]) => {
        const tile = document.createElement('div');
        tile.className = `stat-tile stat-tile--${tone}`;
        const iconBox = document.createElement('span');
        iconBox.className = 'stat-tile__icon';
        iconBox.innerHTML = `<i class="bi ${icon}" aria-hidden="true"></i>`;
        tile.append(iconBox, textEl('div', 'stat-tile__value', value), textEl('div', 'stat-tile__label', label),
                    textEl('div', 'stat-tile__note', note));
        tiles.appendChild(tile);
    });

    const chart = document.getElementById('downloadChart');
    chart.innerHTML = '';
    chart.classList.toggle('is-dense', d.by_day.length > 60);
    const peak = Math.max(1, ...d.by_day.map(b => b.count));
    d.by_day.forEach(b => {
        const bar = document.createElement('div');
        bar.className = 'download-bar' + (b.count ? '' : ' empty');
        bar.style.height = (b.count ? Math.max(4, Math.round(100 * b.count / peak)) : 2) + '%';
        bar.title = DL.dayTitle.replace('__DATE__', new Date(b.date + 'T00:00').toLocaleDateString())
            .replace('__COUNT__', b.count);
        chart.appendChild(bar);
    });
    const axis = document.getElementById('downloadChartAxis');
    const fmt = iso => new Date(iso + 'T00:00').toLocaleDateString([], {day: 'numeric', month: 'short'});
    axis.innerHTML = '';
    if (d.by_day.length) {
        [d.by_day[0].date, d.by_day[d.by_day.length - 1].date].forEach(iso => {
            const span = document.createElement('span');
            span.textContent = fmt(iso);
            axis.appendChild(span);
        });
    }

    const client = c => DL.clients[c] || c;
    const clientGlyph = c => (c === 'web' ? 'bi-globe' : c === 'other' ? 'bi-question-circle' : 'bi-nintendo-switch');
    // Each list's share bars are against its own first row (the most).
    const share = (n, list) => 100 * n / Math.max(1, ...list.map(x => x.count));
    dlList('downloadTopTitles', d.top_titles.map((t, i) => ({
        main: t.name, side: count(t.count), titleId: t.title_id, rank: i + 1, pct: share(t.count, d.top_titles)})));
    dlList('downloadByUser', d.by_user.map(u => ({
        main: u.user || DL.anonymous, side: count(u.count), glyph: 'bi-person', avatarUrl: u.avatar_url || undefined,
        pct: share(u.count, d.by_user)})));
    dlList('downloadByClient', d.by_client.map(c => ({
        main: client(c.client), side: count(c.count), glyph: clientGlyph(c.client), pct: share(c.count, d.by_client)})));
    fillTitleIcons(document.getElementById('downloadsSection'));
    // Ten rows in view for the long list, four for the short ones beside it; the rest by
    // scrolling. (The latest downloads moved to the Dashboard.)
    [['downloadTopTitles', 10], ['downloadByUser', 4], ['downloadByClient', 4]]
        .forEach(([id, rows]) => limitVisibleRows(document.getElementById(id + 'Scroll'), 'li', rows));
}

function loadDownloads() {
    const days = document.getElementById('downloadsDaysSelect').value;
    fetch('/api/stats/downloads?days=' + days, {credentials: 'same-origin'})
        .then(r => r.json())
        .then(renderDownloads)
        .catch(err => console.error('Could not load download stats', err));
}

document.getElementById('downloadsDaysSelect').addEventListener('change', loadDownloads);
document.getElementById('clearDownloadsBtn').addEventListener('click', () => {
    if (!confirm(DL.clearConfirm)) return;
    fetch('/api/stats/downloads', {method: 'DELETE', credentials: 'same-origin'}).then(loadDownloads);
});
document.getElementById('refreshStats').addEventListener('click', loadDownloads);
loadDownloads();
