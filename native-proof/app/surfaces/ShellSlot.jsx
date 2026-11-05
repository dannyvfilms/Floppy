import React, { useState } from 'react';
import { Shell } from '../../../frontend/ui/Shell';
import { Sidebar } from '../../../frontend/ui/Sidebar';
import { palette, radius } from '../theme';

export const surface = {
  id: 'SHELL',
  title: 'Application shell and navigation',
  where: 'Signed-in top bar, public header and mobile navigation',
  status: 'in_progress',
  note: 'The shared React Native top bar and mobile navigation overlay render at the top of the native shell, and the shared sidebar fills the navigation drawer. The web adapter keeps the signed-in and public navigation values, HTMX-boosted links, search island, sidebar storage and server fallback. Browser menu/focus parity and iOS/Android runtime remain unverified.',
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
  surfaceStrong: palette.surfaceStrong,
  surfaceMuted: palette.surfaceStrong,
  surfaceHover: palette.surfaceStrong,
  hoverDim: 'rgba(255, 255, 255, 0.05)',
  border: palette.border,
  accent: palette.accent,
  accentStrong: palette.accentStrong,
  link: '#818cf8',
  danger: palette.danger,
  overlay: 'rgba(0, 0, 0, 0.55)',
  radius: radius.sm,
  focusStyle: {},
};

const SIDEBAR_LABELS = {
  logo: 'Floppy',
  explore: 'Explore',
  logout: 'Logout',
  pinnedLists: 'Pinned lists',
  navOptions: 'Navigation options',
  pin: 'Pin to sidebar',
  unpin: 'Unpin from sidebar',
  listOptions: 'List options',
  reorder: 'Reorder',
  delete: 'Delete',
  done: 'Done',
  closeMenu: 'Close menu',
  navigation: 'Navigation',
  savedViews: 'Saved %(name)s views',
  viewOptions: 'Options for %(name)s',
  confirmDelete: 'Delete the saved view \u201c%(name)s\u201d?',
};

const PIN_KEYS = ['calendar', 'collection', 'custom', 'history', 'lists', 'statistics', 'tags'];

const SIDEBAR_MODEL = {
  userId: 'demo',
  currentUrl: '/',
  logo: { text: 'Floppy' },
  pinKeys: PIN_KEYS,
  primary: [
    { type: 'link', label: 'Home', href: '/', glyph: '\u2302', active: true, pinKey: null, tab: 'home' },
    { type: 'link', label: 'Discover', href: '/discover', glyph: '\u25a6', active: false, pinKey: null, tab: 'discover' },
    {
      type: 'group', key: 'movie', label: 'Movies', href: '/movie', glyph: '\u25b6', active: false, pinKey: null,
      views: [
        { id: 'movie-finished', name: 'Finished', href: '/movie?status=Completed', current: false },
        { id: 'movie-watchlist', name: 'To watch', href: '/movie?status=Planning', current: false },
      ],
    },
    {
      type: 'group', key: 'tv', label: 'TV Shows', href: '/tv', glyph: '\u25a4', active: false, pinKey: null,
      views: [
        { id: 'tv-next', name: 'Up next', href: '/tv?status=In+progress', current: false },
      ],
    },
    { type: 'link', label: 'Anime', href: '/anime', glyph: '\u2726', active: false, pinKey: null, tab: 'library' },
    { type: 'link', label: 'Games', href: '/games', glyph: '\u25c6', active: false, pinKey: null, tab: 'library' },
  ],
  secondary: [
    { type: 'link', key: 'calendar', label: 'Calendar', href: '/calendar', glyph: '\u25a6', active: false, pinKey: 'calendar', tab: 'calendar' },
    { type: 'link', key: 'collection', label: 'Collection', href: '/collection', glyph: '\u25a3', active: false, pinKey: 'collection' },
    { type: 'link', key: 'custom', label: 'Custom', href: '/new', glyph: '\uff0b', active: false, pinKey: 'custom' },
    { type: 'link', key: 'history', label: 'History', href: '/history', glyph: '\u25f7', active: false, pinKey: 'history' },
    { type: 'lists', key: 'lists', label: 'Lists', href: '/lists', glyph: '\u2630', active: false, pinKey: 'lists' },
    { type: 'link', key: 'statistics', label: 'Statistics', href: '/statistics', glyph: '\u25a5', active: false, pinKey: 'statistics' },
    { type: 'link', key: 'tags', label: 'Tags', href: '/tags', glyph: '#', active: false, pinKey: 'tags' },
  ],
  bottom: {
    appearance: { label: 'Appearance', glyph: '\u263e', active: false },
    settings: { label: 'Settings', glyph: '\u2699', active: false, tab: 'settings' },
    logoutIcon: null,
    logoutGlyph: '\u21e5',
    logoutAction: '/logout',
  },
};

export default function ShellSlot({ active = 'home', onNavigate }) {
  const [open, setOpen] = useState(false);
  const [pinned, setPinned] = useState([]);
  const [pinnedLists] = useState([]);
  const pins = {
    pinned,
    pinnedLists,
    isPinned: key => pinned.includes(key),
    toggle: key => setPinned(current => (
      current.includes(key) ? current.filter(entry => entry !== key) : [...current, key]
    )),
    unpinList: () => {},
  };

  const openItem = item => {
    if (item?.tab) onNavigate?.(item.tab);
    setOpen(false);
  };

  return <Shell
    open={open}
    onToggleMenu={() => setOpen(value => !value)}
    onCloseMenu={() => setOpen(false)}
    links={[]}
    onNavigate={link => onNavigate?.(link.key)}
    variant="app"
    showMenu
    showSearch={false}
    showThemeButton={false}
    logoText="Floppy"
    labels={labels}
    palette={shellPalette}
  >
    <Sidebar model={SIDEBAR_MODEL} pins={pins} palette={shellPalette}
      labels={SIDEBAR_LABELS} onNavigate={openItem} onLogout={() => setOpen(false)}
      showLogo={false} />
  </Shell>;
}
