// Helpers shared by the Library (library.js) and the game page (game.js): GraphQL
// calls, catalogue value formatting and the status/verification badges. Loaded before
// either page's own script.

async function gqlFetch(query, variables) {
    // GET (not POST) so the browser's HTTP cache automatically revalidates
    // via If-None-Match against the ETag the server sets on every response.
    const params = new URLSearchParams({query});
    if (variables && Object.keys(variables).length) {
        params.set('variables', JSON.stringify(variables));
    }
    const r = await fetch('/api/graphql?' + params.toString(), {
        method: 'GET',
        headers: {'Accept': 'application/json'},
        credentials: 'same-origin',
    });
    if (!r.ok) throw new Error(`GraphQL HTTP ${r.status}`);
    const body = await r.json();
    if (body.errors && body.errors.length) {
        throw new Error('GraphQL errors: ' + JSON.stringify(body.errors));
    }
    return body.data;
}

async function gqlMutate(query, variables) {
    const r = await fetch('/api/graphql', {
        method: 'POST',
        headers: {'Content-Type': 'application/json', 'Accept': 'application/json'},
        credentials: 'same-origin',
        body: JSON.stringify({query, variables}),
    });
    if (!r.ok) throw new Error(`GraphQL HTTP ${r.status}`);
    const body = await r.json();
    if (body.errors && body.errors.length) {
        throw new Error('GraphQL errors: ' + JSON.stringify(body.errors));
    }
    return body.data;
}

/** titledb's release_date column is the raw "YYYYMMDD" digit string, with no
 *  formatting applied anywhere upstream - shown as-is it reads as a meaningless
 *  number. Anything that doesn't match that exact shape is shown unchanged rather
 *  than mangled, since the catalogue isn't perfectly consistent about it. */
function formatTitledbDate(raw) {
    if (!raw) return null;
    const match = /^(\d{4})(\d{2})(\d{2})$/.exec(String(raw).trim());
    if (!match) return raw;
    const [, year, month, day] = match;
    return `${day}/${month}/${year}`;
}

/** titledb's own `size` field is a raw byte count as a string (per the schema's
 *  own note, "not reliably numeric") - formatted through the same formatBytes()
 *  every real file size in this app already goes through, for one consistent
 *  unit style site-wide. Left as-is when it isn't a plain number, since some
 *  catalogue entries already carry a pre-formatted string. */
function formatTitledbSize(raw) {
    if (raw == null || raw === '') return null;
    const n = Number(raw);
    return Number.isFinite(n) && n > 0 ? formatBytes(n) : raw;
}

function statusBadge(tone, icon, label) {
    const badge = $('<span class="status-badge">').addClass(tone ? `status-badge--${tone}` : '');
    if (icon) badge.append($('<i aria-hidden="true">').addClass(`bi ${icon}`));
    return badge.append($('<span>').text(label));
}

const VERIFICATION_BADGES = {
    VALID: ['bi-check-circle-fill', 'text-success', 'Valid'],
    REPACK: ['bi-arrow-repeat', 'text-warning', 'Repack'],
    SIGNATURE_OK: ['bi-shield-check', 'text-success', 'Signature ok'],
    SIGNATURE_FAILED: ['bi-shield-x', 'text-danger', 'Signature failed'],
    MODIFIED: ['bi-exclamation-triangle-fill', 'text-warning', 'Modified'],
    CORRUPT: ['bi-x-octagon-fill', 'text-danger', 'Corrupt'],
    UNVERIFIED: ['bi-question-circle', 'text-secondary', 'Unverified'],
};

/** A small colored icon reflecting what verifying the file itself found - not
 *  user-controlled text, so building it as an HTML string is safe here. Shown only
 *  for an owned row; there is nothing to verify for something missing. */
function verificationBadge(status) {
    if (!status) return null;
    const [icon, cls, label] = VERIFICATION_BADGES[status] || VERIFICATION_BADGES.UNVERIFIED;
    return $(`<i class="bi ${icon} ${cls}" data-bs-toggle="tooltip" data-bs-placement="top" title="${label}"></i>`);
}

/** A download icon-button, only ever built when the caller has already confirmed
 *  the admin toggle is on and the row is actually owned - see WEB_DOWNLOADS_ENABLED
 *  and IS_SHOP below (any user with shop access, admin or not - see access_shop()
 *  in app.py). The endpoint itself re-checks both regardless. */
function downloadButton(fileId, label) {
    const btn = $(`<a class="btn btn-sm icon-btn p-0" data-bs-toggle="tooltip" data-bs-placement="top" title="${I18N.downloadTooltip}"><i class="bi bi-download"></i></a>`);
    btn.attr('href', `/api/library/download/${fileId}`);
    btn.attr('aria-label', I18N.downloadAria.replace('{name}', label));
    return btn;
}
