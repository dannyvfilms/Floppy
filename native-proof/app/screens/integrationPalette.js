import { palette, radius } from '../theme';

// Theme-token palettes for the integration screens. The shared provider,
// connection and review views read these keys; everything comes from the theme
// so light, dark and custom themes apply without hardcoded colors.
export function integrationPalette() {
  return {
    ...palette,
    background: palette.surface,
    radius: radius.md,
    focusStyle: {},
    card: palette.surface,
    cardHovered: palette.surfaceStrong,
    cardPressed: palette.surfaceStrong,
    badgeBorder: palette.border,
    badgeBackground: palette.surfaceStrong,
    badgeText: palette.textSecondary,
    badgeHover: palette.surfaceMuted,
    statusNeutral: palette.textMuted,
    statusSuccess: palette.success,
    statusWarning: palette.warning,
    attention: palette.warning,
    pin: palette.textMuted,
    pinActive: palette.accent,
  };
}

export function integrationButtonPalette() {
  return {
    primary: {
      background: palette.accentStrong,
      pressed: palette.accentStrongPressed,
      hovered: palette.accentStrongPressed,
      text: palette.onAccentStrong,
      border: 'transparent',
    },
    surface: {
      background: palette.surfaceStrong,
      pressed: palette.surfaceMuted,
      hovered: palette.surfaceMuted,
      text: palette.text,
      border: palette.border,
    },
    'danger-solid': {
      background: palette.danger,
      pressed: palette.dangerPressed,
      hovered: palette.dangerPressed,
      text: palette.onDanger,
      border: 'transparent',
    },
    radius: radius.sm,
    size: 'md',
    focusStyle: {},
  };
}
