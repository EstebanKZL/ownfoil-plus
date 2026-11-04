/* Lists of games, one row each: the game's icon, its name, a muted detail line and a
   figure on the right (a time, a size, a count). Shared by the Dashboard and the
   Statistics page so their lists read the same; styles are the `.dash-list` ones.
   A row with a title id leads to the game's page. */

/**
 * One row for a `<ul class="dash-list">`.
 *   main     the name (required)
 *   sub      the muted line under it (optional)
 *   side     the figure on the right (optional)
 *   titleId  links the row to /game/<id>; its icon comes later from fillTitleIcons
 *   iconUrl  an icon already known (no request needed)
 *   glyph    the Bootstrap icon shown when there is no game picture (default: a controller)
 *   avatarUrl  a person's picture instead (round)
 *   rank     a place number before the icon (1, 2, 3 stand out)
 *   pct      a share bar under the name, 0-100
 *   chips    small labels after the name: [{text, glyph, avatarUrl}]
 */
function titleListRow({main, sub, side, titleId, iconUrl, glyph, avatarUrl, rank, pct, chips}) {
    const make = (tag, className, text) => {
        const node = document.createElement(tag);
        node.className = className;
        if (text !== undefined && text !== null) node.textContent = text;
        return node;
    };
    const li = make('li', 'dash-list__item');
    const row = make(titleId ? 'a' : 'div', 'dash-list__row');
    if (titleId) row.href = `/game/${titleId}`;
    if (rank !== undefined) row.append(make('span', `dash-list__rank${rank <= 3 ? ' is-top' : ''}`, rank));
    const icon = make('span', avatarUrl ? 'dash-list__icon dash-list__icon--person' : 'dash-list__icon');
    if (avatarUrl) {
        const img = document.createElement('img');
        img.src = avatarUrl;
        img.alt = '';
        img.loading = 'lazy';
        icon.append(img);
    } else if (iconUrl) {
        const img = document.createElement('img');
        img.src = iconUrl;
        img.alt = '';
        img.loading = 'lazy';
        icon.append(img);
    } else {
        icon.append(make('i', `bi ${glyph || 'bi-controller'}`));
        if (titleId) icon.dataset.titleIcon = titleId;
    }
    const text = make('div', 'dash-list__text');
    text.append(make('div', 'dash-list__name', main));
    if (sub) {
        text.append(make('div', 'dash-list__sub', sub));
        text.title = sub;
    }
    if (chips && chips.length) {
        const line = make('div', 'dash-list__chips');
        chips.forEach(chip => {
            const tag = make('span', 'dash-list__chip');
            if (chip.avatarUrl) {
                const img = document.createElement('img');
                img.src = chip.avatarUrl;
                img.alt = '';
                tag.append(img);
            } else if (chip.glyph) {
                tag.append(make('i', `bi ${chip.glyph}`));
            }
            tag.append(document.createTextNode(chip.text));
            line.append(tag);
        });
        text.append(line);
    }
    if (pct !== undefined) {
        const bar = make('span', 'dash-list__bar');
        const fill = make('span', 'dash-list__bar-fill');
        fill.style.width = `${Math.max(2, Math.min(100, pct))}%`;
        bar.append(fill);
        text.append(bar);
    }
    row.append(icon, text);
    if (side !== undefined && side !== null && side !== '') row.append(make('div', 'dash-list__when', side));
    li.append(row);
    return li;
}

/** The empty-list line, in the same style. */
function titleListEmpty(text) {
    const li = document.createElement('li');
    li.className = 'dash-list__empty';
    li.textContent = text;
    return li;
}

/** Puts each game's icon into the `[data-title-icon]` placeholders under `root`: one
 *  GraphQL request for all of them. The ids go into the query text as aliases, so only
 *  well-formed title ids are used. A game with no known icon keeps its glyph. */
async function fillTitleIcons(root) {
    const spots = [...(root || document).querySelectorAll('[data-title-icon]')];
    const ids = [...new Set(spots.map(span => span.dataset.titleIcon.toUpperCase()))]
        .filter(id => /^[0-9A-F]{16}$/.test(id)).slice(0, 60);
    if (!ids.length) return;
    const query = '{ ' + ids.map((id, i) => `t${i}: title(titleId: "${id}") { titleId iconUrl }`).join(' ') + ' }';
    let data;
    try {
        const r = await fetch('/api/graphql?' + new URLSearchParams({query}), {credentials: 'same-origin'});
        data = (await r.json()).data || {};
    } catch (e) {
        return;   // the glyph stays: icons are a nicety
    }
    const icons = {};
    Object.values(data).forEach(t => { if (t && t.iconUrl) icons[t.titleId.toUpperCase()] = t.iconUrl; });
    spots.forEach(span => {
        const url = icons[span.dataset.titleIcon.toUpperCase()];
        if (!url) return;
        const img = document.createElement('img');
        img.src = url;
        img.alt = '';
        img.loading = 'lazy';
        span.replaceChildren(img);
        delete span.dataset.titleIcon;
    });
}
