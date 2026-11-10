// The Files admin page (templates/files.html). The page renders its I18N strings and
// server values in its one inline script, then loads this file.

// Mirrors library.py's DUPLICATE_RANK: Valid beats Repack beats Corrupt. A status
// outside this map (Unverified, Modified, Signature ok/failed) never appears here -
// a group with any such file never gets a recommendedKeepId in the first place.
const DUPLICATE_RANK = {VALID: 3, REPACK: 2, CORRUPT: 1};
// Rows a page of All files, remembered per browser.
const FILE_SIZES = [50, 100, 200];
let pageSize = Pager.perPage('files', FILE_SIZES, 100);
const BROKEN = ['SIGNATURE_FAILED', 'MODIFIED', 'CORRUPT'];
// Every library format can be verified, so UNVERIFIED always means not checked yet.
const VERIFICATION_ISSUES = [...BROKEN, 'UNVERIFIED'];

const FILE_FIELDS = `fragment F on File {
    id filename filepath folder extension size compressed organized multicontent libraryId
    identificationType identificationError identificationAttempts
    verificationStatus verificationError verifiedAt addedAt downloadCount
    apps { appId appType appVersion displayVersion titleId title { name iconUrl } }
}`;

async function gql(query, variables, post) {
    const r = post
        ? await fetch('/api/graphql', {
            method: 'POST',
            headers: {'Content-Type': 'application/json', 'Accept': 'application/json'},
            credentials: 'same-origin',
            body: JSON.stringify({query: query, variables: variables || {}}),
        })
        : await fetch('/api/graphql?' + new URLSearchParams(
            {query: query, variables: JSON.stringify(variables || {})}), {
            headers: {'Accept': 'application/json'},
            credentials: 'same-origin',
        });
    if (!r.ok) throw new Error(`GraphQL HTTP ${r.status}`);
    const body = await r.json();
    if (body.errors && body.errors.length) throw new Error(body.errors.map(e => e.message).join('; '));
    return body.data;
}

function el(tag, props, ...children) {
    const node = Object.assign(document.createElement(tag), props || {});
    children.flat(Infinity).forEach(c => c != null && node.append(c));
    return node;
}

function humanize(key) {
    const words = key.replace(/_/g, ' ').toLowerCase();
    return words.charAt(0).toUpperCase() + words.slice(1);
}

function parseDate(text, utc) {
    if (!text) return null;
    const iso = text.replace(' ', 'T').replace(/(\.\d{3})\d+/, '$1');
    return new Date(utc && !/[zZ]|[+-]\d\d:\d\d$/.test(iso) ? iso + 'Z' : iso);
}

const AGO = [[60, I18N.unitSeconds], [60, I18N.unitMinutes], [24, I18N.unitHours], [30, I18N.unitDays],
            [12, I18N.unitMonths], [Infinity, I18N.unitYears]];

function ago(date) {
    if (!date) return '';
    let n = Math.max(0, (Date.now() - date) / 1000), i = 0;
    while (n >= AGO[i][0]) n /= AGO[i++][0];
    return I18N.agoTemplate.replace('{n}', Math.floor(n)).replace('{unit}', AGO[i][1]);
}

function when(date) {
    return date ? el('span', {textContent: ago(date), title: date.toLocaleString()}) : null;
}

function muted(text) {
    return text ? el('span', {className: 'text-secondary', textContent: text}) : null;
}

/** A small chip; with a `tone` (base, update, dlc, multi) it wears that content
 *  type's fixed color, the same in every style. */
function chip(text, tone) {
    return el('span', {className: tone ? `files-chip files-chip--${tone}` : 'files-chip', textContent: text});
}

const yesNo = v => v ? I18N.yes : I18N.no;

const STATUS_TONE = {VALID: 'success', REPACK: 'success', SIGNATURE_OK: 'info', UNVERIFIED: 'secondary',
                     SIGNATURE_FAILED: 'danger', MODIFIED: 'danger', CORRUPT: 'danger'};

// Mirrors STATUS_TONE's keys - every verification status this page ever shows.
// Falls back to the generic humanize() for anything outside that set (there
// shouldn't be one, but never show a blank label over a translation gap).
const STATUS_LABEL = {VALID: I18N.statusValid, REPACK: I18N.statusRepack, CORRUPT: I18N.statusCorrupt,
                      SIGNATURE_OK: I18N.statusSignatureOk, SIGNATURE_FAILED: I18N.statusSignatureFailed,
                      MODIFIED: I18N.statusModified, UNVERIFIED: I18N.statusUnverified};

// Raw pipeline stage identifiers from GraphQL's `pendingFiles.items[].stages`
// (tasks.STAGES' own names: 'identify', 'organize', 'verify', 'compress') -
// humanized for display rather than shown as-is.
const PENDING_STAGE_LABEL = {identify: I18N.pendingStageIdentify, organize: I18N.pendingStageOrganize,
                             verify: I18N.pendingStageVerify, compress: I18N.pendingStageCompress,
                             decompress: I18N.pendingStageDecompress, combine: I18N.pendingStageCombine,
                             split: I18N.pendingStageSplit};
const humanizeStage = stage => PENDING_STAGE_LABEL[stage] || stage;

function humanizeStatus(status) {
    return STATUS_LABEL[status] || humanize(status);
}

function pill(tone, text) {
    const node = el('span', {className: 'files-pill', textContent: text});
    node.dataset.tone = tone;
    return node;
}

function statusPill(status) {
    return pill(STATUS_TONE[status] || 'secondary', humanizeStatus(status));
}

function fileTitles(r) {
    return [...new Map((r.apps || []).map(a => [a.titleId, a])).values()];
}

function titleName(r) {
    return fileTitles(r).map(a => (a.title && a.title.name) || a.titleId).join(', ');
}

// Prefer the human string a game's own Control NCA reports (e.g. "1.2.1"); fall
// back to the raw Nintendo counter for a content not yet (re-)identified since this
// was added, or a DLC, which never carries one. Matches upstream's own fallback.
function version(a) {
    return a.displayVersion || `v${a.appVersion}`;
}

function avatar(apps, size) {
    const placeholder = el('div', {className: `files-avatar files-avatar-none ${size || ''}`},
                           el('i', {className: `bi ${apps && apps.length ? 'bi-controller' : 'bi-question-lg'}`}));
    const a = (apps || []).find(x => x.title && x.title.iconUrl);
    if (!a) return placeholder;
    const img = el('img', {className: `files-avatar ${size || ''}`, src: a.title.iconUrl, alt: '', loading: 'lazy'});
    img.addEventListener('error', () => img.replaceWith(placeholder));
    return img;
}

const APP_TYPES = {BASE: I18N.appTypeBase, UPDATE: I18N.appTypeUpdate, DLC: I18N.appTypeDlc};

function contentText(r) {
    if (!r.apps || !r.apps.length) return '';
    return r.multicontent ? I18N.bundleLabelTemplate.replace('{list}', r.apps.map(contentLabel).join(', '))
                         : contentLabel(r.apps[0]);
}

function contentLabel(a) {
    return [APP_TYPES[a.appType], version(a)].filter(Boolean).join(' ');
}

/** The Content column: the type as a chip in its fixed color, the version(s) as plain
 *  text beside it - a multi-content file leads with the gold Multi chip. The plain
 *  text still goes in the title, so the tooltip keeps the full list. */
function contentChips(r) {
    if (!r.apps || !r.apps.length) return null;
    const wrap = el('div', {className: 'files-row-content', title: contentText(r)});
    if (r.multicontent) {
        wrap.append(chip(I18N.filterContentBundle, 'multi'),
                    el('span', {textContent: ` ${r.apps.map(contentLabel).join(', ')}`}));
        return wrap;
    }
    const a = r.apps[0];
    wrap.append(chip(APP_TYPES[a.appType] || a.appType, (a.appType || '').toLowerCase()));
    const v = version(a);
    if (v) wrap.append(el('span', {textContent: ` ${v}`}));
    return wrap;
}

const IDENTIFIED = {cnmt: ['files-fg-success', I18N.identifiedCnmtTooltip],
                    nup: ['files-fg-success', I18N.identifiedNupTooltip],
                    filename: ['files-fg-warning', I18N.identifiedFilenameTooltip]};

function stateIcons(r) {
    const icon = (name, tone, tip) => el('i', {className: `bi ${name} ${tone}`, title: tip});
    const [idTone, idTip] = IDENTIFIED[r.identificationType] || ['files-fg-danger', I18N.notIdentifiedTooltip];
    const status = r.verificationStatus;
    const shield = status === 'UNVERIFIED' ? ['bi-shield', 'files-off']
        : [BROKEN.includes(status) ? 'bi-shield-exclamation' : 'bi-shield-check', `files-fg-${STATUS_TONE[status]}`];
    return el('span', {className: 'files-state'},
        icon('bi-tag-fill', idTone, idTip),
        icon(shield[0], shield[1], I18N.verificationTooltipTemplate.replace('{status}', humanizeStatus(status))),
        icon('bi-file-earmark-zip', r.compressed ? 'files-fg-primary' : 'files-off',
             r.compressed ? I18N.compressedTooltip : I18N.notCompressedTooltip),
        icon(r.organized ? 'bi-folder-check' : 'bi-folder', r.organized ? 'files-fg-primary' : 'files-off',
             r.organized ? I18N.organizedTooltip : I18N.notOrganizedTooltip));
}

let options = {extension: [], status: [], library: []};
const YES_NO = [['true', I18N.yes], ['false', I18N.no]];

const FILTERS = {
    content: {label: I18N.filterContentLabel,
              choices: () => [['BASE', I18N.appTypeBase], ['UPDATE', I18N.appTypeUpdate],
                              ['DLC', I18N.appTypeDlc], ['multi', I18N.filterContentBundle]],
              // FileContentKind's GraphQL enum names match these verbatim except
              // for the bundle case ('multi' here, MULTI on the wire).
              gql: v => ({content: v.map(x => x === 'multi' ? 'MULTI' : x)}),
              match: (r, v) => (r.apps || []).some(a => v.includes(a.appType)) || (v.includes('multi') && r.multicontent)},
    ext: {label: I18N.filterFormatLabel, choices: () => options.extension,
          gql: v => ({extension: {in: v}}), match: (r, v) => v.includes(r.extension)},
    status: {label: I18N.labelVerification, field: 'verificationStatus', choices: () => options.status,
             gql: v => ({verificationStatus: v}), match: (r, v) => v.includes(r.verificationStatus)},
    identifiedBy: {label: I18N.filterIdentifiedByLabel,
                   choices: () => [['cnmt', I18N.filterIdentifiedByCnmt], ['nup', I18N.filterIdentifiedByNup],
                                   ['filename', I18N.filterIdentifiedByFilename]],
                   gql: v => ({identificationType: {in: v}}), match: (r, v) => v.includes(r.identificationType)},
    compressed: {label: I18N.labelCompressed, single: true, choices: () => YES_NO,
                 gql: v => ({compressed: v[0] === 'true'}), match: (r, v) => String(r.compressed) === v[0]},
    organized: {label: I18N.labelOrganized, single: true, choices: () => YES_NO,
                gql: v => ({organized: v[0] === 'true'}), match: (r, v) => String(r.organized) === v[0]},
    library: {label: I18N.labelLibrary, choices: () => options.library.length > 1 ? options.library : [],
              gql: v => ({libraryId: {in: v.map(Number)}}), match: (r, v) => v.includes(String(r.libraryId))},
};

const TABS = {
    all: {kind: 'files', base: {}},
    unidentified: {kind: 'files', base: {identified: false},
                   detail: r => `${r.identificationError || I18N.noMatch} · ${r.identificationAttempts} ${I18N.attemptsSuffix}`},
    verification: {kind: 'files', base: {verificationStatus: VERIFICATION_ISSUES},
                   detail: r => r.verificationError
                       || (r.verificationStatus === 'UNVERIFIED' ? I18N.notVerifiedYet : humanizeStatus(r.verificationStatus))},
    duplicates: {kind: 'groups', field: 'duplicates'},
    outdated: {kind: 'groups', field: 'outdated'},
    pending: {kind: 'pending', detail: r => [
        r._files ? I18N.pendingFilesCount.replace('{count}', r._files.toLocaleString()) : null,
        ...(r._stages || []).map(humanizeStage),
    ].filter(Boolean).join(' · ')},
    // Files > Compress / Combine: their own panels (packing.js).
    compress: {kind: 'packing'},
    combine: {kind: 'packing'},
};
Object.values(TABS).forEach(t => Object.assign(t, {
    filters: {}, chips: [], search: '', page: 1, rows: null, skipped: new Set(),
    order: t.kind === 'files' ? {field: 'ADDED_AT', direction: 'DESC'} : null}));

let current = 'all';

function notice(text) {
    $('#filesNotice').text(text).toggleClass('d-none', !text);
}

// --- tasks started from this page ---
//
// Polled rather than followed on the realtime feed, same reasoning as the Tasks
// page's own polling: simple, and a queued action is always short-lived here.

const watched = new Map();  // task id -> {files: Set of file ids, text}
const WATCH_MS = 2000;
let watchTimer = null;

function busy(fileId) {
    for (const w of watched.values()) if (w.files.has(String(fileId))) return w.text;
    return null;
}

function paintBusy() {
    document.querySelectorAll('#filesBody [data-id]').forEach(node => {
        const text = busy(node.dataset.id);
        node.classList.toggle('files-busy', Boolean(text));
        if (text) node.title = text;
        node.querySelectorAll('button[data-action]').forEach(b => {
            b.disabled = Boolean(text) || b.dataset.blocked === '1';
        });
    });
}

function watch(task, fileIds, text) {
    if (!task) return;
    watched.set(task.id, {files: new Set(fileIds.map(String)), text: text});
    paintBusy();
    if (!watchTimer) watchTimer = setInterval(checkWatched, WATCH_MS);
}

async function checkWatched() {
    const ids = [...watched.keys()];
    if (!ids.length) { clearInterval(watchTimer); watchTimer = null; return; }
    let d;
    try {
        d = await gql(`query (${ids.map((_, i) => `$t${i}: ID!`).join(', ')}) {
            ${ids.map((_, i) => `t${i}: task(id: $t${i}) { status errorMessage }`).join(' ')} }`,
            Object.fromEntries(ids.map((id, i) => [`t${i}`, id])));
    } catch (e) { return; }
    const failures = [];
    ids.forEach((id, i) => {
        const t = d[`t${i}`];
        if (t && !['completed', 'failed'].includes(t.status)) return;
        if (t && t.status === 'failed') failures.push(I18N.taskFailedTemplate
            .replace('{text}', watched.get(id).text).replace('{error}', t.errorMessage || I18N.seeTasksPage));
        watched.delete(id);
    });
    if (ids.length === watched.size) return;
    markStale(current);
    loadStats();
    await loadTab(true);
    if (drawerId) openDrawer({id: drawerId});
    if (failures.length) notice(failures.join(' '));
}

async function act(mutation, f, text) {
    try {
        const d = await gql(`mutation ($id: ID!) { ${mutation}(fileId: $id) { id } }`, {id: f.id}, true);
        watch(d[mutation], [f.id], text);
    } catch (e) { notice(e.message); }
}

async function deleteOneCopy(file) {
    if (!confirm(I18N.confirmDeleteFileTemplate.replace('{name}', file.filename))) return false;
    try {
        await gql('mutation ($id: ID!) { deleteFileRecord(fileId: $id) }', {id: file.id}, true);
        notice('');
        markStale(current);
        loadStats();
        return true;
    } catch (e) { notice(e.message); return false; }
}

// "Clean DB": forgets the file's record, never the file on disk - Statistics' per-item
// clean, for one file. The next scan finds it again as new.
async function cleanOneFile(file) {
    if (!confirm(I18N.confirmCleanDbTemplate.replace('{name}', file.filename))) return false;
    try {
        await gql('mutation ($id: ID!) { cleanFileRecord(fileId: $id) }', {id: file.id}, true);
        notice('');
        markStale(current);
        loadStats();
        return true;
    } catch (e) { notice(e.message); return false; }
}

// Offered whatever the settings say: an action asked for by hand runs even with
// the matching automatic step off. `blocked` explains an action that cannot run.
const ACTIONS = {
    retry: {icon: 'bi-arrow-repeat', title: I18N.actionRetryTitle, run: f => act('retryIdentification', f, I18N.busyIdentifying)},
    verify: {icon: 'bi-shield-check', title: I18N.actionVerifyTitle, run: f => act('verifyFile', f, I18N.busyVerifying),
             applies: f => VERIFY_EXT.includes(f.extension),
             blocked: () => !KEYS_VALID && I18N.verifyBlockedNeedsKeys},
    compress: {icon: 'bi-file-earmark-zip', title: I18N.actionCompressTitle, run: f => act('compressFile', f, I18N.busyCompressing),
               applies: f => !f.compressed && COMPRESS_EXT.includes(f.extension)},
    decompress: {icon: 'bi-file-earmark-arrow-up', title: I18N.actionDecompressTitle, run: f => act('decompressFile', f, I18N.busyDecompressing),
                 applies: f => f.compressed},
    cleanDb: {icon: 'bi-database-x', title: I18N.actionCleanDbTitle,
              run: f => cleanOneFile(f).then(ok => { if (ok) loadTab(true); })},
    delete: {icon: 'bi-trash', title: I18N.actionDeleteTitle, danger: true,
             run: f => deleteOneCopy(f).then(ok => { if (ok) loadTab(true); })},
};

// A collaborator (<html data-readonly>) looks and changes nothing: no actions at all.
const READ_ONLY = document.documentElement.hasAttribute('data-readonly');

function actionButtons(f, className, label) {
    if (READ_ONLY) return [];
    return Object.entries(ACTIONS).filter(([, a]) => !a.applies || a.applies(f)).map(([name, a]) => {
        const blocked = a.blocked && a.blocked();
        const b = el('button', {type: 'button', className: className + (a.danger ? ' files-fg-danger' : ''),
                                title: blocked || '', disabled: Boolean(blocked)},
                     el('i', {className: `bi ${a.icon} ${label ? 'me-2' : ''}`}), label ? a.title : null);
        b.dataset.action = name;
        if (blocked) b.dataset.blocked = '1';
        if (!label) b.title = blocked || a.title;
        b.addEventListener('click', e => { e.stopPropagation(); a.run(f); });
        return b;
    });
}

function rowMenu(f) {
    if (READ_ONLY) return el('span');
    const toggle = el('button', {type: 'button', className: 'icon-btn px-1', title: I18N.actionsMenuTitle},
                      el('i', {className: 'bi bi-three-dots'}));
    toggle.dataset.bsToggle = 'dropdown';
    toggle.dataset.bsPopperConfig = '{"strategy": "fixed"}';
    const menu = el('div', {className: 'dropdown'}, toggle,
                    el('div', {className: 'dropdown-menu dropdown-menu-end'}, actionButtons(f, 'dropdown-item', true)));
    menu.addEventListener('click', e => e.stopPropagation());
    return menu;
}

// --- cleanup groups (duplicates, outdated updates) ---
//
// Both tabs are normalized to the same {app, keep: [file], remove: [{reason, file}]}
// shape so they share one renderer. `duplicates` comes from `duplicateFileGroups`
// (recommendedKeepId null means the tie is undecided - nothing is pre-selected for
// removal then, same as the Stats page's own duplicate review); `outdated` comes
// from `outdatedUpdateGroups` (always unambiguous: the newest owned version is kept).

// A losing copy's reason, as (the attribute it lost on, so that cell can be
// highlighted - or null when nothing specific decided it; the label shown next to
// its Delete pill). "Worse verification"/"Smaller copy"/etc - never a reason
// based on *when* a copy was added, since this fork's own automatic resolution
// (unlike upstream's) never compares timestamps, see duplicateDecides() below.
const REASONS = {
    VERIFICATION: ['verification', I18N.reasonVerification],
    COMPRESSED: ['compressed', I18N.reasonCompressed],
    SIZE: ['size', I18N.reasonSize],
    DUPLICATE: [null, I18N.reasonDuplicate],
    OLDER_VERSION: ['version', I18N.reasonOlderVersion],
};

/** Why `file` lost to `keepFile` in a decided duplicates group, mirroring
 *  library.py's duplicate_winner_with_preferences(): rank first (Valid > Repack >
 *  Corrupt), then the compression preference if one is set and it actually
 *  distinguishes the two, then size if "prefer larger on tie" is on. Falls back to
 *  the generic DUPLICATE reason when none of those individually explain it (e.g.
 *  the two preferences combined to decide it) rather than guessing. */
function duplicateDecides(file, keepFile) {
    const rank = DUPLICATE_RANK[file.verificationStatus], keepRank = DUPLICATE_RANK[keepFile.verificationStatus];
    if (rank !== keepRank) return 'VERIFICATION';
    if (COMPRESSION_PREFERENCE !== 'none') {
        const wantCompressed = COMPRESSION_PREFERENCE === 'compressed';
        if (Boolean(keepFile.compressed) === wantCompressed && Boolean(file.compressed) !== wantCompressed) return 'COMPRESSED';
    }
    if (PREFER_LARGER_ON_TIE && (file.size || 0) < (keepFile.size || 0)) return 'SIZE';
    return 'DUPLICATE';
}

function normalizeDuplicateGroup(g) {
    // A NUP pair and an NSP pair of the same app are separate groups: the files say which.
    const key = `${g.appId}:${g.appType}:${g.files.map(f => f.id).join(',')}`;
    const keepFile = g.recommendedKeepId ? g.files.find(f => String(f.id) === String(g.recommendedKeepId)) : null;
    const keep = keepFile ? [keepFile] : [];
    const remove = g.files.filter(f => String(f.id) !== String(g.recommendedKeepId))
        .map(file => ({reason: keepFile ? duplicateDecides(file, keepFile) : null, file}));
    return {key, kind: 'duplicates', decided: Boolean(keepFile), app: {titleId: g.titleId, appType: g.appType,
            label: g.appName || g.titleName || g.titleId, versionLabel: ''}, keep, remove};
}

function normalizeOutdatedGroup(g) {
    return {key: g.titleId, kind: 'outdated', decided: true,
            app: {titleId: g.titleId, appType: 'UPDATE', label: g.titleName || g.titleId,
                  versionLabel: `v${g.newestVersion}`},
            keep: g.keepFiles, remove: g.remove.map(r => ({reason: 'OLDER_VERSION', file: r.file, version: r.version}))};
}

function groupFiles(g) {
    return [...g.keep.map(f => ({file: f, keep: true})), ...g.remove.map(r => ({file: r.file, reason: r.reason}))];
}

function visibleGroups(tab) {
    return (tab.rows || []).filter(g => groupFiles(g).some(c => matches(c.file, tab)));
}

function removalSet() {
    const tab = TABS[current];
    const files = new Map();
    if (tab.kind !== 'groups') return files;
    visibleGroups(tab).filter(g => !tab.skipped.has(g.key)).forEach(g => g.remove.forEach(r => files.set(r.file.id, r.file)));
    return files;
}

async function runRemoval() {
    const tab = TABS[current];
    const files = removalSet();
    const size = [...files.values()].reduce((sum, f) => sum + (f.size || 0), 0);
    if (!files.size || !confirm(I18N.confirmBulkDeleteTemplate.replace('{count}', files.size).replace('{size}', formatBytes(size)))) return;
    let failed = 0;
    for (const f of files.values()) {
        try { await gql('mutation ($id: ID!) { deleteFileRecord(fileId: $id) }', {id: f.id}, true); }
        catch (e) { failed++; }
    }
    notice(failed ? I18N.bulkDeleteFailedTemplate.replace('{count}', failed) : '');
    tab.rows = null;
    markStale(current);
    loadStats();
    loadTab(true);
}

/** The app entry a file carries for this group's own content - there can be more
 *  than one app on a bundle, so this picks the one that matches. */
function ownApp(file, g) {
    return (file.apps || []).find(a => a.titleId === g.app.titleId && a.appType === g.app.appType) || (file.apps || [])[0];
}

/** The rows of the comparison table: (key, label, cell, value compared). File and
 *  Size always show; the rest only where the copies differ, or where a copy lost
 *  on them - same rule upstream's own duplicates view uses, ported as-is. */
function attributes(g, copies) {
    return [
        ['file', I18N.attrFile, c => el('span', {className: 'files-cmp-name'}, c.file.folder ? muted(c.file.folder + '/') : null, c.file.filename), c => c.file.id],
        ['version', I18N.attrVersion, c => {
            const v = c.version != null ? c.version : (ownApp(c.file, g) && ownApp(c.file, g).appVersion);
            return v != null ? `v${v}` : '';
        }, c => c.version != null ? c.version : (ownApp(c.file, g) && ownApp(c.file, g).appVersion)],
        ['verification', I18N.labelVerification, c => statusPill(c.file.verificationStatus), c => c.file.verificationStatus],
        ['compressed', I18N.labelCompressed, c => yesNo(c.file.compressed), c => c.file.compressed],
        ['organized', I18N.labelOrganized, c => yesNo(c.file.organized), c => c.file.organized],
        ['added', I18N.labelAdded, c => when(parseDate(c.file.addedAt, true)), c => c.file.addedAt],
        ['size', I18N.labelSize, c => formatBytes(c.file.size), c => c.file.size],
    ];
}

/** One file's column header: a Keep/Delete/"?" pill, the reason it lost (if any),
 *  a manual "Keep this copy" override on anything not already recommended, a
 *  direct Delete, and the same per-file actions (verify/compress/retry/…) the
 *  "All files" table offers, tucked behind the same "…" menu. */
function copyHeader(c, g, tab) {
    const recommended = Boolean(c.keep);
    const pillNode = recommended ? pill('success', I18N.pillKeep) : (g.decided ? pill('danger', I18N.pillDelete) : pill('secondary', I18N.pillUndecided));
    const reasonText = !recommended && c.reason ? REASONS[c.reason][1] : null;
    const keepBtn = recommended ? null : el('button', {type: 'button',
        className: 'btn btn-sm btn-outline-success', textContent: I18N.keepThisCopyButton});
    if (keepBtn) keepBtn.addEventListener('click', async () => {
        if (!confirm(I18N.keepThisCopyConfirmTemplate.replace('{name}', c.file.filename))) return;
        try {
            await gql('mutation ($id: ID!) { resolveDuplicateFiles(keepFileId: $id) }', {id: c.file.id}, true);
            notice('');
            tab.rows = null;
            loadStats();
            loadTab(true);
        } catch (e) { notice(e.message); }
    });
    const delBtn = el('button', {type: 'button', className: 'btn btn-sm btn-outline-danger',
                                 textContent: I18N.copyDeleteButton});
    delBtn.addEventListener('click', () => deleteOneCopy(c.file).then(ok => { if (ok) { tab.rows = null; loadTab(true); } }));
    const blockedBy = busy(c.file.id);
    if (blockedBy) { delBtn.disabled = true; if (keepBtn) keepBtn.disabled = true; }
    const th = el('th', {scope: 'col'}, el('div', {className: 'd-flex flex-column gap-1'},
        el('div', {className: 'd-flex align-items-center gap-2'}, pillNode, reasonText ? muted(reasonText) : null,
            el('span', {className: 'ms-auto'}, rowMenu(c.file))),
        el('div', {className: 'd-flex gap-2 admin-write'}, keepBtn, delBtn)));
    th.dataset.id = c.file.id;
    return th;
}

function groupBlock(g, tab) {
    const copies = groupFiles(g);
    const on = !tab.skipped.has(g.key);
    const free = g.remove.reduce((sum, r) => sum + (r.file.size || 0), 0);
    const toggle = el('input', {type: 'checkbox', className: 'form-check-input', role: 'switch', checked: on,
                                disabled: !g.decided,
                                title: !g.decided ? I18N.toggleUndecidedTitle
                                    : on ? I18N.toggleDeleteGroupTitle : I18N.toggleKeepGroupTitle});
    toggle.addEventListener('change', () => {
        if (toggle.checked) tab.skipped.delete(g.key); else tab.skipped.add(g.key);
        renderBody();
    });
    const head = el('div', {className: 'files-cmp-head'}, avatar(copies[0] ? copies[0].file.apps : [], 'sm'),
        el('b', {textContent: g.app.label}),
        chip(APP_TYPES[g.app.appType] || g.app.appType, (g.app.appType || '').toLowerCase()),
        g.app.versionLabel ? muted(g.app.versionLabel) : null,
        el('span', {className: 'files-cmp-free', textContent: I18N.freeTemplate.replace('{size}', formatBytes(free))}),
        el('div', {className: 'form-check form-switch m-0'}, toggle));
    const columns = copies.map(c => copyHeader(c, g, tab));
    // Which cell (if any) explains a copy's own removal - only that cell gets the
    // amber highlight, same as upstream.
    const decides = copies.map(c => c.reason && REASONS[c.reason][0]);
    const rows = attributes(g, copies).filter(([key, , , value]) => ['file', 'size'].includes(key)
        || new Set(copies.map(c => String(value(c)))).size > 1 || decides.includes(key))
        .map(([key, label, cell]) => el('tr', null, el('th', {scope: 'row', textContent: label}),
            copies.map((c, i) => {
                const td = el('td', {className: decides[i] === key ? 'files-decides' : ''}, cell(c));
                td.dataset.id = c.file.id;
                if (key === 'file') td.addEventListener('click', () => openDrawer(c.file));
                return td;
            })));
    return el('section', {className: on ? '' : 'files-cmp-off'}, head,
        el('div', {className: 'table-responsive'}, el('table', {className: 'files-cmp'},
            el('thead', null, el('tr', null, el('th', {scope: 'col'}), columns)), el('tbody', null, rows))));
}

// --- loading ---

async function loadOptions() {
    const d = await gql(`{ stats { filesByExtension { key } filesByVerificationStatus { status } } libraries { id path } }`);
    options = {
        extension: d.stats.filesByExtension.filter(b => b.key).map(b => [b.key, b.key]),
        status: d.stats.filesByVerificationStatus.map(b => [b.status, humanizeStatus(b.status)]),
        library: d.libraries.map(l => [String(l.id), l.path]),
    };
}

// --- tiles ---
//
// The cheap figures come with the table; duplicates/outdated/pending each need
// their own round trip, so their tiles wait for it rather than blocking the rest.

const CHEAP_STATS = `{ stats { totalFiles totalSize unidentifiedFiles filesByVerificationStatus { status count } } }`;
let stats = {};
let groupStats = {duplicates: null, outdated: null, pending: null};

/** The copies a group would drop: with a recommendation, everything but it; without one
 *  (a tie at the best verification rank, or nothing clean enough to auto-pick yet -
 *  the list below still shows the group for a person to resolve), conservatively
 *  everything but the single largest copy, whichever one ends up kept. */
function duplicateLosers(g) {
    if (g.recommendedKeepId) {
        return g.files.filter(f => String(f.id) !== String(g.recommendedKeepId));
    }
    let largest = null;
    g.files.forEach(f => {
        if (!largest || (f.size || 0) > (largest.size || 0)) largest = f;
    });
    return g.files.filter(f => f !== largest);
}

function duplicateFree(g) {
    return duplicateLosers(g).reduce((sum, f) => sum + (f.size || 0), 0);
}

const TILES = {
    all: s => s.totalFiles != null && [s.totalFiles, formatBytes(s.totalSize)],
    unidentified: s => s.unidentifiedFiles != null && [s.unidentifiedFiles, I18N.tileUnknownContent, 'warning'],
    verification: s => {
        if (!s.filesByVerificationStatus) return null;
        const issues = s.filesByVerificationStatus.filter(b => VERIFICATION_ISSUES.includes(b.status) && b.count);
        return [issues.reduce((n, b) => n + b.count, 0),
                issues.map(b => `${b.count} ${humanizeStatus(b.status).toLowerCase()}`).join(' · ') || I18N.tileAllVerified,
                issues.some(b => BROKEN.includes(b.status)) ? 'danger' : 'warning'];
    },
    duplicates: () => groupStats.duplicates && [groupStats.duplicates.files, I18N.freeTemplate.replace('{size}', formatBytes(groupStats.duplicates.size)), 'warning'],
    outdated: () => groupStats.outdated && [groupStats.outdated.files, I18N.freeTemplate.replace('{size}', formatBytes(groupStats.outdated.size)), 'warning'],
    pending: () => groupStats.pending != null && [groupStats.pending, I18N.tileProcessingDue, 'info'],
    compress: () => Packing.figures('compress'),
    combine: () => Packing.figures('combine'),
};

function paintTiles() {
    document.querySelectorAll('.files-tile').forEach(tile => {
        const key = tile.dataset.tile;
        // The tile in use: outlined in its own color with a check, as in the Library.
        tile.classList.toggle('active', key === current);
        tile.classList.toggle('is-active', key === current);
        const figures = TILES[key](stats);
        if (!figures) return;
        const [count, sub, tone] = figures;
        const alert = tone && count > 0;
        tile.querySelector('.files-tile-count').textContent = count.toLocaleString();
        tile.classList.toggle('ok', Boolean(tone) && !count);
        tile.querySelector('.files-tile-sub').textContent = sub;
        const dot = tile.querySelector('.files-tile-dot');
        dot.classList.toggle('d-none', !alert);
        dot.style.background = alert ? `var(--files-${tone})` : '';
        tile.dataset.tone = alert ? tone : '';
    });
}

function loadStats() {
    gql(CHEAP_STATS).then(d => { stats = {...stats, ...d.stats}; paintTiles(); }).catch(e => notice(e.message));
    gql('{ duplicateFileGroups { recommendedKeepId files { id size } } }').then(d => {
        // One file counts once, however many groups it loses in: a multi-content file
        // sits beside the game's base, its update and each DLC, and dropping it frees
        // its size a single time (the bulk-delete path already worked this way).
        const doomed = new Map();
        d.duplicateFileGroups.forEach(g => duplicateLosers(g).forEach(f => doomed.set(String(f.id), f.size || 0)));
        groupStats.duplicates = {files: doomed.size,
                                 size: [...doomed.values()].reduce((n, s) => n + s, 0)};
        paintTiles();
    }).catch(() => {});
    gql('{ outdatedUpdateGroups { remove { file { size } } } }').then(d => {
        const groups = d.outdatedUpdateGroups;
        const all = groups.flatMap(g => g.remove);
        groupStats.outdated = {files: all.length, size: all.reduce((n, r) => n + (r.file.size || 0), 0)};
        paintTiles();
    }).catch(() => {});
    gql('{ pendingFiles { total } }').then(d => {
        groupStats.pending = d.pendingFiles.total;
        paintTiles();
    }).catch(() => {});
    ['compress', 'combine'].forEach(kind => Packing.load(kind, true).then(() => {
        paintTiles();
        if (current === kind) Packing.render(kind);
    }).catch(() => {}));
}

// --- filters ---

function serverFilter(tab) {
    const filter = {...tab.base};
    Object.entries(tab.filters).forEach(([key, v]) => {
        if (!FILTERS[key].gql) return;
        Object.entries(FILTERS[key].gql(v)).forEach(([field, clause]) => {
            filter[field] = Array.isArray(filter[field]) ? filter[field].filter(x => clause.includes(x)) : clause;
        });
    });
    if (tab.search) filter.filename = {contains: tab.search};
    return filter;
}

function matches(r, tab) {
    if (tab.search && !(r.filename || '').toLowerCase().includes(tab.search.toLowerCase())) return false;
    return Object.entries(tab.filters).every(([key, v]) => !FILTERS[key].match || FILTERS[key].match(r, v));
}

function choicesFor(key) {
    const limit = FILTERS[key].field && (TABS[current].base || {})[FILTERS[key].field];
    return FILTERS[key].choices().filter(([v]) => !limit || limit.includes(v));
}

function setFilter(key, value) {
    const tab = TABS[current];
    if (!value.length) delete tab.filters[key];
    else tab.filters[key] = value;
    tab.page = 1;
    if (tab.kind === 'files') loadTab(true); else renderBody();
}

function filterChip(key) {
    const tab = TABS[current];
    const F = FILTERS[key];
    const chosen = new Set(tab.filters[key] || []);
    const choices = choicesFor(key);
    const toggle = el('button', {type: 'button'});
    toggle.dataset.bsToggle = 'dropdown';
    toggle.dataset.bsAutoClose = 'outside';
    const paint = () => {
        const names = choices.filter(([v]) => chosen.has(v)).map(([, text]) => text);
        toggle.replaceChildren(`${F.label}: `, el('b', {textContent: names.join(', ') || I18N.filterAny}));
    };
    const menu = el('div', {className: 'dropdown-menu'}, choices.map(([v, text]) => {
        const box = el('input', {type: F.single ? 'radio' : 'checkbox', name: `filesFilter-${key}`,
                                 className: 'form-check-input me-2', checked: chosen.has(v)});
        box.addEventListener('change', () => {
            if (F.single) chosen.clear();
            if (box.checked) chosen.add(v); else chosen.delete(v);
            paint();
            setFilter(key, [...chosen]);
        });
        return el('label', {className: 'dropdown-item'}, box, text);
    }));
    const remove = el('button', {type: 'button', title: I18N.removeFilterTitle}, el('i', {className: 'bi bi-x'}));
    remove.addEventListener('click', () => {
        tab.chips = tab.chips.filter(k => k !== key);
        renderChips();
        setFilter(key, []);
    });
    paint();
    const node = el('div', {className: 'dropdown files-filter-chip'}, toggle, menu, remove);
    node.dataset.key = key;
    return node;
}

function renderChips() {
    const tab = TABS[current];
    document.getElementById('filesChips').replaceChildren(...tab.chips.map(filterChip));
    const free = Object.keys(FILTERS).filter(k => !tab.chips.includes(k) && choicesFor(k).length);
    document.getElementById('filesAddMenu').replaceChildren(...free.map(key => {
        const item = el('button', {type: 'button', className: 'dropdown-item', textContent: FILTERS[key].label});
        item.addEventListener('click', () => {
            tab.chips.push(key);
            renderChips();
            const toggle = document.querySelector(`.files-filter-chip[data-key="${key}"] [data-bs-toggle]`);
            setTimeout(() => bootstrap.Dropdown.getOrCreateInstance(toggle).show());
        });
        return item;
    }));
    $('#filesAddFilter').prop('disabled', !free.length);
    $('#filesSearch').val(tab.search);
}

// --- rows ---

async function fetchRows(tab) {
    if (tab.kind === 'groups') {
        if (tab.field === 'duplicates') {
            const d = await gql(`{ duplicateFileGroups { titleId titleName appId appType appName recommendedKeepId
                files { ...F } } } ${FILE_FIELDS}`);
            return d.duplicateFileGroups.map(normalizeDuplicateGroup);
        }
        const d = await gql(`{ outdatedUpdateGroups { titleId titleName newestVersion
            keepFiles { ...F } remove { version file { ...F } } } } ${FILE_FIELDS}`);
        return d.outdatedUpdateGroups.map(normalizeOutdatedGroup);
    }
    if (tab.kind === 'pending') {
        const d = await gql(`{ pendingFiles { total items { stages file { ...F } } } } ${FILE_FIELDS}`);
        tab.total = d.pendingFiles.total;
        return groupPendingByGame(d.pendingFiles.items.map(p => ({...p.file, _stages: p.stages})));
    }
    const d = await gql(`query ($filter: FileFilter, $orderBy: OrderBy, $page: Int!, $pageSize: Int!) {
        files(filter: $filter, orderBy: $orderBy, page: $page, pageSize: $pageSize) {
            total items { ...F } } } ${FILE_FIELDS}`,
        {filter: serverFilter(tab), orderBy: tab.order, page: tab.page, pageSize});
    tab.total = d.files.total;
    return d.files.items;
}

function visibleRows() {
    const tab = TABS[current];
    if (tab.kind === 'files' || tab.kind === 'pending') return tab.rows || [];
    return tab.rows || [];
}

async function loadTab(force) {
    const tab = TABS[current];
    if (tab.kind === 'packing') {
        const kind = current;
        renderBody();
        try {
            await Packing.load(kind, force || packingStale[kind]);
            packingStale[kind] = false;
            notice('');
        } catch (e) { notice(e.message); }
        if (current === kind) { Packing.render(kind); paintTiles(); }
        return;
    }
    renderBody();
    // Pending never serves cached rows: entering the tab shows what runs right now
    // (asked for - a queued combine used to wait for a page reload to appear).
    if (tab.rows && !force && tab.kind !== 'pending') return;
    lastLoaded = Date.now();
    try {
        tab.rows = await fetchRows(tab);
        if (tab.kind === 'groups') tab.rows.forEach(g => { if (!g.decided) tab.skipped.add(g.key); });
        notice('');
    } catch (e) {
        notice(e.message);
    }
    renderBody();
}

const COLUMNS = [[I18N.columnTitle, 'TITLE'], [I18N.columnState, null, 'files-wide'], [I18N.labelSize, 'SIZE', 'text-end'],
                 [I18N.labelAdded, 'ADDED_AT', 'text-end files-wide'], ['']];

function renderHead() {
    const tab = TABS[current];
    document.querySelector('#filesTable thead').replaceChildren(el('tr', null, COLUMNS.map(([label, sort, cls]) => {
        const sorting = tab.kind === 'files' && sort && sort !== 'TITLE';
        const active = sorting && tab.order && tab.order.field === sort;
        const th = el('th', {className: cls || ''}, label,
                      active ? [' ', el('i', {className: `bi bi-caret-${tab.order.direction === 'ASC' ? 'up' : 'down'}-fill`})] : null);
        if (sorting) {
            th.classList.add('files-sortable');
            th.addEventListener('click', () => {
                tab.order = {field: sort, direction: active && tab.order.direction === 'ASC' ? 'DESC' : 'ASC'};
                tab.page = 1;
                renderHead();
                loadTab(true);
            });
        }
        return th;
    })));
}

// --- Pending: a progress bar per file, from the task working on it ---

let pendingTasks = {};      // file id -> {status, pct}
let pendingTitles = {};     // game id -> {status, pct}: a Combine names the game, not a file
let pendingTimer = null;
let pendingReloaded = 0;    // when the list was last asked again (see pollPending)

/** The files of one game pending together fold into a single row: compressing or
 *  combining a whole game used to list its base, update and DLC each with a bar of
 *  its own. The folded row keeps every file id, so its bar is the game's progress as
 *  a whole; a game with one file pending, or a file on its own, stays a plain row. */
function groupPendingByGame(rows) {
    const byTitle = new Map();
    rows.forEach(r => {
        const titleId = r.apps && r.apps[0] && r.apps[0].titleId;
        if (!titleId) return;
        if (!byTitle.has(titleId)) byTitle.set(titleId, []);
        byTitle.get(titleId).push(r);
    });
    const drop = new Set();
    byTitle.forEach(group => {
        if (group.length < 2) return;
        const first = group[0];
        first._ids = group.map(f => String(f.id));
        first._stages = [...new Set(group.flatMap(f => f._stages || []))];
        first._files = group.length;
        first.size = group.reduce((n, f) => n + (f.size || 0), 0);
        group.slice(1).forEach(f => drop.add(f));
    });
    return rows.filter(r => !drop.has(r));
}

/** The bar of a pending file: its task's progress while it runs, "Queued" while it waits
 *  in line, "Waiting" when no task has it yet. Filled in place by pollPending(). */
function progressBar(fileId, apps, ids) {
    const bar = el('div', {className: 'files-progress'},
        el('div', {className: 'files-progress__track'}, el('span', {className: 'files-progress__fill'})),
        el('span', {className: 'files-progress__label'}));
    bar.dataset.progressId = String(fileId);
    if (ids && ids.length) bar.dataset.progressIds = ids.join(',');
    const titleId = apps && apps[0] && apps[0].titleId;
    if (titleId) bar.dataset.progressTitle = String(titleId).toUpperCase();
    paintProgress(bar);
    return bar;
}

function paintProgress(bar) {
    const clamp = n => Math.max(0, Math.min(100, n || 0));
    let t = pendingTasks[bar.dataset.progressId] || pendingTitles[bar.dataset.progressTitle];
    let running = t && t.status === 'RUNNING';
    let pct = running ? clamp(t.pct) : 0;
    const ids = (bar.dataset.progressIds || '').split(',').filter(Boolean);
    if (ids.length) {
        // A folded game row: a combine's own task (keyed by title) drives it whole;
        // otherwise its share is the mean of its files' tasks, a file without one yet
        // counting as zero - one bar for the game, not one per content.
        const titleTask = pendingTitles[bar.dataset.progressTitle];
        if (titleTask) {
            t = titleTask;
            running = t.status === 'RUNNING';
            pct = running ? clamp(t.pct) : 0;
        } else {
            const tasks = ids.map(id => pendingTasks[id]).filter(Boolean);
            running = tasks.some(x => x.status === 'RUNNING');
            pct = running ? Math.round(ids.reduce((n, id) => {
                const x = pendingTasks[id];
                return n + (x && x.status === 'RUNNING' ? clamp(x.pct) : 0);
            }, 0) / ids.length) : 0;
            t = tasks[0];
        }
    }
    bar.classList.toggle('is-running', Boolean(running));
    bar.classList.toggle('is-queued', Boolean(t && !running));
    bar.querySelector('.files-progress__fill').style.width = pct + '%';
    bar.querySelector('.files-progress__label').textContent = running
        ? I18N.progressRunning.replace('{pct}', pct) : t ? I18N.progressQueued : I18N.progressWaiting;
}

/** Every 2 s while Pending is open: which of its files a task holds, and how far along.
 *  A task that has just finished takes its file off the list (the rows are asked again). */
async function pollPending() {
    if (current !== 'pending') return stopPending();
    let tasks;
    try {
        const d = await gql(`{ running: tasks(status: RUNNING, includeChildren: true, limit: 500) { status completionPct input }
                              queued: tasks(status: PENDING, includeChildren: true, limit: 500) { status completionPct input } }`);
        tasks = d.running.concat(d.queued);
    } catch (e) { return; }
    const next = {};
    const nextTitles = {};
    const keep = (map, key, t) => {
        if (!map[key] || t.status === 'RUNNING') map[key] = {status: t.status, pct: t.completionPct};
    };
    tasks.forEach(t => {
        let input = {};
        try { input = JSON.parse(t.input || '{}'); } catch (e) { /* not a file task */ }
        if (input.file_id != null) keep(next, String(input.file_id), t);
        else if (input.title_id) keep(nextTitles, String(input.title_id).toUpperCase(), t);
    });
    const done = (before, after) => Object.keys(before).some(k => before[k].status === 'RUNNING' && !after[k]);
    const finished = done(pendingTasks, next) || done(pendingTitles, nextTitles);
    // Anything new in flight (a compress queued elsewhere, a combine picked here) or
    // gone: the list follows it, not just the finished ones - asked for, it used to
    // sit stale until a page reload. Same-key sets mean nothing moved.
    const sameKeys = (a, b) => Object.keys(a).length === Object.keys(b).length
        && Object.keys(a).every(k => b[k]);
    const changed = finished || !sameKeys(pendingTasks, next) || !sameKeys(pendingTitles, nextTitles);
    pendingTasks = next;
    pendingTitles = nextTitles;
    document.querySelectorAll('.files-progress[data-progress-id]').forEach(paintProgress);
    // Asked again at most every 5 s: the list is the page's heaviest request, and a
    // big scan ends a task every second.
    if (changed && current === 'pending' && Date.now() - pendingReloaded > 5000) {
        pendingReloaded = Date.now();
        await loadTab(true);
        renderBody();
    }
}

function startPending() {
    if (!pendingTimer) pendingTimer = setInterval(pollPending, 2000);
    pollPending();
}

function stopPending() {
    clearInterval(pendingTimer);
    pendingTimer = null;
}

function fileRow(r, tab) {
    const titled = r.apps && r.apps.length;
    // A folded game row (several pending files of one game) has no drawer, chips or
    // per-file state of its own: it is the game, its files are the bar.
    const folded = Boolean(r._ids);
    const sub = tab.detail ? tab.detail(r) : titled ? r.filename : null;
    const line = (className, text) => text ? el('div', {className: className, textContent: text, title: text}) : null;
    const tr = el('tr', {className: r.id === drawerId ? 'files-selected' : ''},
        el('td', null, el('div', {className: 'files-row'}, avatar(r.apps),
            el('div', {className: 'files-row-lines'},
                line('files-row-title', titled ? titleName(r) : r.filename),
                folded ? null : contentChips(r),
                line('files-row-sub', sub)),
            tab.kind === 'pending' ? progressBar(r.id, r.apps, r._ids) : null)),
        el('td', {className: 'files-wide'}, folded ? null : stateIcons(r)),
        el('td', {className: 'text-end files-num'}, formatBytes(r.size)),
        el('td', {className: 'text-end files-num text-secondary files-wide'}, when(parseDate(r.addedAt, true))),
        el('td', {className: 'text-end'}, folded ? null : rowMenu(r)));
    tr.dataset.id = r.id;
    if (!folded) tr.addEventListener('click', () => openDrawer(r));
    return tr;
}

function message(text) {
    return el('tr', null, el('td', {colSpan: COLUMNS.length, className: 'text-secondary fst-italic', textContent: text}));
}

const EMPTY = {unidentified: I18N.emptyUnidentified, verification: I18N.emptyVerification,
               duplicates: I18N.emptyDuplicates, outdated: I18N.emptyOutdated, pending: I18N.emptyPending};

function renderBody() {
    const tab = TABS[current];
    const packing = tab.kind === 'packing';
    $('#packingPanel').toggleClass('d-none', !packing);
    $('#filesMain').toggleClass('d-none', packing);
    if (packing) {
        $('#filesFlatToolbar').addClass('d-none');
        Packing.render(current);
        return;
    }
    const groups = tab.kind === 'groups';
    const filtered = Object.keys(tab.filters).length || tab.search;
    const empty = filtered ? I18N.emptyFiltered : EMPTY[current] || I18N.emptyNoFiles;
    $('#filesTable').toggleClass('d-none', groups);
    $('#filesFlatToolbar').toggleClass('d-none', groups);
    if (groups) {
        const shown = visibleGroups(tab);
        document.getElementById('filesGroups').replaceChildren(
            ...(tab.rows === null ? [muted(I18N.loading)] : shown.length ? shown.map(g => groupBlock(g, tab)) : [muted(empty)]));
    } else {
        document.getElementById('filesGroups').replaceChildren();
        const rows = visibleRows();
        document.querySelector('#filesTable tbody').replaceChildren(
            ...(tab.rows === null ? [message(I18N.loading)] : rows.length ? rows.map(r => fileRow(r, tab)) : [message(empty)]));
    }
    paintBusy();
    renderPager();
}

function renderPager() {
    const tab = TABS[current];
    let text = '';
    if (tab.rows !== null && tab.kind === 'files' && tab.total) {
        const first = (tab.page - 1) * pageSize + 1;
        text = I18N.pagerRangeTemplate.replace('{first}', first.toLocaleString())
            .replace('{last}', (first + tab.rows.length - 1).toLocaleString())
            .replace('{total}', tab.total.toLocaleString());
    } else if (tab.rows !== null && tab.kind === 'pending') {
        text = I18N.pagerPendingTemplate.replace('{shown}', visibleRows().length.toLocaleString())
            .replace('{total}', (tab.total || 0).toLocaleString());
    } else if (tab.rows !== null && tab.kind === 'groups') {
        const files = removalSet();
        const size = [...files.values()].reduce((sum, f) => sum + (f.size || 0), 0);
        text = I18N.pagerRemovalTemplate.replace('{count}', files.size.toLocaleString()).replace('{size}', formatBytes(size));
    }
    $('.files-count').text(text);
    const paged = tab.kind === 'files' && tab.rows !== null;
    $('.files-prev').toggleClass('d-none', !paged).prop('disabled', tab.page <= 1);
    $('.files-next').toggleClass('d-none', !paged).prop('disabled', tab.page * pageSize >= (tab.total || 0));
    // Below the list, the shared pager (the toolbar keeps its short arrows); the bottom
    // row keeps the duplicates' delete button where that applies.
    Pager.render(document.getElementById('filesPages'), {
        total: paged ? tab.total : 0, page: tab.page, perPage: pageSize, sizes: FILE_SIZES,
        onPage: p => {
            tab.page = p;
            document.querySelector('.files-toolbar').scrollIntoView({block: 'start'});
            loadTab(true);
        },
        onPerPage: n => {
            pageSize = n;
            Pager.savePerPage('files', n);
            tab.page = 1;
            loadTab(true);
        },
    });
    $('#filesPagerBottom').toggleClass('d-none', paged);
    const removals = removalSet();
    $('.files-delete').toggleClass('d-none', tab.kind !== 'groups').prop('disabled', !removals.size).find('span')
        .text(removals.size ? I18N.bulkDeleteButtonTemplate.replace('{count}', removals.size.toLocaleString()) : I18N.bulkDeleteButtonEmpty);
}

const DETAIL = `query ($id: ID!) { file(id: $id) { ...F mtime signatureValid hashValid hashModified
    library { path } } } ${FILE_FIELDS}`;
let drawerId = null;

async function openDrawer(f) {
    drawerId = f.id;
    document.querySelectorAll('#filesTable tbody tr').forEach(tr =>
        tr.classList.toggle('files-selected', tr.dataset.id === f.id));
    // The comparison table has no one row per file (columns are files, rows are
    // attributes), so every cell belonging to this file's column is marked instead.
    document.querySelectorAll('.files-cmp [data-id]').forEach(node =>
        node.classList.toggle('files-selected', node.dataset.id === String(f.id)));
    if (f.filename) renderDrawer(f);
    try {
        const d = await gql(DETAIL, {id: f.id});
        if (drawerId !== f.id) return;
        if (!d.file) return closeDrawer();
        renderDrawer(d.file);
    } catch (e) { notice(e.message); }
}

function closeDrawer() {
    drawerId = null;
    document.getElementById('filesDrawer').hidden = true;
    document.querySelectorAll('.files-selected').forEach(tr => tr.classList.remove('files-selected'));
}

function verdict(label, value, bad) {
    const text = value == null ? muted(I18N.notChecked)
        : el('span', {className: value === bad ? 'files-fg-danger' : 'files-fg-success', textContent: value === bad ? I18N.verdictFail : I18N.verdictPass});
    return el('div', null, muted(label), el('b', null, text));
}

function section(title, ...children) {
    return el('section', null, el('h6', {textContent: title}), children);
}

function titleLink(titleId, content, className) {
    // The game's page (stage 3). It used to point at a "title" route that never
    // existed, so the link only ever landed on the Library.
    return el('a', {href: `/game/${titleId}`, className: `files-title-link ${className || ''}`}, content);
}

function pathParts(f) {
    const root = f.library && f.filepath.startsWith(f.library.path) ? f.library.path : null;
    return root ? [muted(root), f.filepath.slice(root.length)] : f.filepath;
}

function renderDrawer(f) {
    const drawer = document.getElementById('filesDrawer');
    const close = el('button', {type: 'button', className: 'icon-btn ms-auto', title: I18N.closeTitle}, el('i', {className: 'bi bi-x-lg'}));
    close.addEventListener('click', closeDrawer);
    const titles = fileTitles(f);
    const bullet = () => muted(' · ');
    const contents = f.apps && f.apps.length
        ? f.apps.map(a => el('div', {className: 'mb-1'},
            chip(APP_TYPES[a.appType] || a.appType, (a.appType || '').toLowerCase()), bullet(), version(a), bullet(),
            el('span', {className: 'files-app-id', textContent: a.appId})))
        : [muted(`${f.identificationError || I18N.notMatchedText}. ${f.identificationAttempts} ${I18N.attemptsSuffix}.`)];
    const verified = parseDate(f.verifiedAt, false);
    drawer.replaceChildren(
        el('div', {className: 'files-drawer-head'}, titles.length ? titleLink(titles[0].titleId, avatar(f.apps, 'lg')) : avatar(f.apps, 'lg'),
            el('div', null,
                titles.length ? titleLink(titles[0].titleId, el('div', {className: 'fw-semibold', textContent: titleName(f)}))
                    : el('div', {className: 'fw-semibold', textContent: f.filename}),
                el('div', {className: 'small font-monospace'}, titles.map((a, i) =>
                    [i ? muted(', ') : null, titleLink(a.titleId, a.titleId, 'text-secondary')]))),
            close),
        el('div', {className: 'files-drawer-actions'}, actionButtons(f, 'btn btn-sm bg-body-tertiary border-0', true)),
        section(I18N.sectionContents, contents),
        section(I18N.labelVerification, statusPill(f.verificationStatus),
            f.signatureValid === undefined ? null : el('div', {className: 'files-verdicts'},
                verdict(I18N.labelSignature, f.signatureValid, false), verdict(I18N.labelContentHash, f.hashValid, false),
                el('div', null, muted(I18N.labelHashModified), el('b', null, f.hashModified == null ? muted(I18N.no) : (f.hashModified ? I18N.yes : I18N.no)))),
            f.verificationError ? el('div', {className: 'files-fg-danger small files-error-lines',
                                             textContent: f.verificationError.replaceAll('; >', '\n>')}) : null,
            verified ? el('div', {className: 'small text-secondary'}, I18N.checkedPrefix, when(verified)) : null),
        section(I18N.sectionFile,
            el('dl', {className: 'files-kv'},
            el('dt', null, I18N.dtName), el('dd', null, f.filename),
            el('dt', null, I18N.dtPath), el('dd', null, pathParts(f)),
            el('dt', null, I18N.dtFormat), el('dd', null, `${f.extension}${f.compressed ? I18N.compressedSuffix : ''}`),
            el('dt', null, I18N.labelSize), el('dd', null, formatBytes(f.size)),
            el('dt', null, I18N.dtIdentified), el('dd', null, f.identificationType ? ({cnmt: I18N.fromCnmt, nup: I18N.fromNup}[f.identificationType] || I18N.fromFilename) : I18N.no),
            el('dt', null, I18N.labelAdded), el('dd', null, when(parseDate(f.addedAt, true))),
            el('dt', null, I18N.dtModified), el('dd', null, f.mtime ? when(new Date(f.mtime * 1000)) : '…'),
            el('dt', null, I18N.dtDownloads), el('dd', null, f.downloadCount == null ? '…' : String(f.downloadCount)))));
    drawer.dataset.id = f.id;
    drawer.hidden = false;
    paintBusy();
}

// --- keeping the tabs fresh ---
//
// Each tab keeps its rows until the files change: entering it again shows them at once.
// The server publishes a signature of the files table on the realtime feed
// (files_events.py); when it moves, the tiles and the open tab follow and every other
// tab is asked again the next time it is entered - only then.

let filesRevision = null;
let lastLoaded = 0;
const packingStale = {compress: false, combine: false};

/** Every tab but `except` asks its rows again when next entered. */
function markStale(except) {
    Object.entries(TABS).forEach(([key, tab]) => {
        if (key === except) return;
        if (tab.kind === 'packing') packingStale[key] = true;
        else tab.rows = null;
    });
}

/** The files changed somewhere (a task, another page, a scan): the tiles and the open
 *  tab follow, the rest wait to be entered. A reload this page just made covers it. */
function filesChanged() {
    markStale(current);
    loadStats();
    if (Date.now() - lastLoaded < 4000) return;
    const tab = TABS[current];
    if (tab.kind === 'pending') return;      // Pending follows its own tasks, live
    if (tab.kind === 'packing') packingStale[current] = true;
    loadTab(true);
}

const live = new Realtime(['files']);
live.on('files', (type, data) => {
    const item = Array.isArray(data) ? data[0] : data;
    const revision = item && item.revision;
    if (!revision || revision === filesRevision) return;
    const first = filesRevision === null;
    filesRevision = revision;
    if (!first) filesChanged();
});

// --- views ---

function showTab() {
    const name = location.hash.slice(1);
    current = TABS[name] ? name : 'all';
    notice('');
    closeDrawer();
    paintTiles();
    document.querySelectorAll('.files-status').forEach(s => s.classList.toggle('d-none', s.dataset.tab !== current));
    renderChips();
    renderHead();
    loadTab(false);
    if (current === 'pending') startPending(); else stopPending();
}

let searchTimer = null;

function setSearch(text) {
    const tab = TABS[current];
    tab.search = text;
    tab.page = 1;
    if (tab.kind === 'files') loadTab(true); else renderBody();
}

const search = document.getElementById('filesSearch');
search.addEventListener('input', () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => setSearch(search.value.trim()), 300);
});

/** A short word from the page: the Synchronize button's outcome, in place. */
function showToast(text) {
    const toast = document.getElementById('filesToast');
    if (!toast) return;
    $('#filesToastText').text(text);
    bootstrap.Toast.getOrCreateInstance(toast).show();
}

/** Synchronize, Switch Library Manager style: download the latest TitleDB and scan
 *  every library behind it. The button spins while the TitleDB task runs (a rebuilt
 *  one re-identifies the library on its own); the scan it chains shows up on Tasks and
 *  Pending as usual. */
async function syncLibrary() {
    const btn = $('#syncFiles');
    if (btn.prop('disabled')) return;
    btn.prop('disabled', true).find('i').addClass('spin');
    try {
        const d = await gql('mutation { syncLibrary { id status } }', {}, true);
        const id = d.syncLibrary && d.syncLibrary.id;
        // Until the TitleDB task settles (it can run for a while on a slow link). A
        // finished root task LEAVES the queue (its row moves to History) while a failed
        // one keeps its row: gone means done, not an error.
        while (id) {
            await new Promise(r => setTimeout(r, 2000));
            const t = await gql(`{ task(id: ${id}) { status } }`);
            const status = t.task && t.task.status;
            if (!status) { showToast(I18N.syncDone); break; }
            if (status === 'RUNNING' || status === 'PENDING' || status === 'WAITING_FOR_CHILDREN') continue;
            showToast(status === 'SUCCEEDED' ? I18N.syncDone : I18N.syncFailedTemplate.replace('{error}', status));
            break;
        }
        loadStats();
        loadTab(true);
    } catch (e) {
        showToast(I18N.syncFailedTemplate.replace('{error}', e.message));
    } finally {
        btn.prop('disabled', false).find('i').removeClass('spin');
    }
}

$('#syncFiles').on('click', syncLibrary);
function turnPage(step, button) {
    TABS[current].page += step;
    if (button.closest('#filesPagerBottom')) document.querySelector('.files-toolbar').scrollIntoView({block: 'start'});
    loadTab(true);
}

$('.files-prev').on('click', e => turnPage(-1, e.currentTarget));
$('.files-next').on('click', e => turnPage(1, e.currentTarget));
$('.files-delete').on('click', runRemoval);
document.addEventListener('keydown', e => { if (e.key === 'Escape' && drawerId) closeDrawer(); });
window.addEventListener('hashchange', showTab);

loadStats();
// Pending moves as tasks come and go elsewhere too (a scan from Synchronize, a combine
// queued in another view): keep its tile honest without a page reload.
setInterval(() => {
    gql('{ pendingFiles { total } }').then(d => {
        if (d.pendingFiles && d.pendingFiles.total !== groupStats.pending) {
            groupStats.pending = d.pendingFiles.total;
            paintTiles();
        }
    }).catch(() => {});
}, 12000);
live.start();
// ?q= from the global search (Ctrl+K): open the All tab already filtered by it.
const urlSearch = new URLSearchParams(location.search).get('q');
if (urlSearch) TABS.all.search = urlSearch;
loadOptions().catch(e => notice(e.message)).finally(showTab);
