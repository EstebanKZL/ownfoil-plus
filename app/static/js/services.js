/* Services (/admin/services): each service's switch turns it on or off at once
   (/api/services/<id>), and its card shows the state the server answers with. Strings
   come from the page's inline I18N object. */

function showServiceState(card, enabled) {
    card.classList.toggle('is-on', enabled);
    const state = card.querySelector('.service-card__state');
    state.textContent = enabled ? I18N.serviceOn : I18N.serviceOff;
    state.classList.toggle('status-badge--ok', enabled);
    card.querySelector('.service-switch').checked = enabled;
}

document.querySelectorAll('.service-switch').forEach(input => {
    input.addEventListener('change', async () => {
        const card = input.closest('.service-card');
        const wanted = input.checked;
        input.disabled = true;
        try {
            const r = await fetch(`/api/services/${encodeURIComponent(card.dataset.service)}`, {
                method: 'POST', credentials: 'same-origin',
                headers: {'Content-Type': 'application/json'}, body: JSON.stringify({enabled: wanted}),
            });
            const body = await r.json();
            if (!r.ok || !body.success) throw new Error(body.error || `HTTP ${r.status}`);
            showServiceState(card, body.enabled);
        } catch (e) {
            // Back to how it was: nothing changed on the server.
            showServiceState(card, !wanted);
            alert(I18N.serviceFailed);
        } finally {
            input.disabled = false;
        }
    });
});
