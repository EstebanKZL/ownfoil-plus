// Installable app (see templates/sw.js). Browsers only allow a service worker on HTTPS
// or localhost, so on a plain-http LAN address this quietly does nothing.
if ('serviceWorker' in navigator && window.isSecureContext) {
    window.addEventListener('load', () => navigator.serviceWorker.register('/sw.js').catch(() => {}));
}

// The navbar's "Install app" button (nav.html) only shows once the browser offers it.
window.addEventListener('beforeinstallprompt', event => {
    event.preventDefault();
    window.__installPrompt = event;
    document.querySelectorAll('.install-app-btn').forEach(b => b.classList.remove('d-none'));
});

function installApp() {
    if (!window.__installPrompt) return;
    window.__installPrompt.prompt();
    window.__installPrompt.userChoice.finally(() => {
        window.__installPrompt = null;
        document.querySelectorAll('.install-app-btn').forEach(b => b.classList.add('d-none'));
    });
}
