/* Upcoming releases (/upcoming): "for you" (wishlist and sequels of the user's sagas)
   and the calendar by month, from /api/upcoming. The heart adds a game to the user's
   wishlist (/api/wishlist). Strings come from the page's inline I18N object. */

const LANG = document.documentElement.lang || undefined;
let upcomingData = null;

function node(tag, className, text) {
    const n = document.createElement(tag);
    if (className) n.className = className;
    if (text !== undefined && text !== null) n.textContent = text;
    return n;
}

/** 2026-12-10 -> "10 dic 2026", in the page's language. */
function formatDay(iso) {
    return new Date(iso + 'T00:00').toLocaleDateString(LANG, {day: 'numeric', month: 'short', year: 'numeric'});
}

/** 2026-12 -> "diciembre de 2026". */
function formatMonth(month) {
    return new Date(month + '-01T00:00').toLocaleDateString(LANG, {month: 'long', year: 'numeric'});
}

/** One game: its cover, name, date and sagas, and the wishlist heart. */
function releaseCard(game) {
    const card = node('article', 'release-card');
    card.dataset.name = game.name.toLowerCase();
    if (game.sequel) card.classList.add('is-sequel');
    const link = node('a', 'release-card__link');
    link.href = `/game/${game.title_id}`;
    const cover = node('div', 'release-card__cover');
    if (game.icon_url) {
        const img = node('img');
        img.src = game.icon_url;
        img.alt = '';
        img.loading = 'lazy';
        img.addEventListener('error', () => img.replaceWith(node('i', 'bi bi-controller')));
        cover.append(img);
    } else {
        cover.append(node('i', 'bi bi-controller'));
    }
    if (game.switch2) cover.append(node('span', 'release-card__console', 'Switch 2'));
    link.append(cover, node('div', 'release-card__name', game.name), node('div', 'release-card__date', formatDay(game.release_date)));
    const sagas = (game.series || []).filter(s => s.name);
    if (sagas.length) {
        const chips = node('div', 'release-card__sagas');
        sagas.forEach(s => chips.append(node('span', 'release-chip', s.name)));
        link.append(chips);
    }
    if (game.sequel) link.title = I18N.sequel;
    card.append(link);
    if (CAN_WISHLIST) card.append(heartButton(game));
    return card;
}

function heartButton(game) {
    const button = node('button', 'release-card__heart');
    button.type = 'button';
    const paint = () => {
        button.classList.toggle('is-on', game.wishlisted);
        button.setAttribute('aria-pressed', String(game.wishlisted));
        button.title = game.wishlisted ? I18N.wishlistRemove : I18N.wishlistAdd;
        button.setAttribute('aria-label', button.title);
        button.innerHTML = `<i class="bi ${game.wishlisted ? 'bi-heart-fill' : 'bi-heart'}" aria-hidden="true"></i>`;
    };
    paint();
    button.addEventListener('click', async () => {
        button.disabled = true;
        const adding = !game.wishlisted;
        try {
            const r = adding
                ? await fetch('/api/wishlist', {method: 'POST', credentials: 'same-origin',
                                                headers: {'Content-Type': 'application/json'},
                                                body: JSON.stringify({title_id: game.title_id})})
                : await fetch(`/api/wishlist/${game.title_id}`, {method: 'DELETE', credentials: 'same-origin'});
            if (!r.ok) throw new Error(`HTTP ${r.status}`);
            // The same game may be on screen twice (for you and its month): keep both in step.
            upcomingData.months.forEach(m => m.games.forEach(g => { if (g.title_id === game.title_id) g.wishlisted = adding; }));
            (upcomingData.recent || []).forEach(g => { if (g.title_id === game.title_id) g.wishlisted = adding; });
            render();
        } catch (e) {
            button.disabled = false;
        }
    });
    return button;
}

/** A just-released game: its card, with the day it came out over the cover. */
function recentCard(game) {
    const card = releaseCard(game);
    card.classList.add('release-card--recent');
    const day = new Date(game.release_date + 'T00:00').toLocaleDateString(LANG, {day: 'numeric', month: 'short'});
    const chip = node('span', 'release-card__day');
    chip.append(node('i', 'bi bi-calendar-event'), document.createTextNode(' ' + day));
    card.querySelector('.release-card__cover').append(chip);
    return card;
}

function render() {
    const recent = upcomingData.recent || [];
    document.getElementById('upcomingRecentStrip').replaceChildren(...recent.map(recentCard));
    document.getElementById('upcomingRecentCount').textContent = recent.length;
    document.getElementById('upcomingRecent').hidden = !recent.length;

    const forYou = upcomingData.months.flatMap(m => m.games).filter(g => g.wishlisted || g.sequel);
    const forYouGrid = document.getElementById('upcomingForYouGrid');
    forYouGrid.replaceChildren(...forYou.map(releaseCard));
    document.getElementById('upcomingForYouEmpty').hidden = forYou.length > 0;
    document.getElementById('upcomingForYou').hidden = !CAN_WISHLIST && !forYou.length;

    const months = document.getElementById('upcomingMonths');
    months.replaceChildren(...upcomingData.months.map(m => {
        const block = node('div', 'release-month');
        block.append(node('h3', 'release-month__title', formatMonth(m.month)));
        const grid = node('div', 'release-grid');
        grid.append(...m.games.map(releaseCard));
        block.append(grid);
        return block;
    }));
    document.getElementById('upcomingNone').hidden = upcomingData.months.length > 0;
    document.getElementById('upcomingCalendar').hidden = false;
    applySearch();
}

/** Hides the games whose name doesn't contain what is typed, and the months left empty. */
function applySearch() {
    const text = document.getElementById('upcomingSearch').value.trim().toLowerCase();
    document.querySelectorAll('.release-card').forEach(card => {
        card.hidden = Boolean(text) && !card.dataset.name.includes(text);
    });
    const strip = document.getElementById('upcomingRecent');
    if (upcomingData.recent && upcomingData.recent.length) {
        strip.hidden = !document.querySelector('#upcomingRecentStrip .release-card:not([hidden])');
    }
    let shown = 0;
    document.querySelectorAll('.release-month').forEach(month => {
        month.hidden = !month.querySelector('.release-card:not([hidden])');
        if (!month.hidden) shown++;
    });
    document.getElementById('upcomingNoMatch').hidden = !text || shown > 0 || !upcomingData.months.length;
}

async function loadUpcoming() {
    try {
        const r = await fetch('/api/upcoming', {credentials: 'same-origin'});
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        upcomingData = await r.json();
        render();
    } catch (e) {
        document.getElementById('upcomingError').hidden = false;
    } finally {
        document.getElementById('upcomingLoading').hidden = true;
    }
}

document.getElementById('upcomingSearch').addEventListener('input', () => { if (upcomingData) applySearch(); });
loadUpcoming();
