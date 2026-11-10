// One pager for every paged list (asked for): "Showing
// 1-24 of 42" on the left, the pages in the middle, "Per page" on the right. Loaded in
// <head> by base.html; its strings come from base.html's #pagerI18n JSON block. Each
// page remembers its own "per page" in this browser (Pager.perPage / Pager.savePerPage).
(function () {
    let strings = null;

    function t(key) {
        if (!strings) {
            try {
                strings = JSON.parse(document.getElementById('pagerI18n').textContent);
            } catch (e) {
                strings = {};
            }
        }
        return strings[key] || '';
    }

    function el(tag, className, text) {
        const node = document.createElement(tag);
        if (className) node.className = className;
        if (text !== undefined && text !== null) node.textContent = text;
        return node;
    }

    /** The pages shown: the first, the last and `span` around the current one (two; one
     *  on a phone, where the row has to fit), "…" between. */
    function windowOf(page, pages, span = 2) {
        const wanted = new Set([1, pages]);
        for (let p = page - span; p <= page + span; p++) if (p >= 1 && p <= pages) wanted.add(p);
        const out = [];
        let last = 0;
        [...wanted].sort((a, b) => a - b).forEach(p => {
            if (last && p - last > 1) out.push(null);
            out.push(p);
            last = p;
        });
        return out;
    }

    /**
     * Fill `container` with the bar. Options:
     *   total      how many items in all
     *   page       the page shown, from 1
     *   perPage    items a page
     *   sizes      the "per page" choices (none: no chooser)
     *   onPage(p)  a page was picked
     *   onPerPage(n)  a size was picked
     * The bar hides itself with nothing to show (no items).
     */
    function render(container, {total, page, perPage, sizes, onPage, onPerPage}) {
        if (!container) return;
        container.classList.add('op-pager');
        container.replaceChildren();
        total = Math.max(0, total || 0);
        container.hidden = total === 0;
        if (!total) return;
        const pages = Math.max(1, Math.ceil(total / perPage));
        page = Math.min(Math.max(1, page), pages);
        const first = (page - 1) * perPage + 1;
        const last = Math.min(total, page * perPage);
        const range = el('div', 'op-pager__range', t('showing')
            .replace('{first}', first.toLocaleString()).replace('{last}', last.toLocaleString())
            .replace('{total}', total.toLocaleString()));
        range.setAttribute('role', 'status');

        const list = el('ul', 'pagination op-pager__pages');
        list.hidden = pages <= 1;
        const item = (label, target, {active = false, disabled = false, aria = null} = {}) => {
            const li = el('li', 'page-item' + (active ? ' active' : '') + (disabled ? ' disabled' : ''));
            const link = el(target === null || disabled ? 'span' : 'a', 'page-link', label);
            if (link.tagName === 'A') {
                link.href = '#';
                link.addEventListener('click', e => {
                    e.preventDefault();
                    if (target !== page && onPage) onPage(target);
                });
            }
            if (aria) link.setAttribute('aria-label', aria);
            if (active) link.setAttribute('aria-current', 'page');
            li.append(link);
            return li;
        };
        list.append(item('«', page - 1, {disabled: page === 1, aria: t('previous')}));
        const narrow = window.matchMedia('(max-width: 575.98px)').matches;
        windowOf(page, pages, narrow ? 1 : 2).forEach(p => list.append(
            p === null ? item('…', null, {disabled: true}) : item(String(p), p, {active: p === page})));
        list.append(item('»', page + 1, {disabled: page === pages, aria: t('next')}));
        const nav = el('nav', 'op-pager__nav');
        nav.setAttribute('aria-label', t('pages'));
        nav.append(list);

        const size = el('div', 'op-pager__size');
        if (sizes && sizes.length && onPerPage) {
            const id = `opPagerSize${render.seq = (render.seq || 0) + 1}`;
            const label = el('label', 'op-pager__size-label', t('perPage'));
            label.htmlFor = id;
            const select = el('select', 'form-select form-select-sm op-pager__select');
            select.id = id;
            const choices = sizes.includes(perPage) ? sizes : [...sizes, perPage].sort((a, b) => a - b);
            choices.forEach(n => {
                const option = el('option', null, String(n));
                option.value = String(n);
                option.selected = n === perPage;
                select.append(option);
            });
            select.addEventListener('change', () => onPerPage(parseInt(select.value, 10)));
            size.append(label, select);
        }
        container.append(range, nav, size);
    }

    function storageKey(key) {
        return `perPage:${key}`;
    }

    /** This browser's "per page" for `key`, when it is one of `sizes`; else `fallback`. */
    function perPage(key, sizes, fallback) {
        try {
            const n = parseInt(localStorage.getItem(storageKey(key)), 10);
            return sizes.includes(n) ? n : fallback;
        } catch (e) {
            return fallback;
        }
    }

    function savePerPage(key, n) {
        try { localStorage.setItem(storageKey(key), String(n)); } catch (e) { /* this visit only */ }
    }

    window.Pager = {render, perPage, savePerPage, windowOf};
})();
