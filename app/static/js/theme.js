// Light / dark / auto theme. Loaded synchronously in <head> (base.html) so the right
// theme is applied before the first paint - no flash of the wrong colors. The choice is
// a per-browser preference, kept in localStorage; dark stays the default, as before.
(function () {
    const KEY = 'theme';
    const media = window.matchMedia('(prefers-color-scheme: dark)');

    function stored() {
        try {
            const value = localStorage.getItem(KEY);
            return ['light', 'dark', 'auto'].includes(value) ? value : 'dark';
        } catch (e) {
            return 'dark';
        }
    }

    function apply(mode) {
        const resolved = mode === 'auto' ? (media.matches ? 'dark' : 'light') : mode;
        document.documentElement.setAttribute('data-bs-theme', resolved);
        document.querySelectorAll('[data-theme-choice]').forEach(item => {
            item.classList.toggle('active', item.dataset.themeChoice === mode);
        });
        document.querySelectorAll('[data-theme-icon]').forEach(icon => {
            icon.className = 'bi ' + {light: 'bi-sun', dark: 'bi-moon-stars', auto: 'bi-circle-half'}[mode];
        });
    }

    window.setTheme = function (mode) {
        try { localStorage.setItem(KEY, mode); } catch (e) { /* private mode: this page only */ }
        apply(mode);
    };

    apply(stored());
    media.addEventListener('change', () => { if (stored() === 'auto') apply('auto'); });
    // The navbar's menu doesn't exist yet when this runs in <head>: mark it once it does.
    document.addEventListener('DOMContentLoaded', () => apply(stored()));
})();
