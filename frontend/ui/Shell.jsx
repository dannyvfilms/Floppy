import { Modal } from './Modal';
import React from 'react';
import {
  Image,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  useWindowDimensions,
  View,
} from 'react-native';

// The application and public shells share one top bar contract. Browser
// adapters supply navigation values, theme colours and link attributes; this
// file only lays out the bar and the mobile navigation overlay.

const defaultPalette = {
  text: '#fafafa',
  textSecondary: '#d1d5db',
  textMuted: '#adb5bd',
  sidebar: '#212529',
  surface: '#2a2f35',
  surfaceMuted: '#343a40',
  border: '#343a40',
  accent: '#4a9eff',
  accentStrong: '#4f46e5',
  link: '#818cf8',
  overlay: 'rgba(0, 0, 0, 0.5)',
  focusStyle: {},
  radius: 6,
};

const defaultLabels = {
  menu: 'Toggle navigation menu',
  closeMenu: 'Close navigation menu',
  navigation: 'Navigation',
  toggleTheme: 'Toggle theme',
  signIn: 'Sign In',
  logo: 'Floppy',
};

function Bars({ color }) {
  return <View aria-hidden style={styles.bars}>
    {[0, 1, 2].map(row => <View key={row} style={[styles.barLine, { backgroundColor: color }]} />)}
  </View>;
}

function ThemeGlyph({ light, color }) {
  return <Text aria-hidden style={[styles.themeGlyph, { color }]}>
    {light ? '☀' : '☾'}
  </Text>;
}

function MenuButton({ open, onPress, label, palette }) {
  return <Pressable accessibilityRole="button" accessibilityLabel={label}
    aria-expanded={open} aria-controls="sidebar-nav" onPress={onPress}
    style={({ pressed, hovered, focused }) => [styles.menuButton, {
      backgroundColor: pressed || hovered ? palette.surfaceMuted : 'transparent',
      borderRadius: palette.radius,
    }, focused && palette.focusStyle]}>
    <Bars color={palette.textMuted} />
  </Pressable>;
}

function ThemeButton({ light, onPress, label, palette }) {
  return <Pressable accessibilityRole="button" accessibilityLabel={label} onPress={onPress}
    style={({ pressed, hovered, focused }) => [styles.themeButton, {
      backgroundColor: pressed || hovered ? palette.surfaceMuted : 'transparent',
      borderRadius: palette.radius,
    }, focused && palette.focusStyle]}>
    <ThemeGlyph light={light} color={palette.textMuted} />
  </Pressable>;
}

function Logo({ logo, label, palette }) {
  if (logo?.src) {
    return <Image accessible accessibilityLabel={logo.alt || label}
      resizeMode={logo.mono ? 'cover' : 'contain'}
      source={{ uri: logo.src }}
      style={styles.logo} />;
  }
  return <Text style={[styles.logoText, { color: palette.text }]}>{label}</Text>;
}

function SignIn({ signIn, palette }) {
  if (!signIn) return null;
  return <Pressable accessibilityRole="link" accessibilityLabel={signIn.label}
    onPress={signIn.onPress} {...signIn.platformProps}
    style={({ pressed, hovered, focused }) => [styles.signIn, {
      backgroundColor: pressed || hovered ? '#4338ca' : palette.accentStrong,
      borderRadius: palette.radius,
    }, focused && palette.focusStyle]}>
    <Text style={styles.signInText}>{signIn.label}</Text>
  </Pressable>;
}

export function TopBar({
  variant = 'app',
  menuOpen = false,
  onToggleMenu,
  showMenu = true,
  showSearch = true,
  search,
  logo,
  logoText,
  signIn,
  light = false,
  onToggleTheme,
  showThemeButton = false,
  labels: labelOverrides,
  palette: paletteOverrides,
}) {
  const palette = { ...defaultPalette, ...paletteOverrides };
  const labels = { ...defaultLabels, ...labelOverrides };
  const { width } = useWindowDimensions();
  const compact = width < 1024;
  const app = variant === 'app';
  const showMenuButton = app && showMenu && compact;

  return <View style={styles.root}>
    <View style={[styles.bar, !app && styles.publicBar]}>
      {showMenuButton ? <MenuButton open={menuOpen} onPress={onToggleMenu}
        label={labels.menu} palette={palette} /> : null}
      {!app ? <View style={styles.brand}>
        <Logo logo={logo} label={logoText || labels.logo} palette={palette} />
      </View> : null}
      {app && logoText ? <View style={styles.brand}>
        <Logo logo={logo} label={logoText || labels.logo} palette={palette} />
      </View> : null}
      {app && showSearch ? <View style={styles.searchWrap}>{search}</View> : null}
      {!app ? <SignIn signIn={signIn} palette={palette} /> : null}
      {app && showThemeButton && !compact && onToggleTheme ? <ThemeButton light={light}
        onPress={onToggleTheme} label={labels.toggleTheme} palette={palette} /> : null}
    </View>
  </View>;
}

function NavLink({ link, onPress, palette }) {
  return <Pressable accessibilityRole={link.current ? 'link' : 'button'}
    accessibilityLabel={link.label}
    accessibilityState={link.current ? { selected: true } : undefined}
    onPress={onPress}
    style={({ pressed, hovered, focused }) => [styles.navLink, {
      backgroundColor: link.current ? palette.surfaceMuted : pressed || hovered ? palette.surface : 'transparent',
      borderRadius: palette.radius,
    }, focused && palette.focusStyle]}>
    <Text style={[styles.navLinkText, { color: link.current ? palette.text : palette.textSecondary }]}>
      {link.label}
    </Text>
  </Pressable>;
}

export function MobileNav({
  open = false,
  onClose,
  links = [],
  onNavigate,
  children,
  labels: labelOverrides,
  palette: paletteOverrides,
}) {
  const palette = { ...defaultPalette, ...paletteOverrides };
  const labels = { ...defaultLabels, ...labelOverrides };
  return <Modal visible={open} transparent animationType="fade"
    onRequestClose={onClose} statusBarTranslucent>
    <View style={styles.modalRoot}>
      <Pressable accessibilityRole="button" accessibilityLabel={labels.closeMenu}
        onPress={onClose} style={[StyleSheet.absoluteFill, { backgroundColor: palette.overlay }]} />
      {links.length || children ? <View style={[styles.drawer, {
        backgroundColor: palette.sidebar, borderRightColor: palette.border,
      }]}>
        <View style={styles.drawerHeader}>
          <Text style={[styles.drawerTitle, { color: palette.text }]}>{labels.navigation}</Text>
          <Pressable accessibilityRole="button" accessibilityLabel={labels.closeMenu}
            onPress={onClose} style={({ pressed, focused }) => [styles.closeButton, {
              backgroundColor: pressed ? palette.surfaceMuted : 'transparent',
              borderRadius: palette.radius,
            }, focused && palette.focusStyle]}>
            <Text aria-hidden style={[styles.closeGlyph, { color: palette.textMuted }]}>×</Text>
          </Pressable>
        </View>
        <View style={styles.drawerBody}>
          {links.length ? <ScrollView>
            {links.map(link => <NavLink key={link.key || link.label} link={link}
              palette={palette}
              onPress={() => { onNavigate?.(link); onClose?.(); }} />)}
          </ScrollView> : null}
          {children}
        </View>
      </View> : null}
    </View>
  </Modal>;
}

export function Shell({ open = false, onToggleMenu, onCloseMenu, links, onNavigate, children, ...topBarProps }) {
  return <View style={styles.shell}>
    <TopBar {...topBarProps} menuOpen={open} onToggleMenu={onToggleMenu} />
    <MobileNav open={open} onClose={onCloseMenu} links={links}
      onNavigate={onNavigate} labels={topBarProps.labels} palette={topBarProps.palette}>
      {children}
    </MobileNav>
  </View>;
}

const styles = StyleSheet.create({
  shell: { width: '100%' },
  root: { width: '100%' },
  bar: {
    width: '100%',
    minHeight: 64,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 8,
  },
  publicBar: { justifyContent: 'space-between' },
  brand: { flex: 1, minWidth: 0, alignItems: 'flex-start' },
  logo: { width: 158, height: 36 },
  logoText: { fontSize: 20, fontWeight: '700', letterSpacing: 0.2 },
  menuButton: { width: 36, height: 40, alignItems: 'center', justifyContent: 'center', marginRight: 4 },
  bars: { width: 22, height: 16, justifyContent: 'space-between' },
  barLine: { width: 22, height: 2, borderRadius: 1 },
  searchWrap: { flex: 1, minWidth: 0, alignItems: 'center' },
  themeButton: { position: 'absolute', right: 16, top: 0, bottom: 0, width: 40, alignItems: 'center', justifyContent: 'center' },
  themeGlyph: { fontSize: 18, lineHeight: 22 },
  signIn: { paddingHorizontal: 16, paddingVertical: 8, alignItems: 'center', justifyContent: 'center' },
  signInText: { color: '#ffffff', fontSize: 13, fontWeight: '600' },
  modalRoot: { flex: 1 },
  drawer: {
    width: 288,
    maxWidth: '86%',
    height: '100%',
    borderRightWidth: 1,
    paddingTop: 8,
    paddingHorizontal: 12,
    paddingBottom: 24,
  },
  drawerBody: { flex: 1, minHeight: 0 },
  drawerHeader: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8, paddingHorizontal: 4 },
  drawerTitle: { fontSize: 15, fontWeight: '600' },
  closeButton: { width: 36, height: 36, alignItems: 'center', justifyContent: 'center' },
  closeGlyph: { fontSize: 24, lineHeight: 26 },
  navLink: { paddingHorizontal: 12, paddingVertical: 10, marginBottom: 2 },
  navLinkText: { fontSize: 14 },
});
