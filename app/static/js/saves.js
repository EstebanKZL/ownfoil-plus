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

function when(iso) {
    return new Date(iso).toLocaleString(LANG, {dateStyle: 'medium', timeStyle: 'short'});
}

function backupRow(backup, game) {
    const li = node('li', 'saves-backup');
    const text = node('div', 'saves-backup__text');
    text.append(node('div', 'saves-backup__when', when(backup.time)),
                node('div', 'saves-backup__file', `${backup.name} · ${formatBytes(backup.size)}`));
    const download = node('a', 'icon-btn');
    const where = {path: backup.path};
    download.href = '/api/saves/download?' + new URLSearchParams(where);
    download.title = I18N.download;
    download.setAttribute('aria-label', I18N.download);
    download.append(node('i', 'bi bi-download'));
    const remove = node('button', 'icon-btn icon-btn--danger');
    remove.type = 'button';
    remove.title = I18N.remove;
    remove.setAttribute('aria-label', I18N.remove);
    remove.append(node('i', 'bi bi-trash'));
    remove.addEventListener('click', async () => {
        if (!confirm(I18N.deleteConfirm)) return;
        remove.disabled = true;
        const r = await fetch('/api/saves?' + new URLSearchParams(where),
                              {method: 'DELETE', credentials: 'same-origin'}).catch(() => null);
        if (r && r.ok) loadSaves();
        else remove.disabled = false;
    });
    li.append(text, download, remove);
    return li;
}

function gameCard(game) {
    const card = node('section', 'surface saves-game');
    const head = node('div', 'saves-game__head');
    const list = node('ul', 'dash-list');
    // The game itself, as every other list of games: icon, name, a line under it.
    const row = titleListRow({
        main: game.name, titleId: game.title_id || undefined, iconUrl: game.icon_url || undefined,
        sub: (game.backups.length === 1 ? I18N.backupsOne : I18N.backups)
                .replace('{count}', game.backups.length).replace('{size}', formatBytes(game.size)),
        side: when(game.latest),
    });
    list.append(row);
    head.append(list);
    const backups = node('ul', 'saves-backups');
    backups.append(...game.backups.map(b => backupRow(b, game)));
    card.append(head, backups);
    return card;
}

let allGames = [];

/** The games that match the search, by name. */
function renderSaves() {
    const query = document.getElementById('savesSearch').value.trim().toLowerCase();
    const shown = allGames.filter(g => !query || (g.name || '').toLowerCase().includes(query));
    document.getElementById('savesGames').replaceChildren(...shown.map(gameCard));
    document.getElementById('savesNoMatch').hidden = !allGames.length || shown.length > 0;
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
