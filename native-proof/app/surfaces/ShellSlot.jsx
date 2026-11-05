import React, { useState } from 'react';
import { Shell } from '../../../frontend/ui/Shell';
import { palette, radius } from '../theme';

export const surface = {
  id: 'SHELL',
  title: 'Application shell and navigation',
  where: 'Signed-in top bar, public header and mobile navigation',
  status: 'ported',
  note: 'The shared React Native top bar and mobile navigation overlay render at the top of the native shell. The web adapter keeps the signed-in and public navigation values, HTMX-boosted links, search island, sidebar state and server fallback. iOS and Android runtime are not verified by this export.',
};

const labels = {
  menu: 'Toggle navigation menu',
  closeMenu: 'Close navigation menu',
  navigation: 'Navigation',
  toggleTheme: 'Toggle theme',
  logo: 'Floppy',
};

const shellPalette = {
  text: palette.text,
  textSecondary: palette.textSecondary,
  textMuted: palette.textMuted,
  sidebar: palette.background,
  surface: palette.surface,
  surfaceMuted: palette.surfaceStrong,
  border: palette.border,
  accent: palette.accent,
  accentStrong: palette.accentStrong,
  overlay: 'rgba(0, 0, 0, 0.55)',
  radius: radius.sm,
  focusStyle: {},
};

const NAV_ITEMS = [
  { key: 'home', label: 'Home' },
  { key: 'discover', label: 'Discover' },
  { key: 'library', label: 'Library' },
  { key: 'calendar', label: 'Calendar' },
  { key: 'settings', label: 'Settings' },
];

export default function ShellSlot({ active = 'home', onNavigate }) {
  const [open, setOpen] = useState(false);
  const links = NAV_ITEMS.map(item => ({ ...item, current: item.key === active }));

  return <Shell
    open={open}
    onToggleMenu={() => setOpen(value => !value)}
    onCloseMenu={() => setOpen(false)}
    links={links}
    onNavigate={link => onNavigate?.(link.key)}
    variant="app"
    showMenu
    showSearch={false}
    showThemeButton={false}
    logoText="Floppy"
    labels={labels}
    palette={shellPalette}
  />;
}
