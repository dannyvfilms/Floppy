import { DARK, LIGHT, PRESETS, getTheme, subscribeTheme, surfaceMutedSoft } from './themeState';
import { themeColor } from './themeColor';

// Semantic colours. Every token is a getter that reads the active theme
// (docs/architecture/theming.md) through the platform's colour strategy:
// CSS variables on the web, dynamic colours on iOS for system/light/dark, and
// literals elsewhere (ThemeRoot remounts the tree when those change). Importing
// `palette` keeps working: `palette.text` always answers for the current theme.
const TOKEN_KEYS = [
  'background', 'surface', 'surfaceStrong', 'surfaceMuted', 'border', 'surfaceBorder', 'surfaceDim', 'panel',
  'text', 'textSecondary', 'textMuted', 'accent', 'accentContrast', 'link', 'dangerText',
];

// Fixed brand and status colours, identical in every theme (web parity: indigo
// primary buttons, red destructive buttons).
const FIXED = {
  fieldBorder: '#4b5563',
  accentStrong: '#4f46e5',
  accentStrongPressed: '#4338ca',
  onAccentStrong: '#ffffff',
  success: '#10b981',
  importRunCompletedText: '#4ade80',
  importRunCompletedBackground: 'rgba(74, 222, 128, 0.1)',
  warning: '#f59e0b',
  danger: '#ef4444',
  dangerPressed: '#b91c1c',
  onDanger: '#ffffff',
  dangerSoft: 'rgba(239, 68, 68, 0.18)',
  overlay: 'rgba(0, 0, 0, 0.55)',
};

// The same diagonal bands as the web appearance swatches; colours stay in the theme source.
export const themeSwatches = Object.fromEntries([
  ['system', LIGHT.background, DARK.background, 0.5],
  ['light', LIGHT.background, '#4f46e5', 0.65],
  ['dark', DARK.background, DARK.accent, 0.65],
  ['catppuccin_mocha', PRESETS.catppuccin_mocha.background, PRESETS.catppuccin_mocha.accent, 0.52, PRESETS.catppuccin_mocha.link, 0.76],
  ['dracula', PRESETS.dracula.background, PRESETS.dracula.accent, 0.52, '#ff79c6', 0.76],
  ['nord', PRESETS.nord.background, PRESETS.nord.accent, 0.52, PRESETS.nord.text, 0.76],
  ['gruvbox', PRESETS.gruvbox.background, PRESETS.gruvbox.accent, 0.52, PRESETS.gruvbox.link, 0.76],
  ['oled', PRESETS.oled.background, PRESETS.oled.accent, 0.65],
  ['plex', PRESETS.plex.background, PRESETS.plex.accent, 0.65],
  ['projector', PRESETS.projector.background, PRESETS.projector.accent, 0.65],
  ['video_store', PRESETS.video_store.background, PRESETS.video_store.accent, 0.5, PRESETS.video_store.link, 0.75],
].map(([key, base, second, at, third, thirdAt]) => [key, {
  viewBox: '0 0 44 44', root: { fill: 'none' }, children: [
    { tag: 'rect', attrs: { width: '44', height: '44', fill: base }, children: [] },
    ...[[second, at], ...(third ? [[third, thirdAt]] : [])].map(([fill, stop]) => ({
      tag: 'polygon', attrs: { points: `44,${88 * stop - 44} 44,44 ${88 * stop - 44},44`, fill }, children: [],
    })),
  ],
}]));

themeSwatches.glass = {
  viewBox: '0 0 44 44', root: { fill: 'none' }, children: [
    { tag: 'defs', attrs: {}, children: [
      { tag: 'linearGradient', attrs: { id: 'theme-glass-base', x1: '0%', y1: '0%', x2: '100%', y2: '100%' }, children: [
        { tag: 'stop', attrs: { offset: '55%', 'stop-color': '#0d1122' }, children: [] },
        { tag: 'stop', attrs: { offset: '100%', 'stop-color': PRESETS.glass.accent }, children: [] },
      ] },
      { tag: 'radialGradient', attrs: { id: 'theme-glass-glow', cx: '30%', cy: '25%', r: '39%' }, children: [
        { tag: 'stop', attrs: { offset: '0%', 'stop-color': PRESETS.glass.link }, children: [] },
        { tag: 'stop', attrs: { offset: '100%', 'stop-color': PRESETS.glass.link, 'stop-opacity': '0' }, children: [] },
      ] },
    ] },
    { tag: 'rect', attrs: { width: '44', height: '44', fill: 'url(#theme-glass-base)' }, children: [] },
    { tag: 'rect', attrs: { width: '44', height: '44', fill: 'url(#theme-glass-glow)' }, children: [] },
  ],
};

const customSwatchColors = ['#ff4fa3', '#58e1d4', '#f2a93b', '#4f46e5', '#ff4fa3'];
themeSwatches.custom = {
  viewBox: '0 0 44 44', root: { fill: 'none' },
  // SVG has no conic paint server; small overlapping sectors render the web's hue wheel on every platform.
  children: Array.from({ length: 120 }, (_, index) => {
    const position = (index + 0.5) / 30;
    const segment = Math.floor(position);
    const fraction = position - segment;
    const channels = [1, 3, 5].map(start => Math.round(
      parseInt(customSwatchColors[segment].slice(start, start + 2), 16) * (1 - fraction)
      + parseInt(customSwatchColors[segment + 1].slice(start, start + 2), 16) * fraction,
    ));
    const from = (index * 3 - 90) * Math.PI / 180;
    const to = (index * 3 - 86.9) * Math.PI / 180;
    return { tag: 'path', attrs: {
      d: `M22 22L${22 + Math.cos(from) * 32} ${22 + Math.sin(from) * 32}L${22 + Math.cos(to) * 32} ${22 + Math.sin(to) * 32}Z`,
      fill: `rgb(${channels.join(',')})`,
    }, children: [] };
  }),
};

let themeVersion = 0;
subscribeTheme(() => { themeVersion += 1; });

export function getThemeVersion() {
  return themeVersion;
}

export const palette = {};
TOKEN_KEYS.forEach(key => {
  Object.defineProperty(palette, key, { enumerable: true, get: () => themeColor(key, getTheme()) });
});
Object.entries(FIXED).forEach(([key, value]) => {
  Object.defineProperty(palette, key, { enumerable: true, value });
});

Object.defineProperty(palette, 'surfaceMutedSoft', { enumerable: true, get: () => surfaceMutedSoft(getTheme()) });

// Palettes derived from `palette` are recomputed when the theme changes, so a
// consumer holding the object never sees stale colours.
function liveObject(factory) {
  let version = -1;
  let cache = {};
  const current = () => {
    if (version !== themeVersion) {
      cache = factory();
      version = themeVersion;
    }
    return cache;
  };
  return new Proxy({}, {
    get: (_target, key) => current()[key],
    has: (_target, key) => key in current(),
    ownKeys: () => Reflect.ownKeys(current()),
    getOwnPropertyDescriptor: (_target, key) => {
      const descriptor = Object.getOwnPropertyDescriptor(current(), key);
      return descriptor ? { ...descriptor, configurable: true } : undefined;
    },
  });
}

export const spacing = { xs: 4, sm: 8, md: 12, lg: 16, xl: 24 };
// Custom web themes use one radius for all rounded controls. Basic themes keep
// the existing native sizes; runtime consumers read the current theme.
export const radius = {
  get sm() { return getTheme().effects?.radius ?? 6; },
  get md() { return getTheme().effects?.radius ?? 10; },
  get lg() { return getTheme().effects?.radius ?? 16; },
  pill: 9999,
};

const makeBadgePalette = () => ({
  indigo: { color: '#fff', backgroundColor: palette.accentStrong },
  outline: { color: palette.textSecondary, borderColor: palette.surfaceMuted, borderWidth: 1 },
});
export const badgePalette = liveObject(makeBadgePalette);

const makeProgressPalette = () => ({
  text: palette.textSecondary,
  icon: palette.text,
  disabledIcon: palette.text,
  button: palette.surfaceStrong,
  buttonHover: palette.surfaceMuted,
  flash: 'rgba(99, 102, 241, 0.55)',
  buttonSize: 24,
  radius: radius.sm,
  iconSize: 12,
  fontSize: 12,
  minWidth: 24,
  showButtons: true,
});
export const progressPalette = liveObject(makeProgressPalette);

const makeProgressDetailPalette = () => ({
  background: palette.background,
  text: palette.text,
  textSecondary: palette.textSecondary,
  textMuted: palette.textMuted,
  surface: palette.surface,
  surfaceStrong: palette.surfaceStrong,
  surfaceBorder: palette.border,
  surfaceMuted: palette.surfaceMuted,
  surfaceHover: palette.surfaceStrong,
  fill: palette.success,
  glow: '#a7f3d0',
  glowShadow: '#6ee7b7',
  watchedBorder: 'rgba(16, 185, 129, 0.4)',
  watchedBg: 'rgba(16, 185, 129, 0.1)',
  watchedText: palette.success,
  upcomingBorder: palette.border,
  droppedBackground: palette.surfaceMuted,
  droppedText: palette.textMuted,
  focusStyle: {},
});
export const progressDetailPalette = liveObject(makeProgressDetailPalette);

const makeRatingPalette = () => ({
  lit: palette.warning,
  unlit: palette.surfaceMuted,
  muted: palette.textMuted,
  text: palette.text,
  textSecondary: palette.textSecondary,
  surface: palette.surface,
  border: palette.border,
  chipBackground: 'rgba(245, 158, 11, 0.07)',
  chipBorder: 'rgba(251, 191, 36, 0.18)',
  chipHoverBackground: 'rgba(245, 158, 11, 0.11)',
  chipHoverBorder: 'rgba(252, 211, 77, 0.28)',
  starBadgeBackground: 'rgba(245, 158, 11, 0.14)',
  starBadgeBorder: 'rgba(251, 191, 36, 0.28)',
  cardBackground: 'rgba(251, 191, 36, 0.10)',
  cardBorder: 'rgba(251, 191, 36, 0.26)',
  compactUnratedBorder: 'rgba(156, 163, 175, 0.28)',
  compactUnratedBackground: 'rgba(107, 114, 128, 0.14)',
  compactUnratedHoverBackground: 'rgba(107, 114, 128, 0.20)',
  compactRatedBorder: 'rgba(251, 191, 36, 0.28)',
  compactRatedBackground: 'rgba(245, 158, 11, 0.14)',
  compactRatedHoverBackground: 'rgba(245, 158, 11, 0.20)',
  compactValue: '#fcd34d',
  compactFontSize: 12,
  compactIconSize: 14,
  focusStyle: {},
  fontSize: 14,
  chipHeight: 32,
  starBadgeSize: 32,
  iconSize: 16,
  paddingRight: 12,
  gap: 8,
  popupWidth: 250,
  popupRadius: 8,
  popupPadding: 12,
});
export const ratingPalette = liveObject(makeRatingPalette);

const makeMediaCardPalette = () => ({
  card: palette.surface,
  text: palette.text,
  textSecondary: palette.textSecondary,
  textMuted: palette.textMuted,
  border: palette.border,
  link: '#818cf8',
  star: palette.warning,
  chipBackground: 'rgba(24, 24, 27, 0.92)',
  chipText: '#ffffff',
  placeholder: palette.surfaceStrong,
  progressTrack: 'rgba(24, 24, 27, 0.6)',
  progressFill: palette.accent,
  progressPaused: 'rgba(99, 102, 241, 0.4)',
  local: {
    backgroundColor: 'rgba(245, 158, 11, 0.15)',
    borderColor: 'rgba(245, 158, 11, 0.3)',
    color: '#fde68a',
  },
  statusColors: {
    Completed: palette.success,
    'In progress': palette.accent,
    Paused: palette.warning,
    Planning: '#38bdf8',
    Dropped: palette.danger,
  },
  rating: { ...ratingPalette, focusStyle: {} },
});
export const mediaCardPalette = liveObject(makeMediaCardPalette);

const makeHistoryPalette = () => ({
  background: palette.background,
  surface: palette.surface,
  surfaceStrong: palette.surfaceStrong,
  surfaceMuted: palette.surfaceMuted,
  border: palette.border,
  text: palette.text,
  textSecondary: palette.textSecondary,
  textMuted: palette.textMuted,
  accent: palette.accent,
  accentStrong: palette.accentStrong,
  accentContrast: '#ffffff',
  link: '#818cf8',
  danger: palette.danger,
  success: palette.success,
  warning: palette.warning,
  radius: radius.md,
  radiusSmall: radius.sm,
  mediaCard: mediaCardPalette,
});
export const historyPalette = liveObject(makeHistoryPalette);

const makeRailPalette = () => ({
  text: palette.text,
  textSecondary: palette.textSecondary,
  textMuted: palette.textMuted,
  surface: palette.surface,
  surfaceHover: palette.surfaceStrong,
  border: palette.border,
  accent: palette.accent,
  arrow: palette.textSecondary,
  arrowDisabled: palette.surfaceMuted,
  loading: palette.accent,
  focus: palette.accent,
});
export const railPalette = liveObject(makeRailPalette);

const makeStatisticsPalette = () => ({
  background: palette.background,
  surface: palette.surface,
  surfaceStrong: palette.surfaceStrong,
  surfaceMuted: palette.surfaceMuted,
  border: palette.border,
  text: palette.text,
  textSecondary: palette.textSecondary,
  textMuted: palette.textMuted,
  accent: palette.accent,
  accentStrong: palette.accentStrong,
  accentContrast: '#ffffff',
  link: palette.link,
  danger: palette.danger,
  warning: palette.warning,
  success: palette.success,
  radius: 18,
  radiusSmall: radius.sm,
});
export const statisticsPalette = liveObject(makeStatisticsPalette);

const makeDateTimePalette = () => ({
  text: palette.text,
  textSecondary: palette.textSecondary,
  textMuted: palette.textMuted,
  surface: palette.surface,
  surfaceStrong: palette.surfaceStrong,
  surfaceMuted: palette.surfaceMuted,
  border: palette.border,
  accent: palette.accent,
  accentContrast: '#ffffff',
  link: '#818cf8',
  danger: palette.danger,
  radius: radius.md,
  radiusSmall: radius.sm,
  fontSize: 14,
  smallFontSize: 12,
});
export const dateTimePalette = liveObject(makeDateTimePalette);

const makePlaybackPalette = () => ({
  surface: palette.surface,
  surfaceStrong: palette.surfaceStrong,
  surfaceHover: palette.surfaceStrong,
  surfaceMuted: palette.surfaceMuted,
  border: palette.border,
  text: palette.text,
  textSecondary: palette.textSecondary,
  textMuted: palette.textMuted,
  link: '#818cf8',
  accent: palette.accent,
  warning: palette.warning,
  danger: palette.danger,
  placeholder: palette.surfaceStrong,
  progressTrack: 'rgba(24, 24, 27, 0.8)',
  progressFill: palette.accent,
  pausedFill: palette.warning,
  focusStyle: {},
});
export const playbackPalette = liveObject(makePlaybackPalette);
