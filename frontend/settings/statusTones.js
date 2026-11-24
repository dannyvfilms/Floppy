// Status chips (connected, active, needs attention) share one colour rule so a light theme never gets the
// pale text that only suits a dark card.

const darkText = { success: '#a7f3d0', warning: '#fde68a', info: '#c7d2fe', danger: '#fecaca' };
const lightText = { success: '#047857', warning: '#92400e', info: '#4338ca', danger: '#b91c1c' };

function brightness(value) {
  // Native dynamic colours are objects, not strings, so they have no brightness to read here.
  if (typeof value !== 'string') return null;
  const text = value.trim();
  let channels = null;
  const hex = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(text);
  if (hex) {
    const digits = hex[1].length === 3 ? [...hex[1]].map(digit => digit + digit).join('') : hex[1];
    channels = [0, 2, 4].map(start => parseInt(digits.slice(start, start + 2), 16));
  } else {
    const rgb = /^rgba?\(\s*(\d+)[\s,]+(\d+)[\s,]+(\d+)/i.exec(text);
    if (rgb) channels = [rgb[1], rgb[2], rgb[3]].map(Number);
  }
  return channels ? (0.299 * channels[0] + 0.587 * channels[1] + 0.114 * channels[2]) / 255 : null;
}

/** True or false when the palette's own colours say so, null when they cannot be read. */
function lightFromPalette(palette) {
  const source = palette || {};
  for (const key of ['background', 'surface']) {
    const level = brightness(source[key]);
    if (level !== null) return level > 0.6;
  }
  const text = brightness(source.text);
  return text === null ? null : text < 0.4;
}

/**
 * True when the app is showing a light theme. Pass the raw palette the app handed over, not one merged over
 * dark defaults, which would hide a light theme that leaves a colour out. Native themes hand over dynamic
 * colours that cannot be read, so the caller's `scheme` (from `useColorScheme()`, which the app keeps in step
 * with its chosen theme) decides there.
 */
export function isLightTheme(palette, scheme) {
  const fromPalette = lightFromPalette(palette);
  return fromPalette === null ? scheme === 'light' : fromPalette;
}

/** Chip text for a tone. `colors.isLight` wins when the view already decided, else it is judged here. */
export function toneText(colors, tone) {
  const light = colors?.isLight ?? isLightTheme(colors);
  return (light ? lightText : darkText)[tone];
}
