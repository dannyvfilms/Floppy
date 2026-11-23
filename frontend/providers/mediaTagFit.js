// How many media tags fit on one line. When some are hidden a "+N" chip takes
// the last slot, so room is kept for it. `widths` are the measured tag widths
// in px, `plusWidths[n]` is the measured width of the "+n" chip (n = how many
// tags are hidden), and `gap` is the space between chips. Returns how many
// tags to show.
export function visibleTagCount({ widths, plusWidths, available, gap = 8 }) {
  const total = widths.length;
  if (!total || !(available > 0)) return total;
  let used = 0;
  let shown = 0;
  for (let index = 0; index < total; index += 1) {
    const next = used + (shown ? gap : 0) + widths[index];
    const hiddenAfter = total - index - 1;
    const needed = hiddenAfter ? next + gap + (plusWidths[hiddenAfter] || 0) : next;
    if (needed > available) break;
    used = next;
    shown += 1;
  }
  return shown;
}
