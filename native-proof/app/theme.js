export const palette = {
  background: '#18181b',
  surface: '#27272a',
  surfaceStrong: '#3f3f46',
  surfaceMuted: '#52525b',
  border: '#3f3f46',
  text: '#fafafa',
  textSecondary: '#d4d4d8',
  textMuted: '#a1a1aa',
  accent: '#6366f1',
  accentStrong: '#4f46e5',
  success: '#10b981',
  warning: '#f59e0b',
  danger: '#ef4444',
};

export const spacing = { xs: 4, sm: 8, md: 12, lg: 16, xl: 24 };
export const radius = { sm: 6, md: 10, lg: 16, pill: 9999 };

export const badgePalette = {
  indigo: { color: '#fff', backgroundColor: palette.accentStrong },
  outline: { color: palette.textSecondary, borderColor: palette.surfaceMuted, borderWidth: 1 },
};

export const progressPalette = {
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
};

export const ratingPalette = {
  lit: palette.warning,
  unlit: palette.surfaceMuted,
  muted: palette.textMuted,
};
