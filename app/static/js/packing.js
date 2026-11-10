/* Files > Compression and Files > Combine (templates/files.html, driven by files.js's
   tiles). Compression: each game with its NSP/NSZ/XCI/XCZ files - pick files, then
   compress the uncompressed ones or decompress the compressed ones; each file becomes a
   task. Combine: each game with its base plus latest update and/or DLC as loose files
   (to combine into one) and every combined file (to split back). The options - the
   level, "delete the originals" - are Settings', shown above the panel. Strings come
   from the page's I18N object (its `pack` part); formatBytes from format.js,
   fillTitleIcons from title-list.js. */

const Packing = (() => {
    const T = I18N.pack;
    const state = {
        compress: {games: null, picked: new Set(), search: '', show: 'all', format: 'all', page: 0, view: ''},
        combine: {games: null, picked: new Set(), search: '', show: 'all', page: 0, view: ''},
    };
    let keysValid = true;
    // Games shown open (their files listed); every other one is folded to its header.
    const open = {compress: new Set(), combine: new Set()};

    function make(tag, className, text) {
        const n = document.createElement(tag);
        if (className) n.className = className;
        if (text !== undefined && text !== null) n.textContent = text;
        return n;
    }

    function fill(template, values) {
        return Object.entries(values).reduce((s, [k, v]) => s.replaceAll(`{${k}}`, v), template);
    }

    // A combine row's key: the title id for loose parts, "f<id>" for a combined file.
    const rowKey = g => g.state === 'combined' ? `f${g.file_id}` : g.title_id;

    const inFlight = {};

    /** The list from the server; a call while one is already on its way shares it (the
     *  tiles and the open tab both ask when the page loads). */
    function load(kind, force) {
        if (state[kind].games && !force) return Promise.resolve();
        if (!inFlight[kind]) inFlight[kind] = fetchList(kind).finally(() => { inFlight[kind] = null; });
        return inFlight[kind];
    }

    async function fetchList(kind) {
        const s = state[kind];
        const r = await fetch(`/api/files/${kind}`, {credentials: 'same-origin'});
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const data = await r.json();
        keysValid = data.keys_valid;
        s.games = data.games;
        const keys = new Set(kind === 'compress' ? s.games.flatMap(g => g.files.map(f => f.id)) : s.games.map(rowKey));
        s.picked = new Set([...s.picked].filter(k => keys.has(k)));
    }

    /** For the tiles: [count, subtitle]. */
    function figures(kind) {
        const games = state[kind].games;
        if (!games) return null;
        if (kind === 'compress') {
            const files = games.flatMap(g => g.files);
            const raw = files.filter(f => !f.compressed);
            return [raw.length, fill(T.tileCompressSub, {size: formatBytes(raw.reduce((n, f) => n + f.size, 0)),
                                                         count: (files.length - raw.length).toLocaleString()})];
        }
        const loose = games.filter(g => g.state === 'loose');
        return [loose.length, fill(T.tileCombineSub, {count: (games.length - loose.length).toLocaleString()})];
    }

    const KIND_LABEL = () => ({BASE: T.kindBase, UPDATE: T.kindUpdate, DLC: T.kindDlc, MULTI: T.kindMulti});
    // Each kind wears its content type's fixed color, the same in every style.
    const KIND_TONE = {BASE: 'base', UPDATE: 'wait', DLC: 'dlc', MULTI: 'fav'};

    function badge(kind) {
        return make('span', `packing-kind packing-kind--${KIND_TONE[kind]}`, KIND_LABEL()[kind]);
    }

    function format(ext, compressed) {
        return make('span', `packing-format${compressed ? ' is-compressed' : ''}`, ext.toUpperCase());
    }

    function icon(game) {
        const box = make('span', 'dash-list__icon packing-icon');
        if (game.icon_url) {
            const img = document.createElement('img');
            img.src = game.icon_url;
            img.alt = '';
            img.loading = 'lazy';
            box.append(img);
        } else {
            box.append(make('i', 'bi bi-controller'));
            box.dataset.titleIcon = game.title_id;
        }
        return box;
    }

    function checkbox(checked, onChange, label) {
        const input = make('input', 'form-check-input packing-check admin-write');
        input.type = 'checkbox';
        input.checked = checked;
        if (label) input.setAttribute('aria-label', label);
        input.addEventListener('change', () => onChange(input.checked));
        return input;
    }

    // --- what shows ----------------------------------------------------------------------

    function fileShown(s, f) {
        if (s.show === 'raw' && f.compressed) return false;
        if (s.show === 'compressed' && !f.compressed) return false;
        return s.format === 'all' || f.extension === s.format;
    }

    function visibleGames(kind) {
        const s = state[kind];
        const q = s.search.toLowerCase();
        return (s.games || []).map(g => {
            if (q && !g.name.toLowerCase().includes(q) && !g.title_id.toLowerCase().includes(q)) return null;
            if (kind === 'compress') {
                const files = g.files.filter(f => fileShown(s, f));
                return files.length ? {...g, files} : null;
            }
            if (s.show !== 'all' && g.state !== s.show) return null;
            return g;
        }).filter(Boolean);
    }

    /** The filters, shown the way the flat list shows its own: every active one a chip
     *  (its choices in a dropdown, an x that clears it back to "all") and a "+" that
     *  adds one - asked for, in place of the rows of pills that used to sit above the
     *  list. Single choice per filter, so the menu items are plain buttons. */
    function filterDefs(kind) {
        if (kind === 'compress') {
            const files = (state[kind].games || []).flatMap(g => g.files);
            const byShow = v => files.filter(f => v === 'all' || (v === 'raw') === !f.compressed);
            return [
                {key: 'show', label: T.filterState,
                 options: () => [['all', T.showAll], ['raw', T.showRaw], ['compressed', T.showCompressed]],
                 count: v => byShow(v).length},
                {key: 'format', label: T.filterFormat,
                 options: () => [['all', T.formatAll], ['nsp', 'NSP'], ['nsz', 'NSZ'], ['xci', 'XCI'], ['xcz', 'XCZ']],
                 count: v => {
                     const seen = byShow(state[kind].show);
                     return v === 'all' ? seen.length : seen.filter(f => f.extension === v).length;
                 }},
            ];
        }
        const games = state[kind].games || [];
        return [
            {key: 'show', label: T.filterState,
             options: () => [['all', T.showAll], ['loose', T.showLoose], ['combined', T.showCombined]],
             count: v => games.filter(g => v === 'all' || g.state === v).length},
        ];
    }

    function filterChipNode(kind, def) {
        const s = state[kind];
        const chip = make('div', 'dropdown files-filter-chip');
        chip.dataset.key = def.key;
        const toggle = make('button');
        toggle.type = 'button';
        toggle.dataset.bsToggle = 'dropdown';
        const current = () => def.options().find(([v]) => v === s[def.key]);
        toggle.replaceChildren(`${def.label}: `, make('b', null, current() ? current()[1] : ''));
        const menu = make('div', 'dropdown-menu');
        def.options().forEach(([v, label]) => {
            const item = make('button', 'dropdown-item');
            item.type = 'button';
            item.append(make('span', null, label),
                         make('span', 'text-secondary ms-2 small', def.count(v).toLocaleString()));
            item.addEventListener('click', () => { s[def.key] = v; render(kind); });
            menu.append(item);
        });
        const remove = make('button', null);
        remove.type = 'button';
        remove.title = T.removeFilterTitle;
        remove.append(make('i', 'bi bi-x'));
        remove.addEventListener('click', () => { s[def.key] = 'all'; render(kind); });
        chip.append(toggle, menu, remove);
        return chip;
    }

    /** The chips bar that goes in the toolbar, after the search: active chips first,
     *  then the "+" with the filters still on "all". */
    function filterBar(kind) {
        const s = state[kind];
        const defs = filterDefs(kind);
        const bar = make('div', 'files-chips');
        defs.forEach(def => { if (s[def.key] !== 'all') bar.append(filterChipNode(kind, def)); });
        const add = make('div', 'dropdown');
        const addBtn = make('button', 'icon-btn');
        addBtn.type = 'button';
        addBtn.dataset.bsToggle = 'dropdown';
        addBtn.append(make('i', 'bi bi-plus-lg'), document.createTextNode(' '), make('span', null, T.filterButton));
        const menu = make('div', 'dropdown-menu');
        const free = defs.filter(def => s[def.key] === 'all');
        free.forEach(def => {
            const item = make('button', 'dropdown-item', def.label);
            item.type = 'button';
            item.addEventListener('click', () => {
                // Straight to its first real choice ("Uncompressed", say), with the
                // chip's own menu open to change it - same feel as the flat list.
                const first = def.options().find(([v]) => v !== 'all');
                s[def.key] = first ? first[0] : 'all';
                render(kind);
                const toggle = document.querySelector(`#packingPanel .files-filter-chip[data-key="${def.key}"] [data-bs-toggle]`);
                if (toggle) setTimeout(() => bootstrap.Dropdown.getOrCreateInstance(toggle).show());
            });
            menu.append(item);
        });
        addBtn.disabled = !free.length;
        add.append(addBtn, menu);
        bar.append(add);
        return bar;
    }

    function toolbar(kind, shown) {
        const s = state[kind];
        // The search leads, flush left like every other card's toolbar; "Select all"
        // rides on its own row underneath (asked for), so the row reads the same as
        // the flat list's.
        const wrap = make('div', 'packing-toolbar-wrap');
        const bar = make('div', 'packing-toolbar');
        const keys = kind === 'compress' ? shown.flatMap(g => g.files.map(f => f.id)) : shown.map(rowKey);
        const all = keys.length > 0 && keys.every(k => s.picked.has(k));
        const selectAll = make('label', 'packing-select-all admin-write');
        selectAll.append(checkbox(all, on => {
            keys.forEach(k => on ? s.picked.add(k) : s.picked.delete(k));
            render(kind);
        }, T.selectAll), document.createTextNode(T.selectAll));
        const search = make('div', 'packing-search');
        search.append(make('i', 'bi bi-search'));
        const input = make('input', 'form-control form-control-sm');
        input.type = 'search';
        input.placeholder = T.search;
        input.setAttribute('aria-label', T.search);
        input.value = s.search;
        input.addEventListener('input', () => {
            clearTimeout(input._timer);
            input._timer = setTimeout(() => { s.search = input.value.trim(); render(kind); focusSearch(); }, 250);
        });
        search.append(input);
        bar.append(search, filterBar(kind), make('span', 'packing-summary ms-auto', summary(kind)));
        const under = make('div', 'packing-toolbar packing-toolbar--under');
        under.append(selectAll);
        wrap.append(bar, under);
        return wrap;
    }

    function focusSearch() {
        const input = document.querySelector('#packingPanel .packing-search input');
        if (input) { input.focus(); input.setSelectionRange(input.value.length, input.value.length); }
    }

    function picked(kind) {
        const s = state[kind];
        if (kind === 'compress') return (s.games || []).flatMap(g => g.files).filter(f => s.picked.has(f.id));
        return (s.games || []).filter(g => s.picked.has(rowKey(g)));
    }

    function summary(kind) {
        const items = picked(kind);
        return fill(kind === 'compress' ? T.selectedFiles : T.selectedGames,
                    {count: items.length.toLocaleString(), size: formatBytes(items.reduce((n, x) => n + x.size, 0))});
    }

    /** A game's header: checkbox, icon, name and summary, and the arrow that opens its
     *  files (a click anywhere on the header but the checkbox and the name does too). */
    function gameHead(kind, key, game, sub, checked, onCheck, side) {
        const head = make('div', 'packing-game__head');
        const text = make('div', 'packing-game__text');
        // The name opens the file panel on the right, like every other view of the page
        // (it used to leave for the game page).
        const name = make('button', 'packing-game__name', game.name);
        name.type = 'button';
        name.title = game.name;
        name.addEventListener('click', () => {
            const files = game.files || [];
            const first = files.find(f => f.kind === 'BASE') || files[0];
            if (first && typeof openDrawer === 'function') openDrawer({id: String(first.id)});
        });
        text.append(name, make('div', 'packing-game__sub', sub));
        const isOpen = open[kind].has(key);
        const toggle = make('button', 'icon-btn packing-toggle');
        toggle.type = 'button';
        toggle.setAttribute('aria-expanded', isOpen ? 'true' : 'false');
        toggle.setAttribute('aria-label', isOpen ? T.hideFiles : T.showFiles);
        toggle.title = isOpen ? T.hideFiles : T.showFiles;
        toggle.append(make('i', `bi ${isOpen ? 'bi-chevron-up' : 'bi-chevron-down'}`));
        head.append(checkbox(checked, onCheck, game.name), icon(game), text);
        if (side) head.append(side);
        head.append(toggle);
        head.addEventListener('click', e => {
            if (e.target.closest('input, a, .packing-game__name')) return;
            isOpen ? open[kind].delete(key) : open[kind].add(key);
            render(kind);
        });
        return head;
    }

    function compressGame(game) {
        const s = state.compress;
        const card = make('section', 'surface packing-game');
        const ids = game.files.map(f => f.id);
        const size = game.files.reduce((n, f) => n + f.size, 0);
        const some = ids.filter(id => s.picked.has(id)).length;
        const sub = fill(T.filesCount, {count: game.files.length, size: formatBytes(size)})
            + (some && some < ids.length ? ' · ' + fill(T.pickedOf, {count: some}) : '');
        const side = make('div', 'packing-game__side');
        [...new Set(game.files.map(f => f.extension))].forEach(ext =>
            side.append(format(ext, ext === 'nsz' || ext === 'xcz')));
        card.append(gameHead('compress', game.title_id, game, sub, ids.every(id => s.picked.has(id)), on => {
            ids.forEach(id => on ? s.picked.add(id) : s.picked.delete(id));
            render('compress');
        }, side));
        if (!open.compress.has(game.title_id)) return card;
        const list = make('ul', 'packing-files');
        game.files.forEach(f => {
            const li = make('li', 'packing-file');
            const name = make('span', 'packing-file__name', f.filename);
            name.title = f.filename;
            li.append(checkbox(s.picked.has(f.id), on => {
                on ? s.picked.add(f.id) : s.picked.delete(f.id);
                render('compress');
            }, f.filename), badge(f.kind), format(f.extension, f.compressed), name,
            make('span', 'packing-size', formatBytes(f.size)));
            list.append(li);
        });
        card.append(list);
        return card;
    }

    function partsText(parts) {
        const out = [];
        if (parts.base) out.push(T.kindBase);
        if (parts.update) out.push(T.kindUpdate);
        if (parts.dlc) out.push(fill(T.dlcCount, {count: parts.dlc}));
        return out.join(' + ');
    }

    function combineGame(game) {
        const s = state.combine;
        const key = rowKey(game);
        const combined = game.state === 'combined';
        const card = make('section', `surface packing-game${combined ? ' is-combined' : ''}`);
        const side = make('div', 'packing-game__side');
        side.append(make('span', `packing-state packing-state--${combined ? 'combined' : 'loose'}`,
                         combined ? T.stateCombined : T.stateLoose),
                    format(game.extension, game.extension === 'nsz'), make('span', 'packing-size', formatBytes(game.size)));
        card.append(gameHead('combine', key, game, partsText(game.parts), s.picked.has(key), on => {
            on ? s.picked.add(key) : s.picked.delete(key);
            render('combine');
        }, side));
        if (!open.combine.has(key)) return card;
        const list = make('ul', 'packing-files packing-files--parts');
        game.files.forEach(f => {
            const li = make('li', 'packing-file');
            const name = make('span', 'packing-file__name', f.filename);
            name.title = f.filename;
            li.append(badge(f.kind), format(f.extension, f.compressed), name, make('span', 'packing-size', formatBytes(f.size)));
            list.append(li);
        });
        card.append(list);
        return card;
    }

    function action(label, glyph, count, tone, onClick) {
        const b = make('button', `btn ${tone} admin-write`);
        b.type = 'button';
        b.append(make('i', `bi ${glyph} me-1`), document.createTextNode(fill(label, {count: count.toLocaleString()})));
        b.disabled = !count || !keysValid;
        b.addEventListener('click', () => onClick(b));
        return b;
    }

    function footer(kind) {
        const bar = make('div', 'surface packing-footer');
        bar.append(make('span', 'packing-note', kind === 'compress' ? T.compressNote : T.combineNote));
        const buttons = make('div', 'packing-actions');
        const items = picked(kind);
        if (kind === 'compress') {
            const raw = items.filter(f => !f.compressed);
            const zipped = items.filter(f => f.compressed);
            buttons.append(
                action(T.decompressBtn, 'bi-file-earmark-arrow-up', zipped.length, 'btn-outline-secondary',
                       b => run('compress', b, {action: 'decompress', file_ids: zipped.map(f => f.id)})),
                action(T.compressBtn, 'bi-file-earmark-zip', raw.length, 'btn-primary',
                       b => run('compress', b, {action: 'compress', file_ids: raw.map(f => f.id)})));
        } else {
            const loose = items.filter(g => g.state === 'loose');
            const combined = items.filter(g => g.state === 'combined');
            buttons.append(
                action(T.splitBtn, 'bi-boxes', combined.length, 'btn-outline-secondary',
                       b => run('combine', b, {action: 'split', file_ids: combined.map(g => g.file_id)}, T.splitConfirm)),
                action(T.combineBtn, 'bi-box-seam', loose.length, 'btn-primary',
                       b => run('combine', b, {action: 'combine', title_ids: loose.map(g => g.title_id)}, T.combineConfirm)));
        }
        bar.append(buttons);
        return bar;
    }

    async function run(kind, button, body, confirmText) {
        const count = (body.file_ids || body.title_ids).length;
        if (confirmText && I18N.pack.deletesOriginals && !confirm(fill(confirmText, {count}))) return;
        button.disabled = true;
        try {
            const r = await fetch(`/api/files/${kind}`, {method: 'POST', credentials: 'same-origin',
                headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
            const data = await r.json();
            if (!r.ok || !data.success) throw new Error(data.error || `HTTP ${r.status}`);
            const done = new Set(body.file_ids ? body.file_ids.map(id => kind === 'compress' ? id : `f${id}`) : body.title_ids);
            state[kind].picked = new Set([...state[kind].picked].filter(k => !done.has(k)));
            render(kind);
            showNotice(fill(T.queued, {count: data.queued}));
        } catch (e) {
            showNotice(e.message);
            button.disabled = false;
        }
    }

    function showNotice(text) {
        const box = document.getElementById('packingNotice');
        if (!box) return;
        box.replaceChildren(document.createTextNode(text + ' '));
        // Pending, right here: the follow-up link opens the tab that shows this very
        // work with its live bars (asked for - it used to leave for the Tasks page).
        const link = make('a', null, T.openTasks);
        link.href = '#pending';
        box.append(link);
        box.hidden = false;
    }

    const PAGE_GAMES = 100;

    /** A page of at most PAGE_GAMES games: a long library rendered every game card at once. */
    function pager(kind, total) {
        const s = state[kind];
        const pages = Math.ceil(total / PAGE_GAMES);
        const bar = make('div', 'packing-pager');
        if (pages <= 1) return bar;
        const first = s.page * PAGE_GAMES + 1;
        const last = Math.min(total, first + PAGE_GAMES - 1);
        const step = (delta, glyph, label) => {
            const b = make('button', 'icon-btn');
            b.type = 'button';
            b.title = label;
            b.setAttribute('aria-label', label);
            b.disabled = s.page + delta < 0 || s.page + delta >= pages;
            b.append(make('i', `bi ${glyph}`));
            b.addEventListener('click', () => {
                s.page += delta;
                render(kind);
                document.getElementById('packingPanel').scrollIntoView({block: 'start'});
            });
            return b;
        };
        bar.append(make('span', 'packing-pager__text', I18N.pagerRangeTemplate
            .replace('{first}', first.toLocaleString()).replace('{last}', last.toLocaleString())
            .replace('{total}', total.toLocaleString())),
            step(-1, 'bi-chevron-left', I18N.previousPage), step(1, 'bi-chevron-right', I18N.nextPage));
        return bar;
    }

    function render(kind) {
        const panel = document.getElementById('packingPanel');
        const s = state[kind];
        const nodes = [];
        const notice = make('p', 'dash-notice dash-notice--ok packing-notice');
        notice.id = 'packingNotice';
        notice.hidden = true;
        nodes.push(notice);
        if (s.games === null) {
            nodes.push(make('p', 'text-secondary fst-italic', I18N.loading));
        } else if (!s.games.length) {
            nodes.push(make('p', 'text-secondary', kind === 'compress' ? T.noneCompress : T.noneCombine));
        } else {
            const shown = visibleGames(kind);
            // Another search or filter starts again from the first page.
            const view = JSON.stringify([s.search, s.show, s.format]);
            if (view !== s.view) { s.view = view; s.page = 0; }
            s.page = Math.max(0, Math.min(s.page, Math.ceil(shown.length / PAGE_GAMES) - 1));
            const page = shown.slice(s.page * PAGE_GAMES, (s.page + 1) * PAGE_GAMES);
            nodes.push(toolbar(kind, shown), pager(kind, shown.length));
            if (!shown.length) nodes.push(make('p', 'text-secondary', I18N.emptyFiltered));
            const list = make('div', 'packing-games');
            page.forEach(g => list.append(kind === 'compress' ? compressGame(g) : combineGame(g)));
            nodes.push(list, pager(kind, shown.length), footer(kind));
        }
        panel.replaceChildren(...nodes);
        if (typeof fillTitleIcons === 'function') fillTitleIcons(panel);
    }

    return {load, render, figures};
})();
