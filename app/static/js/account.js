/* My account (/account): saves the signed-in user's own preferences. Strings come from
   the page's inline I18N object. */

const FIRMWARE_RE = /^\d{1,2}\.\d{1,2}\.\d{1,2}$/;

function accountFeedback(text, ok) {
    const out = document.getElementById('accountFeedback');
    out.textContent = text;
    out.className = 'small ' + (ok ? 'text-success' : 'text-danger');
}

document.getElementById('accountForm').addEventListener('submit', async event => {
    event.preventDefault();
    const input = document.getElementById('accountFirmware');
    const firmware = input.value.trim();
    // The same check the server makes, so a typo is told before the round trip.
    const valid = !firmware || FIRMWARE_RE.test(firmware);
    input.classList.toggle('is-invalid', !valid);
    if (!valid) {
        accountFeedback(I18N.firmwareInvalid, false);
        input.focus();
        return;
    }
    const button = document.getElementById('accountSave');
    button.disabled = true;
    try {
        const r = await fetch('/api/account', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            credentials: 'same-origin',
            body: JSON.stringify({
                console_firmware: firmware,
                show_background_image: document.getElementById('accountBackground').value,
                show_verification: document.getElementById('accountVerification').value,
                language: document.getElementById('accountLanguage').value,
                // Only when offered (the email channel is on in Settings).
                ...(document.getElementById('accountNotifyEmail')
                    ? {notify_email: document.getElementById('accountNotifyEmail').checked} : {}),
            }),
        });
        const body = await r.json().catch(() => ({}));
        if (r.ok && body.success) {
            accountFeedback(I18N.saved, true);
            // A new language shows once the page is drawn again in it.
            const picked = document.getElementById('accountLanguage').value;
            if (picked !== 'auto' && picked !== document.documentElement.lang) setTimeout(() => location.reload(), 400);
        } else {
            input.classList.toggle('is-invalid', body.error === 'invalid_firmware');
            accountFeedback(body.error === 'invalid_firmware' ? I18N.firmwareInvalid : I18N.saveFailed, false);
        }
    } catch (e) {
        accountFeedback(I18N.saveFailed, false);
    } finally {
        button.disabled = false;
    }
});

// --- Email and password (accounts_views.py) ---------------------------------------------

function feedbackIn(id, text, ok) {
    const out = document.getElementById(id);
    out.textContent = text;
    out.className = 'small mt-1 ' + (ok ? 'text-success' : 'text-danger');
}

async function postJson(url, body) {
    const r = await fetch(url, {method: 'POST', credentials: 'same-origin',
                                headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
    return {ok: r.ok, body: await r.json().catch(() => ({}))};
}

document.getElementById('accountEmailSend').addEventListener('click', async () => {
    const {ok, body} = await postJson('/api/account/email',
                                      {email: document.getElementById('accountEmailInput').value.trim()})
        .catch(() => ({ok: false, body: {}}));
    feedbackIn('accountEmailFeedback', ok ? I18N.emailSent : body.error === 'too_many' ? I18N.tooMany
        : body.error === 'send_failed' ? I18N.emailSendFailed : I18N.emailFailed, ok);
});

document.getElementById('accountPasswordSave').addEventListener('click', async () => {
    const current = document.getElementById('accountPasswordCurrent');
    const {ok, body} = await postJson('/api/account/password', {
        current: current ? current.value : '', new: document.getElementById('accountPasswordNew').value,
    }).catch(() => ({ok: false, body: {}}));
    if (ok) {
        feedbackIn('accountPasswordFeedback', I18N.passwordSaved, true);
        document.getElementById('accountPasswordNew').value = '';
        if (current) current.value = '';
    } else {
        const text = body.error === 'too_many' ? I18N.tooMany
            : body.error === 'wrong_password' ? I18N.passwordWrong : (body.message || I18N.passwordWrong);
        feedbackIn('accountPasswordFeedback', text, false);
    }
});

// --- Save vault (vault.py): this user's own password and webdav.json ---------------------

const vaultSection = document.getElementById('accountVault');
if (vaultSection) {
    const password = document.getElementById('vaultPassword');
    const origin = document.getElementById('vaultOrigin');
    // The console needs the server's address on the network: the one the browser used,
    // unless that's localhost, which the user changes here.
    origin.value = window.location.origin;

    document.getElementById('vaultPasswordSave').addEventListener('click', async () => {
        const {ok} = await postJson('/api/account/vault', {password: password.value})
            .catch(() => ({ok: false}));
        feedbackIn('vaultPasswordFeedback', ok ? I18N.vaultSaved : I18N.vaultShort, ok);
    });

    // JKSV's webdav.json, made here in the browser: the password written above goes into
    // it, since the server never sends it back.
    document.getElementById('vaultDownloadWebdav').addEventListener('click', () => {
        const needs = document.getElementById('vaultNeedsPassword');
        needs.classList.toggle('d-none', Boolean(password.value));
        if (!password.value) {
            password.focus();
            return;
        }
        const base = origin.value.trim().replace(/\/+$/, '');
        const config = {origin: base + '/dav', basepath: 'JKSV', username: VAULT_USER, password: password.value};
        const blob = new Blob([JSON.stringify(config, null, 2) + '\n'], {type: 'application/json'});
        const link = document.createElement('a');
        link.href = URL.createObjectURL(blob);
        link.download = 'webdav.json';
        document.body.appendChild(link);
        link.click();
        link.remove();
        setTimeout(() => URL.revokeObjectURL(link.href), 1000);
    });
}

// --- Profile picture (avatars.py): a gallery avatar or an uploaded image ------------------

function showAvatar(url) {
    const preview = document.getElementById('avatarPreview');
    preview.replaceChildren();
    if (url) {
        const img = document.createElement('img');
        img.src = url;
        img.alt = '';
        img.width = img.height = 72;
        preview.append(img);
    } else {
        const icon = document.createElement('i');
        icon.className = 'bi bi-person-circle';
        icon.setAttribute('aria-hidden', 'true');
        preview.append(icon);
    }
    document.getElementById('avatarRemove').hidden = !url;
    // The top bar's picture follows on the next page; the selection shows here at once.
    document.querySelectorAll('.avatar-choice').forEach(b => {
        const on = Boolean(url) && url.endsWith(`/${b.dataset.avatar}.svg`);
        b.classList.toggle('is-selected', on);
        b.setAttribute('aria-pressed', String(on));
    });
}

async function saveAvatar(body, isFile) {
    const r = await fetch('/api/account/avatar', isFile
        ? {method: 'POST', credentials: 'same-origin', body}
        : {method: 'POST', credentials: 'same-origin', headers: {'Content-Type': 'application/json'},
           body: JSON.stringify(body)}).catch(() => null);
    const data = r ? await r.json().catch(() => ({})) : {};
    if (r && r.ok && data.success) {
        showAvatar(data.url);
        feedbackIn('avatarFeedback', I18N.avatarSaved, true);
    } else {
        feedbackIn('avatarFeedback', r && r.status === 413 ? I18N.avatarTooLarge : I18N.avatarFailed, false);
    }
}

document.querySelectorAll('.avatar-choice').forEach(button => {
    button.addEventListener('click', () => saveAvatar({gallery: button.dataset.avatar}, false));
});
document.getElementById('avatarRemove').addEventListener('click', () => saveAvatar({gallery: null}, false));
document.getElementById('avatarFile').addEventListener('change', event => {
    const file = event.target.files[0];
    if (!file) return;
    const form = new FormData();
    form.append('file', file);
    saveAvatar(form, true);
    event.target.value = '';
});
