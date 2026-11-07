// The Dashboard (templates/dashboard.html). The page renders the D strings in its one
// inline script, then loads this file; charts.js brings percentBar().

const LOW_SPACE = 0.05;   // warn below 5% free
const fmtNum = n => Number(n).toLocaleString();
const fill = (template, values) => Object.entries(values)
    .reduce((text, [key, value]) => text.split('{' + key + '}').join(value), template);
const when = iso => iso ? new Date(iso).toLocaleString([], {dateStyle: 'medium', timeStyle: 'short'}) : '';

function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
}

// The alert kinds' tones: amber waits for you, red is broken, cyan is information.
const NOTICE_TONES = {warning: 'wait', danger: 'danger', info: 'nav'};

function renderAlerts(d) {
    const alerts = [];
    const lib = d.library;
    if (!d.keys_valid) alerts.push(['danger', 'bi-key', D.alertKeys, '/admin/settings']);
    d.storage.filter(s => !s.online).forEach(s =>
        alerts.push(['danger', 'bi-hdd-network', fill(D.alertOffline, {path: s.path}), '/admin/settings']));
    d.storage.filter(s => s.online && s.total && s.free / s.total < LOW_SPACE).forEach(s =>
        alerts.push(['warning', 'bi-hdd', fill(D.alertLowSpace, {path: s.path, free: formatBytes(s.free)}), '/admin/stats']));
    if (lib.corrupt) alerts.push(['danger', 'bi-shield-exclamation', fill(D.alertCorrupt, {n: fmtNum(lib.corrupt)}), '/admin/files#verification']);
    if (d.tasks.failed) alerts.push(['warning', 'bi-exclamation-triangle', fill(D.alertFailed, {n: fmtNum(d.tasks.failed)}), '/admin/tasks']);
    if (lib.unidentified) alerts.push(['warning', 'bi-question-circle', fill(D.alertUnidentified, {n: fmtNum(lib.unidentified)}), '/admin/files#unidentified']);
    if (lib.duplicates) alerts.push(['info', 'bi-files', fill(D.alertDuplicates, {n: fmtNum(lib.duplicates)}), '/admin/files#duplicates']);
    if (!d.maintenance.last_backup) alerts.push(['info', 'bi-archive', D.alertNoBackup, '/admin/settings#Maintenance']);

    const box = document.getElementById('dashAlerts');
    box.innerHTML = '';
    if (!alerts.length) {
        const ok = el('div', 'dash-notice dash-notice--ok');
        ok.append(el('i', 'bi bi-check-circle'), el('span', '', D.allGood));
        box.append(ok);
        return;
    }
    alerts.forEach(([kind, icon, text, href]) => {
        const a = el('a', `dash-notice dash-notice--${NOTICE_TONES[kind]}`);
        a.href = href;
        a.append(el('i', `bi ${icon}`), el('span', 'dash-notice__text', text), el('i', 'bi bi-chevron-right'));
        box.append(a);
    });
}

function renderTiles(d) {
    const lib = d.library;
    const pct = (n, of) => of ? Math.round(100 * n / of) + '%' : '-';
    // (value, label, note, link, icon, tone) - the tone is the tile's one color.
    const tiles = [
        [fmtNum(lib.owned_titles), D.tileTitles,
         fill(D.tileTitlesNote, {complete: pct(lib.complete_titles, lib.owned_titles), uptodate: pct(lib.up_to_date_titles, lib.owned_titles)}),
         '/', 'bi-controller', 'ok'],
        [fmtNum(lib.files), D.tileFiles, fill(D.tileFilesNote, {size: formatBytes(lib.size)}),
         '/admin/files', 'bi-hdd-stack', 'nav'],
        [fmtNum(d.downloads_week), D.tileDownloads, D.tileDownloadsNote,
         '/admin/stats#downloadsSection', 'bi-download', 'action'],
        [fmtNum(d.tasks.running + d.tasks.pending), D.tileTasks,
         fill(D.tileTasksNote, {running: fmtNum(d.tasks.running), pending: fmtNum(d.tasks.pending)}),
         '/admin/tasks', 'bi-list-task', 'wait'],
    ];
    const box = document.getElementById('dashTiles');
    box.innerHTML = '';
    tiles.forEach(([value, label, note, href, icon, tone]) => {
        const a = el('a', `stat-tile stat-tile--${tone}`);
        a.href = href;
        const iconBox = el('span', 'stat-tile__icon');
        iconBox.append(el('i', `bi ${icon}`));
        a.append(iconBox, el('div', 'stat-tile__value', value), el('div', 'stat-tile__label', label),
                 el('div', 'stat-tile__note', note));
        box.append(a);
    });
}

/** Free space as a tone: red below 5 %, amber below 15 %, green otherwise. */
function storageTone(freePct) {
    if (freePct < 5) return 'danger';
    if (freePct < 15) return 'wait';
    return 'ok';
}

function renderStorage(d) {
    const box = document.getElementById('dashStorage');
    box.innerHTML = '';
    d.storage.forEach(s => {
        const row = el('div', 'dash-storage');
        const head = el('div', 'dash-storage__head');
        head.append(el('span', 'dash-storage__path', s.path));
        // Offline, or a filesystem that reports no total: nothing to divide by.
        if (!s.online || !s.total) {
            head.append(el('span', 'dash-storage__offline', D.offline));
            row.append(head);
            box.append(row);
            return;
        }
        const usedPct = Math.round(100 * s.used / s.total);
        const freePct = 100 * s.free / s.total;
        head.append(el('span', 'dash-storage__figures',
            fill(D.storageUsed, {used: formatBytes(s.used), total: formatBytes(s.total), free: formatBytes(s.free)})));
        row.append(head, percentBar(usedPct, storageTone(freePct)));
        box.append(row);
    });
}

const clientName = c => D.clients[c] || c;
const clientGlyph = c => (c === 'web' ? 'bi-globe' : c === 'other' ? 'bi-question-circle' : 'bi-nintendo-switch');
const stamp = iso => new Date(iso).toLocaleString([], {dateStyle: 'short', timeStyle: 'short'});

/** A list in the Stats look (title-list.js rows with chips): `rows` as titleListRow takes
 *  them, plus an optional action link appended to each row. */
function renderCardList(id, rows) {
    const list = document.getElementById(id);
    list.innerHTML = '';
    if (!rows.length) {
        list.append(titleListEmpty(D.nothingYet));
    }
    rows.forEach(({action, ...row}) => {
        const li = titleListRow(row);
        if (action) li.querySelector('.dash-list__row').append(action);
        list.append(li);
    });
    limitVisibleRows(document.getElementById(id + 'Scroll'), 'li', 10);
}

/** An admin's download of one uploaded save (any user's). */
function saveDownloadLink(s) {
    const a = el('a', 'btn btn-sm icon-btn dash-list__action');
    a.href = '/api/admin/saves/download?' + new URLSearchParams({user: s.user_id, path: s.path});
    a.title = D.downloadSave;
    a.setAttribute('aria-label', `${D.downloadSave}: ${s.name}`);
    a.innerHTML = '<i class="bi bi-download" aria-hidden="true"></i>';
    return a;
}

function loadDashboard() {
    fetch('/api/dashboard', {credentials: 'same-origin'})
        .then(r => r.json())
        .then(d => {
            renderAlerts(d);
            renderTiles(d);
            renderStorage(d);
            renderCardList('dashRecentDownloads', d.recent_downloads.map(r => ({
                main: r.name || r.title_id || r.filename,
                sub: [r.filename, r.size ? formatBytes(r.size) : null, r.address].filter(Boolean).join(' · '),
                chips: [{text: r.user || D.anonymous, avatarUrl: r.user_avatar || undefined, glyph: 'bi-person'},
                        {text: clientName(r.client), glyph: clientGlyph(r.client)}],
                side: stamp(r.downloaded_at), titleId: r.title_id})));
            renderCardList('dashRecentSaves', (d.recent_saves || []).map(s => ({
                main: s.name, sub: [s.file, s.size ? formatBytes(s.size) : null].filter(Boolean).join(' · '),
                iconUrl: s.icon_url || undefined, glyph: 'bi-safe',
                chips: [{text: s.user, avatarUrl: s.user_avatar || undefined, glyph: 'bi-person'}],
                side: stamp(s.time), action: saveDownloadLink(s)})));
            renderCardList('dashRecentFiles', d.recent_files.map(f => ({
                main: f.name || f.filename, sub: f.filename,
                chips: [{text: D.types[f.app_type] || f.app_type || '?', glyph: 'bi-box'},
                        ...(f.version && f.version !== '0' ? [{text: 'v' + f.version, glyph: 'bi-arrow-up-circle'}] : []),
                        {text: formatBytes(f.size), glyph: 'bi-hdd'}],
                side: f.added_at ? stamp(f.added_at) : '', titleId: f.title_id})));
            fillTitleIcons(document);
        })
        .catch(err => console.error('Could not load the dashboard', err));
}

document.getElementById('refreshDashboard').addEventListener('click', loadDashboard);
// A finished upload shows up in "Recently added" and the storage bar.
document.addEventListener('upload:finished', loadDashboard);
loadDashboard();
