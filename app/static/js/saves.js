/* Saves (/saves): the save vault's backups by game, from /api/saves - download or delete
   one - and the library's games without any. Strings come from the inline I18N object;
   formatBytes from format.js, titleListRow from title-list.js. */

const LANG = document.documentElement.lang || undefined;

function node(tag, className, text) {
    const n = document.createElement(tag);
    if (className) n.className = className;
    if (text !== undefined && text !== null) n.textContent = text;
    return n;
}

function day(iso) {
    return new Date(iso).toLocaleDateString(LANG, {day: 'numeric', month: 'short', year: 'numeric'});
}

function hour(iso) {
    return new Date(iso).toLocaleTimeString(LANG, {hour: '2-digit', minute: '2-digit'});
}

/** One backup, a block of the game's strip: its day, hour and size. The block itself
 *  downloads it (a small arrow says so); its bin, a button of its own, shows on hover or
 *  focus - always on a touch screen. The newest (the first: the API sends them newest
 *  first) is marked. The file's name rides in the tooltip. */
function backupTile(backup, index) {
    const tile = node('li', 'saves-tile' + (index === 0 ? ' is-newest' : ''));
    const where = {path: backup.path};
    const download = node('a', 'saves-tile__main');
    download.href = '/api/saves/download?' + new URLSearchParams(where);
    download.title = backup.name;
    download.setAttribute('aria-label', `${I18N.download}: ${backup.name}`);
    if (index === 0) download.append(node('span', 'saves-tile__badge', I18N.newest));
    download.append(node('span', 'saves-tile__day', day(backup.time)),
                    node('span', 'saves-tile__hour', hour(backup.time)));
    const foot = node('span', 'saves-tile__foot');
    foot.append(node('span', 'saves-tile__size', formatBytes(backup.size)),
                node('i', 'bi bi-download saves-tile__glyph'));
    download.append(foot);
    const remove = node('button', 'saves-tile__remove icon-btn icon-btn--danger');
    remove.type = 'button';
    remove.title = I18N.remove;
    remove.setAttribute('aria-label', `${I18N.remove}: ${backup.name}`);
    remove.append(node('i', 'bi bi-trash'));
    remove.addEventListener('click', async () => {
        if (!confirm(I18N.deleteConfirm)) return;
        remove.disabled = true;
        const r = await fetch('/api/saves?' + new URLSearchParams(where),
                              {method: 'DELETE', credentials: 'same-origin'}).catch(() => null);
        if (r && r.ok) loadSaves();
        else remove.disabled = false;
    });
    tile.append(download, remove);
    return tile;
}

/** A game, one row: its icon, name and totals fixed on the left, its backups as blocks
 *  in a strip to the right, newest first, scrolling sideways when they don't fit (asked
 *  for: a server keeping every backup made a column that never ended). */
function gameCard(game) {
    const card = node('section', 'surface saves-game');
    const info = node('ul', 'dash-list saves-game__info');
    info.append(titleListRow({
        main: game.name, titleId: game.title_id || undefined, iconUrl: game.icon_url || undefined,
        sub: (game.backups.length === 1 ? I18N.backupsOne : I18N.backups)
                .replace('{count}', game.backups.length).replace('{size}', formatBytes(game.size)),
    }));
    const strip = node('ul', 'saves-strip');
    strip.append(...game.backups.map(backupTile));
    card.append(info, strip);
    return card;
}

let allGames = [];
// Games a page, remembered per browser.
const SAVES_SIZES = [5, 10, 20, 50];
let savesPerPage = Pager.perPage('saves', SAVES_SIZES, 10);
let savesPage = 1;
let savesQuery = '';

/** The games that match the search, by name, a page of them. */
function renderSaves() {
    const query = document.getElementById('savesSearch').value.trim().toLowerCase();
    if (query !== savesQuery) { savesQuery = query; savesPage = 1; }
    const shown = allGames.filter(g => !query || (g.name || '').toLowerCase().includes(query));
    const pages = Math.max(1, Math.ceil(shown.length / savesPerPage));
    savesPage = Math.min(savesPage, pages);
    const page = shown.slice((savesPage - 1) * savesPerPage, savesPage * savesPerPage);
    document.getElementById('savesGames').replaceChildren(...page.map(gameCard));
    document.getElementById('savesNoMatch').hidden = !allGames.length || shown.length > 0;
    Pager.render(document.getElementById('savesPager'), {
        total: shown.length, page: savesPage, perPage: savesPerPage, sizes: SAVES_SIZES,
        onPage: p => {
            savesPage = p;
            renderSaves();
            document.getElementById('savesToolbar').scrollIntoView({block: 'start', behavior: 'smooth'});
        },
        onPerPage: n => {
            savesPerPage = n;
            Pager.savePerPage('saves', n);
            savesPage = 1;
            renderSaves();
        },
    });
    fillTitleIcons(document);
}

document.getElementById('savesSearch').addEventListener('input', renderSaves);

async function loadSaves() {
    try {
        const r = await fetch('/api/saves', {credentials: 'same-origin'});
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const data = await r.json();
        allGames = data.games;
        document.getElementById('savesOff').hidden = data.enabled;
        document.getElementById('savesNone').hidden = data.games.length > 0 || !data.enabled;
        document.getElementById('savesToolbar').hidden = !data.games.length;
        renderSaves();
    } catch (e) {
        document.getElementById('savesError').hidden = false;
    } finally {
        document.getElementById('savesLoading').hidden = true;
    }
}

loadSaves();
