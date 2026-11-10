import React, { useEffect, useState } from 'react';
import { Platform } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { useHinge } from 'expo-hinge';
import { useVerticalBarEdgeIOS } from 'expo-status-bar';
import { getActiveAuthSession, subscribeAuthSession } from '../data/authSession';
import { signOut } from '../data/authTransport';
import { Shell } from '../../../frontend/ui/Shell';
import { Sidebar } from '../../../frontend/ui/Sidebar';
import { renderNativeIcon } from '../iconRenderer';
import SearchSlot from './SearchSlot';
import NativeShell from './NativeShell';
import { horizontalContentPadding } from '../safeAreaSpacing.mjs';
import { palette, radius } from '../theme';

export const surface = {
  id: 'SHELL',
  title: 'Application shell and navigation',
  where: 'Signed-in top bar, public header and mobile navigation',
  status: 'in_progress',
  note: 'The native shell mirrors the web compact layout: a top bar with the menu button and global search, and a navigation drawer built from /api/v1/user/navigation/ — the same sidebar model the web template renders, including icons, order and saved views. Signed out it falls back to demo navigation because there is no server session. The persistent desktop sidebar and the web-only onboarding card are not ported yet.',
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
  confirmDelete: 'Delete the saved view "%(name)s"?',
};

const PIN_KEYS = ['calendar', 'collection', 'custom', 'history', 'lists', 'statistics', 'tags'];

// Signed-out demo navigation. A real session replaces this with the server
// model, so the demo fallback is only ever shown behind the Demo data banner.
const DEMO_MODEL = {
  userId: 'demo',
  currentUrl: '/',
  logo: { text: 'Floppy' },
  pinKeys: PIN_KEYS,
  primary: [
    { type: 'link', label: 'Home', href: '/', glyph: '\u2302', active: true, pinKey: null },
    { type: 'link', label: 'Discover', href: '/discover', glyph: '\u25a6', active: false, pinKey: null },
  ],
  secondary: [
    { type: 'link', key: 'calendar', label: 'Calendar', href: '/calendar', glyph: '\u25a6', active: false, pinKey: 'calendar' },
    { type: 'link', key: 'history', label: 'History', href: '/history', glyph: '\u25f7', active: false, pinKey: 'history' },
    { type: 'link', key: 'lists', label: 'Lists', href: '/lists', glyph: '\u2630', active: false, pinKey: 'lists' },
    { type: 'link', key: 'tags', label: 'Tags', href: '/tags', glyph: '#', active: false, pinKey: 'tags' },
  ],
  bottom: {
    appearance: { label: 'Appearance', glyph: '\u263e', active: false },
    settings: { label: 'Settings', glyph: '\u2699', active: false },
    logoutIcon: null,
    logoutGlyph: '\u21e5',
    logoutAction: '/logout',
  },
};

// If an icon spec cannot render, a one-character fallback keeps the row
// readable instead of showing an identical bullet everywhere.
const GLYPHS = {
  Home: '\u2302', Discover: '\u25a6', 'TV Shows': '\u25a4', Movies: '\u25b6',
  Anime: '\u2726', Manga: '\u25a4', Games: '\u25c6', Books: '\u25a4',
  Comics: '\u25a4', 'Board Games': '\u25c6', Music: '\u266b', Podcasts: '\u25c9',
  'TV Seasons': '\u25a4', Videos: '\u25b6', Calendar: '\u25a6', Collection: '\u25a3',
  Custom: '\uff0b', History: '\u25f7', Lists: '\u2630', Statistics: '\u25a5',
  Tags: '#', Appearance: '\u263e', Settings: '\u2699', Logout: '\u21e5',
};

function withGlyphs(model) {
  const add = item => ({ ...item, glyph: item.glyph || GLYPHS[item.label] || undefined });
  return {
    ...model,
    primary: (model.primary || []).map(add),
    secondary: (model.secondary || []).map(add),
    bottom: model.bottom ? {
      ...model.bottom,
      appearance: add(model.bottom.appearance),
      settings: add(model.bottom.settings),
    } : model.bottom,
  };
}

function markActive(model, activeHref) {
  if (!activeHref) return model;
  const active = href => Boolean(href) && (href === activeHref
    || (href !== '/' && activeHref.startsWith(href)));
  const mark = item => ({
    ...item,
    active: active(item.href),
    views: (item.views || []).map(view => ({ ...view, current: view.href === activeHref })),
  });
  return {
    ...model,
    primary: (model.primary || []).map(mark),
    secondary: (model.secondary || []).map(mark),
    bottom: model.bottom ? {
      ...model.bottom,
      appearance: mark(model.bottom.appearance),
      settings: mark(model.bottom.settings),
    } : model.bottom,
  };
}

function absoluteLogo(model, serverUrl) {
  const src = model?.logo?.src;
  if (!src || !serverUrl || /^https?:\/\//.test(src)) return model;
  return { ...model, logo: { ...model.logo, src: `${serverUrl}${src}` } };
}

export default function ShellSlot({
  active = 'home',
  activeHref = '/',
  canGoBack = false,
  onBack,
  onNavigate,
  onOpenHref,
  onOpenSearch,
  onOpenSuggestion,
  children,
}) {
  const [session, setSession] = useState(() => getActiveAuthSession());
  const [serverModel, setServerModel] = useState(null);
  const [open, setOpen] = useState(false);
  const [pinned, setPinned] = useState([]);
  const hinge = useHinge();
  const railEdge = useVerticalBarEdgeIOS();
  const insets = useSafeAreaInsets();

  useEffect(() => subscribeAuthSession(setSession), []);

  useEffect(() => {
    const auth = session;
    if (!auth || typeof auth.request !== 'function') {
      setServerModel(null);
      setPinned([]);
      return undefined;
    }
    let cancelled = false;
    // Saved views change on other devices, so read them again each time the menu opens.
    auth.request('/api/v1/user/navigation/')
      .then(model => { if (!cancelled) setServerModel(absoluteLogo(model, auth.serverUrl)); })
      .catch(() => { if (!cancelled) setServerModel(null); });
    return () => { cancelled = true; };
  }, [session, open]);

  const base = serverModel || DEMO_MODEL;
  const model = markActive(withGlyphs(base), activeHref);
  const routeMediaType = activeHref.match(/^\/medialist\/([^/?#]+)/)?.[1];
  const searchType = routeMediaType || serverModel?.lastSearchType || 'all';
  const pins = {
    pinned,
    pinnedLists: [],
    isPinned: key => pinned.includes(key),
    toggle: key => setPinned(current => (
      current.includes(key) ? current.filter(entry => entry !== key) : [...current, key]
    )),
    unpinList: () => {},
  };

  const openItem = item => {
    setOpen(false);
    if (item?.href) onOpenHref?.(item.href, item);
  };

  const navigationPadding = horizontalContentPadding(insets, 16);
  const adaptivePalette = Platform.OS === 'ios' && (hinge || railEdge)
    ? { ...shellPalette, navRowHeight: 44, navContentPaddingTop: 25,
      navContentPaddingLeft: navigationPadding.paddingLeft,
      navContentPaddingRight: navigationPadding.paddingRight,
      navFontSize: 17, navIconSize: 22 }
    : shellPalette;
  const sidebar = <Sidebar model={model} pins={pins} palette={adaptivePalette}
    labels={SIDEBAR_LABELS}
    renderIcon={renderNativeIcon}
    onNavigate={openItem}
    // Carve-out: web reveals the saved-views arrow on hover or on the current library; touch has no
    // hover, so native always shows it.
    rowActions="always"
    onLogout={() => { setOpen(false); signOut().catch(() => {}); }}
    showLogo={false} />;
  const search = <SearchSlot
    key={searchType}
    expanded
    initialMediaType={searchType}
    onOpenSearch={onOpenSearch}
    onOpenSuggestion={onOpenSuggestion}
  />;

  if (Platform.OS === 'ios') {
    return <NativeShell open={open} onToggle={() => setOpen(value => !value)}
      sidebar={sidebar} search={search} labels={labels} palette={shellPalette}
      canGoBack={canGoBack} onBack={() => { setOpen(false); onBack?.(); }}>
      {children}
    </NativeShell>;
  }

  return <><Shell
    open={open}
    onToggleMenu={() => setOpen(value => !value)}
    onCloseMenu={() => setOpen(false)}
    links={[]}
    variant="app"
    showMenu
    showSearch
    showThemeButton={false}
    search={search}
    labels={labels}
    palette={shellPalette}
  >
    {sidebar}
  </Shell>{children}</>;
}
