// Resumable uploads from the browser (see uploads.py and the _upload_modal.html partial,
// which holds the dialog and its strings). Included by the pages that offer uploading;
// a page that wants to react to a finished upload listens for `upload:finished`.
(function () {
    const UP = JSON.parse(document.getElementById('uploadStrings').textContent);
    const MIN_CHUNK = 512 * 1024;
    let uploadChunk = 8 * 1024 * 1024;
    const uploadItems = [];
    let uploadRunning = false;

    function uploadErrorText(body, status) {
        return (body && UP.errors[body.error]) || (body && body.message) || ('HTTP ' + status);
    }

    function renderUploadItem(item) {
        const pct = item.file.size ? Math.floor(100 * item.offset / item.file.size) : 0;
        item.el.find('.upload-bar').css('width', pct + '%')
            .toggleClass('bg-success', item.state === 'done')
            .toggleClass('bg-danger', item.state === 'failed');
        let detail = formatBytes(item.offset) + ' / ' + formatBytes(item.file.size) + ' · ' + pct + '%';
        if (item.state === 'uploading' && item.speed) detail += ' · ' + formatBytes(item.speed) + '/s';
        item.el.find('.upload-detail').text(detail);
        item.el.find('.upload-state').text(item.error || UP[item.state] || '')
            .toggleClass('text-danger', item.state === 'failed');
        item.el.find('.upload-pause')
            .text(item.state === 'paused' || item.state === 'failed' ? UP.resume : UP.pause)
            .prop('hidden', item.state === 'done' || item.state === 'queued');
        item.el.find('.upload-cancel').prop('hidden', item.state === 'done');
    }

    function addUploadFiles(files) {
        const library = $('#uploadLibrarySelect').val();
        Array.from(files).forEach(file => {
            const el = $('<li class="list-group-item">' +
                '<div class="d-flex justify-content-between gap-2">' +
                '<span class="upload-name text-truncate"></span>' +
                '<span class="d-flex gap-1 flex-shrink-0">' +
                '<button type="button" class="btn btn-sm btn-outline-secondary upload-pause" hidden></button>' +
                '<button type="button" class="btn btn-sm btn-outline-danger upload-cancel"></button>' +
                '</span></div>' +
                '<div class="progress mt-2" style="height: .5rem;"><div class="progress-bar upload-bar"></div></div>' +
                '<div class="d-flex justify-content-between small mt-1">' +
                '<span class="upload-detail text-secondary"></span><span class="upload-state"></span>' +
                '</div></li>');
            el.find('.upload-name').text(file.name).attr('title', file.name);
            el.find('.upload-cancel').text(UP.cancel);
            const item = {file, library, el, offset: 0, state: 'queued', id: null, error: null};
            el.find('.upload-pause').on('click', () => {
                if (item.state === 'uploading') {
                    item.state = 'paused';
                } else {
                    item.state = 'queued';
                    item.error = null;
                    runUploads();
                }
                renderUploadItem(item);
            });
            el.find('.upload-cancel').on('click', () => cancelUploadItem(item));
            uploadItems.push(item);
            $('#uploadQueue').append(el);
            renderUploadItem(item);
        });
        runUploads();
    }

    async function cancelUploadItem(item) {
        item.state = 'cancelled';
        if (item.id) {
            await fetch('/api/uploads/' + item.id, {method: 'DELETE', credentials: 'same-origin'});
        }
        item.el.remove();
        uploadItems.splice(uploadItems.indexOf(item), 1);
        loadPendingUploads();
    }

    async function runUploads() {
        if (uploadRunning) return;
        uploadRunning = true;
        try {
            let item;
            while ((item = uploadItems.find(i => i.state === 'queued'))) {
                await uploadOne(item);
            }
        } finally {
            uploadRunning = false;
            loadPendingUploads();
        }
    }

    async function uploadOne(item) {
        item.state = 'uploading';
        renderUploadItem(item);
        const startResp = await fetch('/api/uploads', {
            method: 'POST', credentials: 'same-origin', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({library: item.library, filename: item.file.name, size: item.file.size}),
        }).catch(() => null);
        const start = startResp ? await startResp.json().catch(() => null) : null;
        if (!startResp || !startResp.ok || !start || !start.success) {
            item.state = 'failed';
            item.error = uploadErrorText(start, startResp ? startResp.status : 0);
            return renderUploadItem(item);
        }
        item.id = start.id;
        item.offset = start.offset;   // > 0 when resuming an earlier, interrupted upload
        let failures = 0;
        let windowStart = performance.now();
        let windowBytes = 0;
        while (item.offset < item.file.size) {
            if (item.state !== 'uploading') return renderUploadItem(item);
            const end = Math.min(item.offset + uploadChunk, item.file.size);
            let resp = null;
            let body = null;
            try {
                resp = await fetch('/api/uploads/' + item.id, {
                    method: 'PATCH', credentials: 'same-origin',
                    headers: {'Upload-Offset': String(item.offset),
                              'Content-Type': 'application/offset+octet-stream'},
                    body: item.file.slice(item.offset, end),
                });
                body = await resp.json().catch(() => null);
            } catch (e) {
                // Network error: retried below.
            }

            if (resp && resp.ok && body && body.success) {
                windowBytes += end - item.offset;
                item.offset = body.offset;
                failures = 0;
                const elapsed = (performance.now() - windowStart) / 1000;
                if (elapsed > 1) {
                    item.speed = windowBytes / elapsed;
                    windowStart = performance.now();
                    windowBytes = 0;
                }
                renderUploadItem(item);
                continue;
            }
            if (resp && resp.status === 409 && body && body.error === 'offset_mismatch') {
                item.offset = body.offset;   // the server knows better: carry on from there
                continue;
            }
            if (resp && resp.status === 413 && uploadChunk > MIN_CHUNK) {
                uploadChunk = Math.max(MIN_CHUNK, Math.floor(uploadChunk / 2));   // a proxy's body limit
                continue;
            }
            if (resp && resp.status >= 400 && resp.status < 500 && resp.status !== 408 && resp.status !== 429) {
                item.state = 'failed';
                item.error = uploadErrorText(body, resp.status);
                return renderUploadItem(item);
            }
            failures += 1;
            if (failures > 5) {
                item.state = 'failed';
                item.error = uploadErrorText(body, resp ? resp.status : 0);
                return renderUploadItem(item);
            }
            await new Promise(r => setTimeout(r, 1000 * 2 ** failures));
            const status = await fetch('/api/uploads/' + item.id, {credentials: 'same-origin'})
                .then(r => r.json()).catch(() => null);
            if (status && status.success) item.offset = status.offset;
        }
        item.state = 'done';
        item.speed = null;
        renderUploadItem(item);
        document.dispatchEvent(new CustomEvent('upload:finished', {detail: {name: item.file.name}}));
    }

    function loadPendingUploads() {
        $.getJSON('/api/uploads', data => {
            const select = $('#uploadLibrarySelect');
            if (!select.children().length) {
                data.libraries.forEach(path => select.append($('<option>').val(path).text(path)));
            }
            const active = new Set(uploadItems.map(i => i.id).filter(Boolean));
            const pending = data.uploads.filter(u => !active.has(u.id));
            const list = $('#uploadPending').empty();
            pending.forEach(u => {
                const pct = Math.floor(100 * u.offset / u.size);
                const li = $('<li class="list-group-item d-flex justify-content-between align-items-center gap-2">');
                li.append($('<span class="text-truncate">').attr('title', u.library)
                    .text(u.filename + ' · ' + pct + '% (' + formatBytes(u.offset) + ' / ' + formatBytes(u.size) + ')'));
                li.append($('<button type="button" class="btn btn-sm btn-outline-danger flex-shrink-0">')
                    .text(UP.discard)
                    .on('click', () => fetch('/api/uploads/' + u.id, {method: 'DELETE', credentials: 'same-origin'})
                        .then(loadPendingUploads)));
                list.append(li);
            });
            $('#uploadPendingBlock').prop('hidden', !pending.length);
        });
    }

    $('#uploadModal').on('show.bs.modal', loadPendingUploads);
    $('#uploadFileInput').on('change', function () {
        addUploadFiles(this.files);
        this.value = '';
    });
    $('#uploadDrop')
        .on('dragover', e => { e.preventDefault(); $('#uploadDrop').addClass('dragging'); })
        .on('dragleave drop', () => $('#uploadDrop').removeClass('dragging'))
        .on('drop', e => { e.preventDefault(); addUploadFiles(e.originalEvent.dataTransfer.files); });
    window.addEventListener('beforeunload', e => {
        if (uploadItems.some(i => i.state === 'uploading')) {
            e.preventDefault();
            e.returnValue = UP.leaveWarning;
        }
    });
})();
