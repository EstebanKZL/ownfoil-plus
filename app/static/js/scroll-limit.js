// Show the first `visible` rows of a list and scroll the rest, sized from the rows as
// actually rendered - a fixed max-height in CSS can't know that a row wraps to two
// lines on a phone, or how tall a table header is.
//
//   limitVisibleRows(scrollContainer, 'li', 5)
//   limitVisibleRows(tableWrapper, 'tbody tr', 10)   // the header stays sticky (CSS)
function limitVisibleRows(container, rowSelector, visible) {
    if (!container) return;
    const apply = () => {
        const rows = container.querySelectorAll(rowSelector);
        if (rows.length <= visible) {
            container.style.maxHeight = '';
            container.classList.remove('rows-limited');
            return;
        }
        const top = container.getBoundingClientRect().top - container.scrollTop;
        container.style.maxHeight = Math.ceil(rows[visible].getBoundingClientRect().top - top) + 'px';
        container.classList.add('rows-limited');
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
