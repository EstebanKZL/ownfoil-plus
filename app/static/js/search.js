// Global search palette (Ctrl+K, Cmd+K or "/"), on every page with the navbar. Pages and
// settings sections come from nav.html (already filtered by what this user may open);
// games and - for an admin - files come from /api/search. Arrow keys move, Enter opens.
(function () {
    const data = document.getElementById('searchPages');
    const modalEl = document.getElementById('searchModal');
    if (!data || !modalEl) return;
    const config = JSON.parse(data.textContent);
    const input = document.getElementById('searchInput');
    const list = document.getElementById('searchResults');
    const modal = new bootstrap.Modal(modalEl);
    let items = [];
    let active = 0;
    let timer = null;
    let requestId = 0;

    // Accent-insensitive: "configuracion" finds "Configuración".
    const fold = s => (s || '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();

    function matchPages(query) {
        const q = fold(query);
        if (!q) return config.pages.slice(0, 8);
        return config.pages.filter(p => fold(p.title + ' ' + p.keywords).includes(q)).slice(0, 6);
    }

    function render(groups) {
        list.innerHTML = '';
        items = [];
        groups.forEach(([label, entries]) => {
            if (!entries.length) return;
            const header = document.createElement('div');
            header.className = 'list-group-item small text-secondary text-uppercase bg-body-tertiary py-1';
            header.textContent = label;
            list.append(header);
            entries.forEach(entry => {
                const a = document.createElement('a');
                a.className = 'list-group-item list-group-item-action d-flex align-items-center gap-2';
                a.href = entry.url;
                a.setAttribute('role', 'option');
                const icon = document.createElement('i');
                icon.className = 'bi ' + entry.icon;
                const text = document.createElement('span');
                text.className = 'text-truncate me-auto';
                text.textContent = entry.title;
                a.append(icon, text);
                if (entry.detail) {
                    const detail = document.createElement('small');
                    detail.className = 'text-secondary text-nowrap';
                    detail.textContent = entry.detail;
                    a.append(detail);
                }
                a.addEventListener('mousemove', () => select(items.indexOf(a)));
                list.append(a);
                items.push(a);
            });
        });
        if (!items.length) {
            const empty = document.createElement('div');
            empty.className = 'list-group-item text-secondary fst-italic';
            empty.textContent = input.value.trim() ? config.empty : config.hint;
            list.append(empty);
        }
        select(0);
    }

    function select(index) {
        if (!items.length) return;
        active = (index + items.length) % items.length;
        items.forEach((item, i) => item.classList.toggle('active', i === active));
        items[active].scrollIntoView({block: 'nearest'});
    }

    function pageEntries(query) {
        return matchPages(query).map(p => ({title: p.title, url: p.url, icon: p.icon}));
    }

    function search() {
        const query = input.value.trim();
        const pages = pageEntries(query);
        render([[config.pagesLabel, pages]]);
        clearTimeout(timer);
        if (query.length < 2) return;
        const id = ++requestId;
        timer = setTimeout(() => {
            fetch('/api/search?q=' + encodeURIComponent(query), {credentials: 'same-origin'})
                .then(r => r.ok ? r.json() : {titles: [], files: []})
                .then(result => {
                    if (id !== requestId) return;   // a newer keystroke already searched
                    const games = result.titles.map(g => ({
                        title: g.name, url: '/?q=' + encodeURIComponent(g.name), icon: 'bi-controller', detail: g.title_id}));
                    const files = result.files.map(f => ({
                        title: f.filename, url: '/admin/files?q=' + encodeURIComponent(f.filename),
                        icon: 'bi-file-earmark', detail: typeof formatBytes === 'function' ? formatBytes(f.size) : ''}));
                    render([[config.games, games], [config.files, files], [config.pagesLabel, pages]]);
                })
                .catch(() => {});
        }, 150);
    }

    window.openSearch = function () {
        input.value = '';
        search();
        modal.show();
    };

    modalEl.addEventListener('shown.bs.modal', () => input.focus());
    input.addEventListener('input', search);
    input.addEventListener('keydown', event => {
        if (event.key === 'ArrowDown') { event.preventDefault(); select(active + 1); }
        else if (event.key === 'ArrowUp') { event.preventDefault(); select(active - 1); }
        else if (event.key === 'Enter' && items[active]) { event.preventDefault(); items[active].click(); }
    });
    document.addEventListener('keydown', event => {
        const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement.tagName)
            || document.activeElement.isContentEditable;
        if ((event.key === 'k' || event.key === 'K') && (event.ctrlKey || event.metaKey)) {
            event.preventDefault();
            window.openSearch();
        } else if (event.key === '/' && !typing && !modalEl.classList.contains('show')) {
            event.preventDefault();
            window.openSearch();
        }
    });
})();
