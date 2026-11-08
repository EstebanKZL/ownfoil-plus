// Give a list a frame of `visible` rows and scroll the rest, sized from the rows as
// actually rendered - a fixed height in CSS can't know that a row wraps to two lines on
// a phone, or how tall a table header is.
//
// The frame keeps that height with fewer rows too, empty included, so a card doesn't
// grow and shrink as its list fills. With no row to measure yet, the row pitch comes
// from the list's `--row-pitch` (CSS), else the last one measured.
//
//   limitVisibleRows(scrollContainer, 'li', 5)
//   limitVisibleRows(tableWrapper, 'tbody tr', 10)   // the header stays sticky (CSS)
function limitVisibleRows(container, rowSelector, visible) {
    if (!container) return;
    const apply = () => {
        // The "nothing yet" line is not a row: it would set the pitch.
        const rows = [...container.querySelectorAll(rowSelector)]
            .filter(row => !row.classList.contains('dash-list__empty'));
        const top = container.getBoundingClientRect().top - container.scrollTop;
        container.classList.add('rows-limited');
        container.style.maxHeight = '';
        if (rows.length > visible) {
            container.style.height = Math.ceil(rows[visible].getBoundingClientRect().top - top) + 'px';
            return;
        }
        let first = 0;
        if (rows.length) {
            const a = rows[0].getBoundingClientRect();
            first = a.top - top;
            const b = rows[1] && rows[1].getBoundingClientRect();
            container.__rowPitch = b ? b.top - a.top : a.height;
        }
        const css = parseFloat(getComputedStyle(container).getPropertyValue('--row-pitch'));
        const rem = parseFloat(getComputedStyle(document.documentElement).fontSize) || 16;
        const pitch = container.__rowPitch || (css ? css * rem : 0);
        container.style.height = pitch ? Math.ceil(first + pitch * visible) + 'px' : '';
    };
    apply();
    // Re-measure when the layout changes (window resize, rows wrapping differently).
    if (!container.__rowLimitObserver && window.ResizeObserver) {
        let frame = null;
        container.__rowLimitObserver = new ResizeObserver(() => {
            cancelAnimationFrame(frame);
            frame = requestAnimationFrame(apply);
        });
        container.__rowLimitObserver.observe(container.parentElement || container);
    }
    container.__rowLimitApply = apply;
}
