/** Byte counts as a human-readable string. Binary units, so the numbers agree with
 *  what a file manager reports rather than with the disk vendor's arithmetic. */
/** The "{s}" of a counted string ("{n} file{s}"): an "s" for more than one, only in the
 *  page languages whose plural takes one (French "fichiers", but German "Dateien",
 *  Japanese none), so it never sticks to a word that doesn't take it. */
function pluralS(count) {
    const lang = (document.documentElement.lang || 'en').split('-')[0];
    return count !== 1 && ['en', 'es', 'fr', 'pt'].includes(lang) ? 's' : '';
}

function formatBytes(bytes) {
    const units = ['B', 'KiB', 'MiB', 'GiB', 'TiB', 'PiB'];
    let n = Number(bytes) || 0;
    let unit = 0;
    while (n >= 1024 && unit < units.length - 1) { n /= 1024; unit++; }
    return `${unit && n < 100 ? n.toFixed(1) : Math.round(n)} ${units[unit]}`;
}
