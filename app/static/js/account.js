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
            }),
        });
        const body = await r.json().catch(() => ({}));
        if (r.ok && body.success) {
            accountFeedback(I18N.saved, true);
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
