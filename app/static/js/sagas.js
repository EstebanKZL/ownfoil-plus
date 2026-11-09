/* Sagas (/sagas): the series the user has games of, "4 of 6" each; or one saga
   (/sagas/<id>, SAGA_ID) with the games owned, missing and still to come. From
   /api/sagas. Strings come from the page's inline I18N object. */

const LANG = document.documentElement.lang || undefined;

function node(tag, className, text) {
    const n = document.createElement(tag);
    if (className) n.className = className;
    if (text !== undefined && text !== null) n.textContent = text;
    return n;
}

function cover(url) {
    const box = node('div', 'release-card__cover');
    if (url) {
        const img = node('img');
        img.src = url;
        img.alt = '';
        img.loading = 'lazy';
        img.addEventListener('error', () => img.replaceWith(node('i', 'bi bi-controller')));
        box.append(img);
    } else {
        box.append(node('i', 'bi bi-controller'));
    }
    return box;
}

/** "4 of 6" and a bar, plus "+1 coming" when the saga has games still to come. */
function progress(saga) {
    const wrap = node('div', 'saga-progress');
    const label = node('div', 'saga-progress__label');
    label.append(node('strong', null, I18N.count.replace('{owned}', saga.owned).replace('{total}', saga.total)));
    if (saga.upcoming) label.append(node('span', 'saga-progress__coming', I18N.upcomingCount.replace('{n}', saga.upcoming)));
    const bar = node('div', 'saga-progress__bar saga-progress__bar--striped');
    const fill = node('div', 'saga-progress__fill');
    fill.style.width = `${Math.round(100 * saga.owned / Math.max(saga.total, 1))}%`;
    bar.append(fill);
    bar.setAttribute('role', 'img');
    bar.setAttribute('aria-label', label.textContent);
    wrap.append(label, bar);
    return wrap;
}

function show(id, visible) {
    document.getElementById(id).hidden = !visible;
}

async function getJson(url) {
    const r = await fetch(url, {credentials: 'same-origin'});
    if (r.status === 404) return null;
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    return r.json();
}

/** One saga's card: its cover, name and "4 of 6", the bar, a strip with every game out
 *  (the missing ones greyed) and "View the saga". */
function sagaCard(saga) {
    const card = node('article', 'saga-card surface');
    const link = `/sagas/${saga.id}`;
    const coverLink = node('a', 'saga-card__cover');
    coverLink.href = link;
    coverLink.setAttribute('aria-hidden', 'true');
    coverLink.tabIndex = -1;
    coverLink.append(cover(saga.cover));
    const body = node('div', 'saga-card__body');
    const head = node('div', 'saga-card__head');
    const name = node('a', 'saga-card__name', saga.name);
    name.href = link;
    // A complete saga: a gold frame and a trophy before its "10 of 10".
    const complete = saga.total > 0 && saga.owned >= saga.total;
    card.classList.toggle('is-complete', complete);
    const count = node('span', 'saga-card__count');
    if (complete) count.append(node('i', 'bi bi-trophy-fill saga-card__trophy'));
    count.append(document.createTextNode(
        I18N.count.replace('{owned}', saga.owned).replace('{total}', saga.total)));
    head.append(name, count);
    const bar = node('div', 'saga-progress__bar saga-progress__bar--striped');
    const fill = node('div', 'saga-progress__fill');
    fill.style.width = `${Math.round(100 * saga.owned / Math.max(saga.total, 1))}%`;
    bar.append(fill);
    const strip = node('div', 'saga-card__strip');
    // One row: up to SAGA_THUMBS covers, the rest as "+N" (opening the saga).
    const games = saga.games || [];
    const shown = games.length > SAGA_THUMBS ? games.slice(0, SAGA_THUMBS - 1) : games;
    shown.forEach(game => {
        const thumb = node('a', 'saga-thumb' + (game.owned ? '' : ' is-missing'));
        thumb.href = `/game/${game.title_id}`;
        thumb.title = `${game.name} - ${game.owned ? I18N.owned : I18N.missing}`;
        thumb.append(cover(game.icon_url));
        strip.append(thumb);
    });
    if (shown.length < games.length) {
        const more = node('a', 'saga-thumb saga-thumb--more', `+${games.length - shown.length}`);
        more.href = link;
        strip.append(more);
    }
    const view = node('a', 'btn btn-sm btn-outline-secondary saga-card__view');
    view.href = link;
    view.append(node('i', 'bi bi-grid-3x3-gap'), document.createTextNode(' ' + I18N.view));
    body.append(head, bar, strip, view);
    card.append(coverLink, body);
    return card;
}

const SAGA_TAB_KEY = 'sagasTab';
// Cards a page: 24 fills every row at one, two or three columns (the grid's widths), so
// only the last page can end with a short row.
const SAGAS_PER_PAGE = 24;
let sagaPage = 1;
let sagaView = '';
const SAGA_THUMBS = 6;   // covers in a card's row (the last one "+N" when there are more)
let allSagas = [];

function sagaTab() {
    try {
        const tab = localStorage.getItem(SAGA_TAB_KEY);
        return ['all', 'incomplete', 'complete'].includes(tab) ? tab : 'all';
    } catch (e) { return 'all'; }
}

/** The sagas of the chosen tab that match the search. */
function renderSagaList() {
    const tab = sagaTab();
    const query = document.getElementById('sagasSearch').value.trim().toLowerCase();
    const isComplete = s => s.owned >= s.total;
    document.getElementById('sagasAllCount').textContent = allSagas.length;
    document.getElementById('sagasIncompleteCount').textContent = allSagas.filter(s => !isComplete(s)).length;
    document.getElementById('sagasCompleteCount').textContent = allSagas.filter(isComplete).length;
    document.querySelectorAll('[data-saga-tab]').forEach(b => {
        b.classList.toggle('active', b.dataset.sagaTab === tab);
        b.setAttribute('aria-pressed', String(b.dataset.sagaTab === tab));
    });
    const shown = allSagas.filter(s => (tab === 'all' || isComplete(s) === (tab === 'complete'))
                                       && (!query || s.name.toLowerCase().includes(query)));
    // Another tab or search starts at the first page.
    const view = tab + '\n' + query;
    if (view !== sagaView) { sagaView = view; sagaPage = 1; }
    const pages = Math.max(1, Math.ceil(shown.length / SAGAS_PER_PAGE));
    sagaPage = Math.min(sagaPage, pages);
    const page = shown.slice((sagaPage - 1) * SAGAS_PER_PAGE, sagaPage * SAGAS_PER_PAGE);
    document.getElementById('sagasList').replaceChildren(...page.map(sagaCard));
    renderSagaPager(pages);
    show('sagasNoMatch', allSagas.length > 0 && !shown.length);
}

/** The pages under the grid: « 1 2 3 … 9 », as in the Library. */
function renderSagaPager(pages) {
    const bar = document.getElementById('sagasPager');
    bar.replaceChildren();
    bar.hidden = pages <= 1;
    if (pages <= 1) return;
    const item = (label, target, {active = false, disabled = false, aria} = {}) => {
        const li = node('li', 'page-item' + (active ? ' active' : '') + (disabled ? ' disabled' : ''));
        const a = node(disabled && target === null ? 'span' : 'a', 'page-link', label);
        if (a.tagName === 'A') {
            a.href = '#';
            a.addEventListener('click', e => {
                e.preventDefault();
                if (disabled || target === sagaPage) return;
                sagaPage = target;
                renderSagaList();
                document.getElementById('sagasToolbar').scrollIntoView({block: 'start', behavior: 'smooth'});
            });
        }
        if (aria) a.setAttribute('aria-label', aria);
        if (active) a.setAttribute('aria-current', 'page');
        li.append(a);
        return li;
    };
    bar.append(item('«', sagaPage - 1, {disabled: sagaPage === 1, aria: I18N.previous}));
    const wanted = new Set([1, pages, sagaPage - 1, sagaPage, sagaPage + 1]);
    let last = 0;
    for (let p = 1; p <= pages; p++) {
        if (!wanted.has(p)) continue;
        if (p - last > 1) bar.append(item('…', null, {disabled: true}));
        bar.append(item(String(p), p, {active: p === sagaPage}));
        last = p;
    }
    bar.append(item('»', sagaPage + 1, {disabled: sagaPage === pages, aria: I18N.next}));
}

async function loadList() {
    const data = await getJson('/api/sagas');
    allSagas = data.sagas;
    show('sagasNone', !allSagas.length);
    show('sagasToolbar', allSagas.length > 0);
    document.getElementById('sagasSearch').addEventListener('input', renderSagaList);
    document.querySelectorAll('[data-saga-tab]').forEach(b => b.addEventListener('click', () => {
        try { localStorage.setItem(SAGA_TAB_KEY, b.dataset.sagaTab); } catch (e) { /* this visit only */ }
        renderSagaList();
    }));
    renderSagaList();
}

async function loadSaga() {
    const saga = await getJson(`/api/sagas/${SAGA_ID}`);
    show('sagasBack', true);
    if (!saga) {
        show('sagasNotFound', true);
        return;
    }
    document.getElementById('sagasTitle').textContent = saga.name;
    document.title = `${saga.name} - ${document.title}`;
    document.getElementById('sagaSummary').replaceChildren(progress(saga));
    document.getElementById('sagaGames').replaceChildren(...saga.games.map(game => {
        const card = node('article', 'release-card');
        card.classList.toggle('is-missing', !game.owned && !game.upcoming);
        card.classList.toggle('is-upcoming', game.upcoming);
        const link = node('a', 'release-card__link');
        link.href = `/game/${game.title_id}`;
        const state = game.owned ? I18N.owned
            : game.upcoming ? I18N.coming.replace('{date}', new Date(game.release_date + 'T00:00')
                .toLocaleDateString(LANG, {day: 'numeric', month: 'short', year: 'numeric'}))
            : I18N.missing;
        const art = cover(game.icon_url);
        // Each game says its console: "Switch 2", or plain "Switch" for the first one.
        art.append(node('span', 'release-card__console', game.switch2 ? 'Switch 2' : 'Switch'));
        link.append(art, node('div', 'release-card__name', game.name),
                    node('div', 'release-card__date', state));
        card.append(link);
        return card;
    }));
    show('sagaDetail', true);
}

(async () => {
    try {
        if (SAGA_ID === null) await loadList();
        else if (SAGA_ID) await loadSaga();
        else { show('sagasBack', true); show('sagasNotFound', true); }
    } catch (e) {
        show('sagasError', true);
    } finally {
        show('sagasLoading', false);
    }
})();
