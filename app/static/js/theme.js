// Light / dark / auto theme and color style. Loaded synchronously in <head> (base.html)
// so the right colors are applied before the first paint - no flash of the wrong ones.
// Both are per-browser preferences, kept in localStorage; dark stays the default mode.
// The style starts from the admin's default, rendered by the server as <html data-style>
// (Settings > Appearance); a browser that picks its own keeps it until it goes back to
// the server's.
(function () {
    const KEY = 'theme';
    const STYLE_KEY = 'style';
    const STYLES = ['ownfoil', 'neon', 'joycon'];
    const media = window.matchMedia('(prefers-color-scheme: dark)');
    const root = document.documentElement;
    let serverStyle = STYLES.includes(root.dataset.style) ? root.dataset.style : 'joycon';

    function stored() {
        try {
            const value = localStorage.getItem(KEY);
            return ['light', 'dark', 'auto'].includes(value) ? value : 'dark';
        } catch (e) {
            return 'dark';
        }
    }

    // Only a known style counts: anything else (an old version's value, a typo) falls
    // back to the server's, never to a page without accent colors.
    function storedStyle() {
        try {
            const value = localStorage.getItem(STYLE_KEY);
            return STYLES.includes(value) ? value : null;
        } catch (e) {
            return null;
        }
    }

    function apply(mode) {
        const resolved = mode === 'auto' ? (media.matches ? 'dark' : 'light') : mode;
        root.setAttribute('data-bs-theme', resolved);
        document.querySelectorAll('[data-theme-choice]').forEach(item => {
            item.classList.toggle('active', item.dataset.themeChoice === mode);
        });
        document.querySelectorAll('[data-theme-icon]').forEach(icon => {
            icon.className = 'bi ' + {light: 'bi-sun', dark: 'bi-moon-stars', auto: 'bi-circle-half'}[mode];
        });
    }

    function applyStyle() {
        const own = storedStyle();
        root.setAttribute('data-style', own || serverStyle);
        document.querySelectorAll('[data-style-choice]').forEach(item => {
            item.classList.toggle('active', item.dataset.styleChoice === (own || 'server'));
        });
    }

    window.setTheme = function (mode) {
        try { localStorage.setItem(KEY, mode); } catch (e) { /* private mode: this page only */ }
        apply(mode);
    };

    // Anything but a known style ('server', null) goes back to the admin's default.
    window.setStyle = function (style) {
        try {
            if (STYLES.includes(style)) localStorage.setItem(STYLE_KEY, style);
            else localStorage.removeItem(STYLE_KEY);
        } catch (e) { /* private mode: this page only */ }
        applyStyle();
    };

    // Settings > Appearance changed the default: follow it unless this browser chose.
    window.setServerStyle = function (style) {
        if (STYLES.includes(style)) serverStyle = style;
        applyStyle();
    };

    apply(stored());
    applyStyle();
    media.addEventListener('change', () => { if (stored() === 'auto') apply('auto'); });
    // The navbar's menu doesn't exist yet when this runs in <head>: mark it once it does.
    // Pages with the phone's bottom bar (admins) get room for it at the bottom.
    document.addEventListener('DOMContentLoaded', () => {
        apply(stored());
        applyStyle();
        if (document.querySelector('.bottom-nav')) document.body.classList.add('has-bottom-nav');
    });
})();
