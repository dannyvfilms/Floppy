import { useEffect, useState } from 'react';
import { palette, radius } from '../theme';
import { subscribeTheme } from '../themeState';

// Palettes for the shared settings components, built from theme tokens. Built
// per render so a theme change reaches them; components never keep colours.
export function buildSettingsPalettes() {
  return {
    settingsPalette: {
      text: palette.text,
      textSecondary: palette.textSecondary,
      textMuted: palette.textMuted,
      border: palette.border,
      fieldBorder: palette.fieldBorder,
      surfaceBorder: palette.surfaceBorder,
      background: palette.surface,
      surface: palette.surface,
      surfaceStrong: palette.surfaceStrong,
      surfaceDim: palette.surfaceDim,
      panel: palette.panel,
      surfaceMuted: palette.surfaceMuted,
      accent: palette.accent,
      accentStrong: palette.accentStrong,
      accentText: palette.accentContrast,
      success: palette.success,
      warning: palette.warning,
      danger: palette.danger,
      overlay: palette.overlay,
      badgeBorder: palette.surfaceMuted,
      badgeBackground: palette.surfaceStrong,
      badgeText: palette.textSecondary,
      badgeHover: palette.surfaceMuted,
      link: palette.link,
      thumb: palette.onAccentStrong,
      radius: radius.md,
      focusStyle: {},
    },
    buttonPalette: {
      primary: {
        background: palette.accentStrong, pressed: palette.accentStrongPressed,
        hovered: palette.accentStrongPressed, text: palette.onAccentStrong, border: 'transparent',
      },
      surface: {
        background: palette.surfaceStrong, pressed: palette.surfaceMuted,
        hovered: palette.surfaceMuted, text: palette.text, border: palette.border,
      },
      'danger-solid': {
        background: palette.danger, pressed: palette.dangerPressed,
        hovered: palette.dangerPressed, text: palette.onDanger, border: 'transparent',
      },
      'ghost-danger': {
        background: 'transparent', pressed: palette.dangerSoft,
        hovered: palette.dangerSoft, text: palette.dangerText, border: 'transparent',
      },
      radius: radius.sm,
      focusStyle: {},
    },
  };
}

export function useSettingsPalettes() {
  const [, bump] = useState(0);
  useEffect(() => subscribeTheme(() => bump(count => count + 1)), []);
  return buildSettingsPalettes();
}
