// On a phone the admin sidebar is one horizontally scrolling row of tabs (style.css):
// bring the current page's tab into view, so "Stats" isn't hidden off the right edge.
document.addEventListener('DOMContentLoaded', () => {
    const active = document.querySelector('.settings-sidebar .nav-link.active');
    const row = active && active.closest('.nav');
    if (row && row.scrollWidth > row.clientWidth) {
        row.scrollLeft = active.offsetLeft - (row.clientWidth - active.offsetWidth) / 2;
    }
});
