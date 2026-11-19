// Theme resolution shared by every platform. Pure JavaScript: no react-native
// import, so it is unit tested. The six states of docs/architecture/theming.md
// are `system`, `light`, `dark`, the ten presets and `custom`; only `system`
// follows the operating system, everything else is explicit.
//
// Token values for presets come from src/static/css/input.css (the html.<preset>
// blocks). Glass is translucent on the web; native has no backdrop blur, so its
// page colour is the opaque navy the glass overlay sits on.

export const DARK = {
  background: '#212529',
  // The side menu's own colour: --color-sidebar on the web.
  sidebar: '#1a1d20',
  surface: '#2a2f35',
  surfaceStrong: '#39404b',
  surfaceDim: '#262a2f',
  panel: '#272c31',
  surfaceMuted: '#3e454d',
  border: '#2c3136',
  surfaceBorder: '#454d59',
  text: '#f3f4f6',
  textSecondary: '#d1d5db',
  textMuted: '#adb5bd',
  accent: '#4a9eff',
  accentContrast: '#111827',
  link: '#a5b4fc',
  dangerText: '#f87171',
};

export const LIGHT = {
  background: '#f8f9fa',
  sidebar: '#f1f3f5',
  surface: '#ffffff',
  surfaceStrong: '#e9ecef',
  surfaceDim: '#dee2e6',
  panel: '#f8f9fa',
  surfaceMuted: '#dee2e6',
  border: '#dee2e6',
  surfaceBorder: '#ced4da',
  text: '#212529',
  textSecondary: '#495057',
  textMuted: '#6c757d',
  accent: '#4a9eff',
  accentContrast: '#111827',
  link: '#4f46e5',
  dangerText: '#b91c1c',
};

function preset(background, surface, surfaceStrong, surfaceMuted, border, text, textSecondary, textMuted, accent, accentContrast, link) {
  return { background, sidebar: background, surface, surfaceStrong, surfaceMuted, border, text, textSecondary, textMuted, accent, accentContrast, link };
}

export const PRESETS = {
  catppuccin_mocha: preset('#1e1e2e', '#313244', '#45475a', '#45475a', '#45475a', '#cdd6f4', '#bac2de', '#a6adc8', '#cba6f7', '#11111b', '#89b4fa'),
  dracula: preset('#282a36', '#343746', '#44475a', '#44475a', '#44475a', '#f8f8f2', '#e2e2dc', '#b7bdd5', '#bd93f9', '#21222c', '#8be9fd'),
  nord: preset('#2e3440', '#3b4252', '#434c5e', '#4c566a', '#3b4252', '#eceff4', '#d8dee9', '#b9c1d0', '#88c0d0', '#242933', '#81a1c1'),
  gruvbox: preset('#282828', '#3c3836', '#504945', '#665c54', '#3c3836', '#ebdbb2', '#d5c4a1', '#bdae93', '#fabd2f', '#1d2021', '#83a598'),
  oled: preset('#000000', '#0a0a0a', '#171717', '#1f1f1f', '#171717', '#ffffff', '#e5e5e5', '#a3a3a3', '#22d3ee', '#000000', '#67e8f9'),
  glass: preset('#0b0f1f', '#171b31', '#252b49', '#292f4c', '#343c5e', '#f8f9ff', '#d7dcf2', '#aab3d1', '#8b7cff', '#070a14', '#67e8f9'),
  plex: preset('#0f0f0f', '#1b1b1b', '#282828', '#2c2c2c', '#262626', '#f4f4f4', '#dedede', '#b6b6b6', '#e5a00d', '#090909', '#ffc83d'),
  projector: preset('#15130f', '#242018', '#332d21', '#383124', '#3b3325', '#fff4d6', '#ead9ad', '#bba97e', '#f2a93b', '#15130f', '#ffc866'),
  video_store: preset('#10132b', '#1a1f46', '#282f63', '#292f63', '#2e376f', '#f9f7ff', '#d8d9ff', '#aeb3df', '#ff4fa3', '#090b1d', '#58e1d4'),
};

export const BASIC_THEMES = ['system', 'light', 'dark'];

const PRESET_SURFACES = Object.fromEntries([
  ['catppuccin_mocha', '#585b70', '#181825', '#181825', '#11111b'],
  ['dracula', '#6272a4', '#21222c', '#21222c', '#21222c'],
  ['nord', '#4c566a', '#2b303b', '#242933', '#242933'],
  ['gruvbox', '#665c54', '#32302f', '#1d2021', '#1d2021'],
  ['oled', '#303030', '#050505', '#000000', '#030303'],
  ['glass', '#4c567a', '#11162a', '#0c1122', '#0c1020'],
  ['plex', '#444444', '#141414', '#0a0a0a', '#090909'],
  ['projector', '#5c4d32', '#1d1a14', '#191711', '#0d0c09'],
  ['video_store', '#4652a0', '#151938', '#11152f', '#090b1d'],
].map(([key, surfaceBorder, panel, surfaceDim, sidebar]) => [key, { surfaceBorder, panel, surfaceDim, sidebar }]));

// Tokens that platforms can keep live without re-rendering (CSS variables on the
// web, dynamic colours on iOS). `accent` stays out: shared code appends alpha
// digits to it, which only works on a literal colour.
export const LIVE_KEYS = [
  'background', 'sidebar', 'surface', 'surfaceStrong', 'surfaceMuted', 'border', 'surfaceBorder', 'surfaceDim', 'panel',
  'text', 'textSecondary', 'textMuted', 'link', 'accentContrast', 'dangerText',
];

const HEX = /^#[0-9a-f]{6}$/i;

export function isKnownTheme(theme) {
  return BASIC_THEMES.includes(theme) || theme === 'custom' || theme in PRESETS;
}

function customTokens(custom) {
  const saved = custom && typeof custom === 'object' ? custom : {};
  const pick = key => (typeof saved[key] === 'string' && HEX.test(saved[key]) ? saved[key].toLowerCase() : undefined);
  const overrides = {
    background: pick('page_bg'),
    surface: pick('surface'),
    panel: pick('panel'),
    text: pick('text'),
    textMuted: pick('muted'),
    accent: pick('accent'),
    accentContrast: pick('accent_text'),
  };
  const tokens = { ...DARK };
  Object.entries(overrides).forEach(([key, value]) => { if (value) tokens[key] = value; });
  const opacity = customEffects(saved).surfaceOpacity / 100;
  for (const key of ['surface', 'panel']) {
    const rgb = hexToRgb(tokens[key]);
    if (rgb && opacity < 1) tokens[key] = `rgba(${rgb.join(', ')}, ${opacity})`;
  }
  return tokens;
}

// Match users.appearance.CUSTOM_THEME_EFFECTS, including its step validation.
export function customEffects(custom) {
  const saved = custom && typeof custom === 'object' ? custom : {};
  const pick = (key, min, max, fallback) => Number.isInteger(saved[key])
    && saved[key] >= min && saved[key] <= max && (saved[key] - min) % 2 === 0
    ? saved[key] : fallback;
  return {
    radius: pick('radius', 0, 28, 12),
    blur: pick('blur', 0, 24, 12),
    surfaceOpacity: pick('surface_opacity', 40, 100, 82),
  };
}

// `scheme` describes resolved colours; `override` controls native chrome.
// React Native expects `auto`, not null, to follow the operating system.
export function resolveTheme(setting, systemScheme = 'dark') {
  const theme = isKnownTheme(setting?.theme) ? setting.theme : 'system';
  if (theme === 'light') return { theme, scheme: 'light', override: 'light', tokens: LIGHT };
  if (theme === 'dark') return { theme, scheme: 'dark', override: 'dark', tokens: DARK };
  if (theme === 'system') {
    return { theme, scheme: systemScheme === 'light' ? 'light' : 'dark', override: 'auto', tokens: systemScheme === 'light' ? LIGHT : DARK };
  }
  if (theme === 'custom') return { theme, scheme: 'dark', override: 'dark', tokens: customTokens(setting?.custom), effects: customEffects(setting?.custom) };
  return { theme, scheme: 'dark', override: 'dark', tokens: { ...DARK, ...PRESETS[theme], ...PRESET_SURFACES[theme] } };
}

const listeners = new Set();
let setting = { theme: 'system', custom: {} };
let systemScheme = 'dark';
let resolved = resolveTheme(setting, systemScheme);

function refresh() {
  const next = resolveTheme(setting, systemScheme);
  const changed = JSON.stringify(next) !== JSON.stringify(resolved);
  resolved = next;
  if (changed) listeners.forEach(listener => listener(resolved));
}

export function getTheme() {
  return resolved;
}

export function getThemeSetting() {
  return setting;
}

export function setThemeSetting(next) {
  setting = { theme: isKnownTheme(next?.theme) ? next.theme : 'system', custom: next?.custom || {} };
  refresh();
}

export function setSystemScheme(next) {
  systemScheme = next === 'light' ? 'light' : 'dark';
  refresh();
}

export function subscribeTheme(listener) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

// Changes to these force a remount on platforms that cannot keep them live.
export function remountSignature(resolvedTheme, liveKeys) {
  const live = new Set(liveKeys);
  return JSON.stringify([live.size, Object.entries(resolvedTheme.tokens).filter(([key]) => !live.has(key)), resolvedTheme.effects]);
}

// Web `--color-surface-muted` at 0.4 (calendar blank days, soft chips). The web
// token is darker than native `surfaceMuted` (the web's surface-alt) in the two
// built-in schemes, so those use the web values; presets and custom themes
// already share one value.
const WEB_SURFACE_MUTED = { dark: [52, 58, 64], light: [233, 236, 239] };
function hexToRgb(hex) {
  const match = /^#([0-9a-f]{6})$/i.exec(String(hex));
  if (!match) return null;
  const value = parseInt(match[1], 16);
  return [(value >> 16) & 255, (value >> 8) & 255, value & 255];
}
export function surfaceMutedSoft(resolved, alpha = 0.4) {
  const basic = ['light', 'dark', 'system'].includes(resolved.theme);
  const builtIn = basic ? WEB_SURFACE_MUTED[resolved.scheme === 'light' ? 'light' : 'dark'] : null;
  const rgb = builtIn || hexToRgb(resolved.tokens.surfaceMuted) || WEB_SURFACE_MUTED.dark;
  return `rgba(${rgb[0]}, ${rgb[1]}, ${rgb[2]}, ${alpha})`;
}
