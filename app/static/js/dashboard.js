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

/** Recent items: icon, name, detail, time - a row with a title id leads to its game
 *  page (title-list.js). Icons arrive afterwards, in one request for every visible game. */
function renderList(id, items, render) {
    const list = document.getElementById(id);
    list.innerHTML = '';
    if (!items.length) {
        list.append(titleListEmpty(D.nothingYet));
        return;
    }
    items.forEach(item => {
        const [main, sub, side, titleId] = render(item);
        list.append(titleListRow({main, sub, side, titleId}));
    });
}

function renderStatus(d) {
    // (tone, text, link): green fine, amber worth a look, muted off.
    const badges = [
        [d.maintenance.enabled ? 'ok' : '',
         d.maintenance.enabled && d.maintenance.next_run ? fill(D.maintOn, {when: when(d.maintenance.next_run)}) : D.maintOff,
         '/admin/settings#Maintenance'],
        [d.maintenance.last_backup ? 'ok' : 'wait',
         d.maintenance.last_backup ? fill(D.lastBackup, {when: when(d.maintenance.last_backup)}) : D.noBackup,
         '/admin/settings#Maintenance'],
        [d.notifications_enabled ? 'ok' : '', d.notifications_enabled ? D.notifOn : D.notifOff,
         '/admin/settings#Notifications'],
        [d.shop_public ? 'wait' : 'ok', d.shop_public ? D.shopPublic : D.shopPrivate, '/admin/settings'],
    ];
    const box = document.getElementById('dashStatus');
    box.innerHTML = '';
    badges.forEach(([tone, text, href]) => {
        const a = el('a', 'status-badge dash-status' + (tone ? ` status-badge--${tone}` : ''), text);
        a.href = href;
        box.append(a);
    });
}

function loadDashboard() {
    fetch('/api/dashboard', {credentials: 'same-origin'})
        .then(r => r.json())
        .then(d => {
            renderAlerts(d);
            renderTiles(d);
            renderStorage(d);
            renderList('dashRecentFiles', d.recent_files, f => [
                f.name || f.filename,
                [D.types[f.app_type] || f.app_type, f.version && f.version !== '0' ? 'v' + f.version : '', formatBytes(f.size)]
                    .filter(Boolean).join(' · '),
                when(f.added_at), f.title_id]);
            renderList('dashRecentDownloads', d.recent_downloads, e => [
                e.name, [e.user || D.anonymous, D.clients[e.client] || e.client].join(' · '), when(e.downloaded_at),
                e.title_id]);
            renderStatus(d);
            limitVisibleRows(document.getElementById('dashRecentFiles'), 'li', 10);
            limitVisibleRows(document.getElementById('dashRecentDownloads'), 'li', 10);
            fillTitleIcons(document);
        })
        .catch(err => console.error('Could not load the dashboard', err));
}

document.getElementById('refreshDashboard').addEventListener('click', loadDashboard);
// A finished upload shows up in "Recently added" and the storage bar.
document.addEventListener('upload:finished', loadDashboard);
loadDashboard();
