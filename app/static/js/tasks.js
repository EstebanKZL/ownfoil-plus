// The Tasks admin page (templates/tasks.html). The page renders its I18N strings and
// MAX_TASKS in its one inline script, then loads this file.

const CANCEL_MUTATION = `
    mutation Cancel($id: ID!) {
        cancelTask(id: $id)
    }`;

const DISMISS_MUTATION = `
    mutation Dismiss($id: ID!) {
        dismissTask(id: $id)
    }`;

const PURGE_MUTATION = `
    mutation Purge {
        purgeFailedTasks
    }`;

// Task rows the server has dropped. Kept on screen briefly so work that finishes
// does not simply blink out of existence, then faded and forgotten.
const FADE_AFTER_MS = 10000;

let tasks = {};      // id -> task, including ones being faded out
let workers = {};    // id -> worker
let renderQueued = false;
// Cancelling deletes the row, which reaches us as an ordinary removal. Remembering
// what we cancelled is what keeps it from being reported back as "finished".
const cancelled = new Set();

function scheduleRender() {
    // Several updates can land per second; coalesce them into one paint.
    if (renderQueued) return;
    renderQueued = true;
    requestAnimationFrame(() => { renderQueued = false; render(); });
}

async function mutate(query, variables) {
    const r = await fetch('/api/graphql', {
        method: 'POST',
        headers: {'Content-Type': 'application/json', 'Accept': 'application/json'},
        credentials: 'same-origin',
        body: JSON.stringify({query: query, variables: variables || {}}),
    });
    if (!r.ok) throw new Error(`GraphQL HTTP ${r.status}`);
    const body = await r.json();
    if (body.errors && body.errors.length) {
        throw new Error('GraphQL errors: ' + JSON.stringify(body.errors));
    }
    return body.data;
}

/** Undo an optimistic cancel mark, correcting the row if the removal already used it. */
function unmarkCancelled(key) {
    cancelled.delete(key);
    const task = tasks[key];
    if (task && task.cancelled) {
        task.cancelled = false;
        task.completionPct = 100;
        scheduleRender();
    }
}

async function cancelTask(id) {
    const key = String(id);
    $(`.task-cancel[data-id="${id}"]`).prop('disabled', true);
    // Marked before the request, not after it. Cancelling a *running* task restarts
    // its worker process, which takes far longer than the poll interval, so the row's
    // removal reaches us over the WebSocket well before this response does — and
    // markDone has to already know the row was cancelled rather than finished.
    cancelled.add(key);
    try {
        // False means it was already finished or failed, so it was never cancelled.
        if (!(await mutate(CANCEL_MUTATION, {id: key})).cancelTask) unmarkCancelled(key);
    } catch (e) {
        console.error(e);
        unmarkCancelled(key);
        $(`.task-cancel[data-id="${id}"]`).prop('disabled', false);
    }
}

/** Drop rows locally so the incoming removal has nothing left to dress up. */
function forget(keys) {
    // A dismissed failure is not an accomplishment: it should just go, without the
    // green tick and ten-second fade that markDone gives work that ran to the end.
    keys.forEach(key => { delete tasks[key]; });
    scheduleRender();
}

async function dismissTask(id) {
    const key = String(id);
    $(`.task-cancel[data-id="${id}"]`).prop('disabled', true);
    try {
        if ((await mutate(DISMISS_MUTATION, {id: key})).dismissTask) forget([key]);
    } catch (e) {
        console.error(e);
        $(`.task-cancel[data-id="${id}"]`).prop('disabled', false);
    }
}

async function purgeFailed() {
    const button = $('#purgeFailed').prop('disabled', true);
    try {
        await mutate(PURGE_MUTATION);
        forget(Object.values(tasks).filter(t => t.status === 'failed').map(t => String(t.id)));
    } catch (e) {
        console.error(e);
    } finally {
        button.prop('disabled', false);
    }
}

// --- Formatting ---

// Wall clock the rows are measured against. While the stream is down the task data
// is frozen, so the clock has to freeze with it — otherwise elapsed times climb and
// "3m left" counts down against numbers that stopped arriving, which reads as live
// progress on a page that is not receiving any.
let stoppedAt = null;

function clockNow() {
    return stoppedAt ?? Date.now();
}

function humanizeDuration(ms) {
    const s = Math.round(ms / 1000);
    if (s < 60) return `${s}s`;
    const m = Math.floor(s / 60);
    if (m < 60) return `${m}m ${s % 60}s`;
    const h = Math.floor(m / 60);
    if (h < 24) return `${h}h ${m % 60}m`;
    return `${Math.floor(h / 24)}d ${h % 24}h`;
}

function relativeTime(iso) {
    const delta = new Date(iso).getTime() - clockNow();
    return delta <= 0 ? I18N.dueNow : I18N.inDuration.replace('{d}', humanizeDuration(delta));
}

function taskMeta(task) {
    if (task.cancelled) return I18N.statusCancelled;
    if (task.done) return I18N.statusFinished;
    // The server's one fixed message (tasks.cleanup_tasks) is shown in the page language.
    if (task.status === 'failed' && task.errorMessage === 'Interrupted by application restart') return I18N.interrupted;
    if (task.status === 'failed') return task.errorMessage || I18N.statusFailed;
    if (task.runAfter) {
        return `${new Date(task.runAfter).toLocaleString()} — ${relativeTime(task.runAfter)}`;
    }
    if (!task.startedAt) return '';

    const elapsed = clockNow() - new Date(task.startedAt).getTime();
    let meta = I18N.runningFor.replace('{d}', humanizeDuration(elapsed));
    if (task.completionPct > 0 && task.completionPct < 100) {
        // The bar is too slim to hold a legible label, so the percentage lives here.
        const remaining = elapsed / (task.completionPct / 100) - elapsed;
        meta = `${task.completionPct}% — ${meta} — ${I18N.left.replace('{d}', humanizeDuration(remaining))}`;
    }
    return meta;
}

const ICONS = {
    cancelled: '<i class="bi bi-slash-circle-fill text-secondary"></i>',
    done:      '<i class="bi bi-check-circle-fill text-success"></i>',
    failed:    '<i class="bi bi-exclamation-circle-fill text-danger"></i>',
    pending:   '<i class="bi bi-hourglass-split text-secondary"></i>',
    running:   '<i class="bi bi-arrow-repeat spin text-info"></i>',
};

function statusIconKey(task) {
    if (task.cancelled) return 'cancelled';
    if (task.done) return 'done';
    if (task.status === 'failed') return 'failed';
    if (task.status === 'pending') return 'pending';
    return 'running';
}

// --- Rendering ---

// A task that finishes moves above the live rows and holds there until it fades out.
// The finished group runs oldest-finished first, so each new one lands at its end,
// right above the running rows. Live rows keep their oldest-first order below: they
// are claimed oldest-first, so it says what is running and what is waiting behind it.
function queueOrder(a, b) {
    if (!!a.done !== !!b.done) return a.done ? -1 : 1;
    return a.done ? a.finishSeq - b.finishSeq : a.id - b.id;
}

function childrenOf(id) {
    return Object.values(tasks).filter(t => t.parentId === id).sort(queueOrder);
}

function buildRow(task) {
    const li = document.createElement('li');
    li.className = 'task-row';
    li.dataset.id = task.id;
    li.innerHTML = `
        <div class="task-head">
            <span class="task-icon"></span>
            <span class="task-name"></span>
            <span class="task-meta text-secondary"></span>
            <button type="button" class="icon-btn task-cancel" data-id="${task.id}" title="${I18N.cancel}">
                <i class="bi bi-x-lg"></i>
            </button>
        </div>
        <div class="progress task-progress">
            <div class="progress-bar" role="progressbar"></div>
        </div>
        <ul class="task-children"></ul>`;
    // Resolved at click time, not here: a row that was queued when it was built can
    // have failed by the time the button is pressed, and the two need different calls.
    li.querySelector(':scope > .task-head > .task-cancel')
      .addEventListener('click', () => {
          const current = tasks[String(task.id)];
          if (current && current.status === 'failed') dismissTask(task.id);
          else cancelTask(task.id);
      });
    return li;
}

function updateRow(li, task) {
    // `:scope >` throughout: a row contains its sub-task rows, so an unanchored
    // selector could reach into a child's markup instead of this row's own.
    const own = sel => li.querySelector(`:scope > ${sel}`);

    li.classList.toggle('task-done', !!task.done);
    li.classList.toggle('task-failed', task.status === 'failed');

    // Rewritten only when it actually changes: replacing the element on every tick
    // restarts the spinner's CSS animation, which reads as a stutter.
    const icon = own('.task-head > .task-icon');
    const iconKey = statusIconKey(task);
    if (icon.dataset.icon !== iconKey) {
        icon.dataset.icon = iconKey;
        icon.innerHTML = ICONS[iconKey];
    }

    own('.task-head > .task-name').textContent = task.displayName;
    // A failed task's meta is its error message: cut to the row, whole in the tooltip.
    const meta = own('.task-head > .task-meta');
    meta.textContent = taskMeta(task);
    meta.title = meta.textContent;

    // Only a live row carries a bar: a queued one has nothing to report yet, and a
    // finished, cancelled or failed one says so in its icon and meta text already.
    const inFlight = !task.done && task.status !== 'pending' && task.status !== 'failed';
    own('.task-progress').classList.toggle('d-none', !inFlight);
    if (inFlight) {
        // A task with no reported percentage should not look stalled at 0%: only the
        // verify/compress/decompress tasks report real progress, everything else jumps
        // straight from queued to done.
        const bar = own('.task-progress > .progress-bar');
        bar.style.width = task.completionPct ? `${task.completionPct}%` : '100%';
        bar.className = 'progress-bar progress-bar-striped progress-bar-animated';
    }

    // `done` covers both finished and cancelled rows: the task is already gone
    // server-side, so the button has nothing to act on and is taken away. On a
    // failed row it stays, as the only way to clear a failure.
    const cancel = own('.task-head > .task-cancel');
    cancel.classList.toggle('d-none', !!task.done);
    cancel.title = task.status === 'failed' ? I18N.dismiss : I18N.cancel;
}

/** Sync a <ul> to a list of tasks, reusing rows so progress bars animate instead of flicker. */
function syncList(container, items) {
    const wanted = new Set(items.map(t => String(t.id)));
    Array.from(container.children).forEach(child => {
        if (!wanted.has(child.dataset.id)) child.remove();
    });
    const existing = {};
    Array.from(container.children).forEach(c => { existing[c.dataset.id] = c; });

    // Re-inserting a node restarts its CSS animations, so rows are walked against a
    // cursor and only moved where the order actually differs: a row that finishes
    // slots in above the live ones without disturbing their spinners.
    let cursor = container.firstChild;
    items.forEach(task => {
        let li = existing[String(task.id)];
        if (!li) li = buildRow(task);
        if (li === cursor) cursor = cursor.nextSibling;
        else container.insertBefore(li, cursor);
        updateRow(li, task);
        syncList(li.querySelector(':scope > .task-children'), childrenOf(task.id));
    });
    return items.length;
}

function section(listId, emptyId, items) {
    const count = syncList(document.getElementById(listId), items);
    document.getElementById(emptyId).classList.toggle('d-none', count > 0);
}

/** A small element with a class and plain text: task names never go in as HTML. */
function textNode(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = text;
    return node;
}

function renderWorkers() {
    const container = document.getElementById('workerCards');
    container.replaceChildren();
    const list = Object.values(workers).sort((a, b) => a.id - b.id);
    if (!list.length) {
        container.appendChild(textNode('p', 'text-secondary fst-italic mb-0', I18N.noWorkersReported));
        return;
    }
    list.forEach(worker => {
        const task = worker.taskId ? tasks[worker.taskId] : null;
        // One dot per state: working on something, waiting for work, or gone.
        const state = !worker.alive ? 'offline' : task ? 'busy' : 'idle';
        const col = textNode('div', 'col-md-6 col-xl-4');
        const card = textNode('div', 'worker-card surface h-100');
        const head = textNode('div', 'worker-card__head');
        const name = textNode('span', 'worker-card__name');
        name.append(textNode('span', `worker-dot worker-dot--${state}`), I18N.workerN.replace('{n}', worker.id));
        head.append(name, textNode('span', worker.alive ? 'worker-card__state' : 'worker-card__state worker-card__state--stopped', worker.alive ? I18N.alive : I18N.stopped));
        card.append(head, textNode('div', 'worker-card__pid', I18N.pid.replace('{pid}', worker.pid ?? '—')));
        const slot = textNode('div', 'worker-task');
        if (task) {
            slot.append(textNode('div', 'fw-semibold', task.displayName), textNode('div', 'text-secondary small', taskMeta(task)));
        } else {
            slot.appendChild(textNode('span', 'text-secondary fst-italic', I18N.idle));
        }
        card.appendChild(slot);
        col.appendChild(card);
        container.appendChild(col);
    });
}

function render() {
    // Sub-tasks are rendered nested under their parent, so the sections only list
    // roots — plus any child whose parent has already gone, which would vanish.
    const roots = Object.values(tasks)
        .filter(t => t.parentId === null || !(t.parentId in tasks))
        .sort(queueOrder);

    // Running and pending share one list, under the rows that just finished.
    section('queueTasks', 'queueEmpty', roots.filter(
        t => t.status !== 'failed' && !t.runAfter));
    section('scheduledTasks', 'scheduledEmpty', roots.filter(
        t => t.status === 'pending' && t.runAfter));
    const failed = roots.filter(t => t.status === 'failed');
    section('failedTasks', 'failedEmpty', failed);
    document.getElementById('purgeFailed').classList.toggle('d-none', !failed.length);

    // Queue and Failed frame 10 rows, Scheduled and History 5 (--task-rows in the page),
    // the rest by scrolling: the frames keep their height as rows come and go.
    renderQueueMore();
    renderWorkers();
}

// A full window: how many more open tasks wait behind the ones the page has, asked at
// most every 5 s (one COUNT on the server).
let queuedTotal = null;
let queuedAsked = 0;

function renderQueueMore() {
    const shown = Object.values(tasks).filter(t => t.status !== 'failed').length;
    const line = document.getElementById('queueMore');
    if (shown < MAX_TASKS) {
        line.classList.add('d-none');
        return;
    }
    if (Date.now() - queuedAsked > 5000) {
        queuedAsked = Date.now();
        fetch('/api/tasks/queued', {credentials: 'same-origin'})
            .then(r => r.ok ? r.json() : null)
            .then(d => { if (d) { queuedTotal = d.open; renderQueueMore(); } })
            .catch(() => {});
    }
    const more = queuedTotal === null ? 0 : queuedTotal - shown;
    line.classList.toggle('d-none', more <= 0);
    line.textContent = I18N.queueMore.replace('{n}', more.toLocaleString());
}

// --- Wiring ---

function upsert(task) {
    delete task.done;
    tasks[task.id] = task;
}

// Stamped on each row as it finishes, to order the finished group by end time: a task
// is deleted on completion rather than timestamped, so the row arrives here with no
// end time on it and the order these events land in is the only one there is.
let finishes = 0;

function markDone(task) {
    // The row is gone server-side: completed tasks are deleted rather than kept in a
    // terminal state, so completion is shown here and then dropped.
    const known = tasks[task.id];
    if (!known) return;
    const wasCancelled = cancelled.delete(String(task.id));
    Object.assign(known, task, {
        done: true,
        finishSeq: ++finishes,
        cancelled: wasCancelled,
        completionPct: wasCancelled ? known.completionPct : 100,
    });
    setTimeout(() => {
        const li = document.querySelector(`.task-row[data-id="${task.id}"]`);
        if (li) li.classList.add('task-fading');
        setTimeout(() => { delete tasks[task.id]; scheduleRender(); }, 600);
    }, FADE_AFTER_MS);
}

const live = new Realtime(['tasks', 'workers']);

live.on('tasks', (type, data) => {
    if (type === 'snapshot') {
        const faded = Object.values(tasks).filter(t => t.done);
        tasks = {};
        faded.forEach(t => { tasks[t.id] = t; });  // keep rows still fading out
        data.forEach(upsert);
    } else if (type === 'remove') {
        markDone(data);
    } else {
        upsert(data);
    }
    scheduleRender();
    // The top bar's counter is rendered at page load; keep it live here.
    const running = Object.values(tasks).filter(t => !t.done && t.status === 'running').length;
    ['navCountTasks', 'navCountTasksPhone'].forEach(id => {
        const navCount = document.getElementById(id);
        if (navCount) {
            navCount.textContent = running;
            navCount.hidden = !running;
        }
    });
});

live.on('workers', (type, data) => {
    if (type === 'snapshot') {
        workers = {};
        data.forEach(w => { workers[w.id] = w; });
    } else if (type === 'remove') {
        delete workers[data.id];
    } else {
        workers[data.id] = data;
    }
    scheduleRender();
});

live.onStatus(connected => {
    // Only stamp the first drop: this fires again on every failed reconnect, and
    // re-stamping would let the frozen clock creep forward with each attempt.
    if (connected) {
        stoppedAt = null;
    } else if (stoppedAt === null) {
        stoppedAt = Date.now();
    }
    scheduleRender();
});

live.start();

// Elapsed times and countdowns move on their own, without a server event — but only
// while connected, since nothing on a frozen page changes between ticks.
setInterval(() => { if (stoppedAt === null) scheduleRender(); }, 1000);

// --- History: completed top-level operations, fetched once (not part of the live
// task/worker stream - it's a plain log, not something that itself progresses). ---

const HISTORY_QUERY = `
    query { taskHistory(limit: 50) { id summary completedAt } }`;

function buildHistoryRow(entry) {
    const li = document.createElement('li');
    li.className = 'task-row';
    const head = document.createElement('div');
    head.className = 'task-head';
    head.innerHTML = '<i class="bi bi-check-circle-fill text-success task-icon"></i>';
    head.appendChild(Object.assign(document.createElement('span'), {
        className: 'task-name', textContent: entry.summary,
    }));
    head.appendChild(Object.assign(document.createElement('span'), {
        className: 'task-meta text-secondary',
        textContent: new Date(entry.completedAt).toLocaleString(),
    }));
    li.appendChild(head);
    return li;
}

async function loadHistory() {
    try {
        const r = await fetch('/api/graphql', {
            method: 'POST',
            headers: {'Content-Type': 'application/json', 'Accept': 'application/json'},
            credentials: 'same-origin',
            body: JSON.stringify({query: HISTORY_QUERY}),
        });
        if (!r.ok) throw new Error(`GraphQL HTTP ${r.status}`);
        const body = await r.json();
        if (body.errors && body.errors.length) {
            throw new Error('GraphQL errors: ' + JSON.stringify(body.errors));
        }
        const entries = body.data.taskHistory || [];
        const list = document.getElementById('historyList');
        list.innerHTML = '';
        entries.forEach(entry => list.appendChild(buildHistoryRow(entry)));
        document.getElementById('historyEmpty').classList.toggle('d-none', entries.length > 0);
        document.getElementById('clearHistory').classList.toggle('d-none', !entries.length);
    } catch (e) {
        console.error(e);
    }
}

document.getElementById('refreshHistory').addEventListener('click', loadHistory);
document.getElementById('clearHistory').addEventListener('click', async () => {
    if (!confirm(I18N.clearHistoryConfirm)) return;
    await fetch('/api/tasks/history', {method: 'DELETE', credentials: 'same-origin'});
    loadHistory();
});
loadHistory();
