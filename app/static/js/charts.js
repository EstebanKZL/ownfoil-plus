// Small chart helpers for the Statistics page and the Dashboard: donuts, rings and bars
// drawn with CSS (conic-gradient, widths), no chart library - the UI works offline.
// Colors are design tokens, so every chart follows the style and the mode.

// One color per segment, in order; anything past the list repeats the last one. The
// palette is one hue in steps - the same in every style, and deliberately NOT the
// content-type colors, so a format's segment never reads as "update" or "DLC" (the
// donut's only user today is Statistics' format donut; type-colored charts pick each
// row's own token instead).
const CHART_COLORS = [100, 74, 50, 30, 14].map(
    share => `color-mix(in srgb, var(--op-info) ${share}%, var(--op-chart-track))`);

/** `part` as a percentage of `total`, one decimal; 0 when there is no total. */
function percent(part, total) {
    if (!total || total <= 0) return 0;
    return Math.round(1000 * (Number(part) || 0) / total) / 10;
}

/** A conic-gradient for a donut: one segment per value, colored in order. With nothing
 *  to draw (no values, or all zero) it is one neutral ring rather than NaN degrees. */
function donutGradient(values, colors) {
    const palette = colors || CHART_COLORS;
    const nums = (values || []).map(v => Math.max(0, Number(v) || 0));
    const total = nums.reduce((a, b) => a + b, 0);
    if (!total) return 'conic-gradient(var(--op-chart-track) 0deg 360deg)';
    let acc = 0;
    const stops = nums.map((v, i) => {
        const from = acc;
        acc += 360 * v / total;
        // The last segment always closes the circle, whatever the rounding.
        const to = i === nums.length - 1 ? 360 : acc;
        return `${palette[Math.min(i, palette.length - 1)]} ${from.toFixed(2)}deg ${to.toFixed(2)}deg`;
    });
    return `conic-gradient(${stops.join(', ')})`;
}

/** A conic-gradient for a progress ring at `pct` percent, in `color`. */
function ringGradient(pct, color) {
    const deg = Math.max(0, Math.min(100, Number(pct) || 0)) * 3.6;
    return `conic-gradient(${color || 'var(--op-ok)'} 0deg ${deg.toFixed(2)}deg, var(--op-chart-track) ${deg.toFixed(2)}deg 360deg)`;
}

/** A labelled bar: a track with a filled part, sized by percent. */
function percentBar(pct, tone) {
    const bar = document.createElement('div');
    bar.className = 'chart-bar' + (tone ? ` chart-bar--${tone}` : '');
    const fill = document.createElement('div');
    fill.className = 'chart-bar__fill';
    fill.style.width = `${Math.max(0, Math.min(100, Number(pct) || 0))}%`;
    bar.appendChild(fill);
    return bar;
}
