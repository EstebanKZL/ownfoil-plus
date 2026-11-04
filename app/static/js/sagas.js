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
    const bar = node('div', 'saga-progress__bar');
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

async function loadList() {
    const data = await getJson('/api/sagas');
    const list = document.getElementById('sagasList');
    list.replaceChildren(...data.sagas.map(saga => {
        const card = node('a', 'saga-card surface');
        card.href = `/sagas/${saga.id}`;
        const collage = node('div', 'saga-card__collage');
        (saga.icons.length ? saga.icons : [null]).forEach(url => collage.append(cover(url)));
        card.append(collage, node('div', 'saga-card__name', saga.name), progress(saga));
        return card;
    }));
    show('sagasNone', !data.sagas.length);
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
        link.append(cover(game.icon_url), node('div', 'release-card__name', game.name),
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
