import React, { useState } from 'react';
import { Pressable, StyleSheet, Text, useWindowDimensions, View } from 'react-native';
import { Icon } from '../ui/Icon';
import { SettingsNavLink } from './SettingsNavLink';

// The Django settings navigation is the source for this model: the same groups,
// items, order, labels and superuser-only entry appear on the web page and in
// the Expo client. Adapters map `onNavigate(item)` to a URL or an Expo route and
// supply the icon renderer; the composition owns the menu structure.
export const settingsNavigation = [
  {
    id: 'general',
    title: 'General',
    items: [
      { id: 'account', label: 'Account', page: 'settingsAccount', icon: 'person' },
      { id: 'preferences', label: 'Preferences', page: 'settingsPreferences', icon: 'vertical-sliders' },
      { id: 'notifications', label: 'Notifications', page: 'settingsNotifications', icon: 'bell' },
    ],
  },
  {
    id: 'display',
    title: 'Display',
    items: [
      { id: 'appearance', label: 'Appearance', page: 'settingsAppearance', icon: 'sun' },
      { id: 'cards', label: 'Media Cards', page: 'settingsCards', icon: 'grid' },
      { id: 'sidebar', label: 'Sidebar', page: 'settingsSidebar', icon: 'sidebar', availability: 'server' },
      { id: 'home', label: 'Home Screen', page: 'settingsHome', icon: 'house' },
    ],
  },
  {
    id: 'providers-data',
    title: 'Providers & Data',
    items: [
      { id: 'providers', label: 'Providers', page: 'providers', icon: 'database' },
      { id: 'activity', label: 'Activity', page: 'providerActivity', icon: 'clock', availability: 'server' },
      { id: 'data', label: 'Data Management', page: 'settingsData', icon: 'database' },
      { id: 'access', label: 'Access & Tokens', page: 'settingsAccess', icon: 'padlock' },
    ],
  },
  {
    id: 'system',
    title: 'System',
    items: [
      { id: 'advanced', label: 'Advanced', page: 'settingsAdvanced', icon: 'shield-alert' },
      { id: 'users', label: 'Users', page: 'settingsUsers', icon: 'persons', permission: 'superuser' },
      { id: 'about', label: 'About', page: 'settingsAbout', icon: 'info' },
    ],
  },
];

export const settingsLabels = {
  title: 'Settings',
  subtitle: 'Configure your account and preferences',
  menu: 'Menu',
  serverOnly: 'Server only',
  current: 'Current page',
};

function canSee(item, permissions) {
  return !item.permission || Boolean(permissions?.[item.permission]);
}

function isAvailable(item, availablePages) {
  if (availablePages) return availablePages.includes(item.page);
  return item.availability !== 'server';
}

export function SettingsNav({
  navigation = settingsNavigation,
  active,
  onNavigate,
  permissions = {},
  availablePages,
  labels = {},
  palette = {},
  icons = {},
  renderIcon,
  collapsible = false,
}) {
  const copy = { ...settingsLabels, ...(labels || {}) };
  const [open, setOpen] = useState(false);
  const activeItem = navigation.flatMap(group => group.items)
    .find(item => item.page === active || item.id === active);
  const menuLabel = activeItem?.label || copy.menu;

  return <View testID="settings-nav" style={[styles.navCard, {
    backgroundColor: palette.surface || '#27272a',
    borderRadius: palette.radius ?? 8,
  }]}>
    {collapsible ? <Pressable accessibilityRole="button" accessibilityLabel={copy.menu}
      aria-expanded={open} onPress={() => setOpen(value => !value)}
      style={styles.menuButton}>
      <View style={styles.menuCurrent}>
        {activeItem?.iconSpec ? <View style={styles.itemIcon}><Icon spec={activeItem.iconSpec} /></View>
          : renderIcon && activeItem ? <View style={styles.itemIcon}>{renderIcon(activeItem.icon, activeItem)}</View> : null}
        <Text style={[styles.menuText, { color: palette.text || '#fafafa' }]}>{menuLabel}</Text>
      </View>
      {icons.chevron ? <View style={[styles.menuChevronIcon, open && styles.menuChevronOpen]}>
        <Icon spec={icons.chevron} />
      </View> : <Text style={[styles.menuChevron, { color: palette.textMuted || '#a1a1aa' }]}>{open ? '⌃' : '⌄'}</Text>}
    </Pressable> : null}
    {!collapsible || open ? <View style={styles.navBody}>
      {navigation.map(group => {
        const items = group.items.filter(item => canSee(item, permissions));
        if (!items.length) return null;
        return <View key={group.id} style={styles.group}>
          <Text style={[styles.groupTitle, { color: palette.textMuted || '#a1a1aa' }]}>{group.title}</Text>
          {items.map(item => {
            const current = activeItem?.id === item.id;
            const available = isAvailable(item, availablePages);
            return <SettingsNavLink key={item.id} item={item} current={current}
              available={available} labels={copy} palette={palette}
              renderIcon={renderIcon}
              onPress={available ? () => {
                onNavigate?.(item);
                if (collapsible) setOpen(false);
              } : undefined} />;
          })}
        </View>;
      })}
    </View> : null}
  </View>;
}

// One settings page for web and Expo. `content` is the page's shared section
// composition; adapters pass the server/native model and intents through it.
export function SettingsView({
  active,
  onNavigate,
  navigation = settingsNavigation,
  permissions = {},
  availablePages,
  labels = {},
  palette = {},
  icons = {},
  renderIcon,
  collapsible,
  children,
}) {
  const copy = { ...settingsLabels, ...(labels || {}) };
  const { width } = useWindowDimensions();
  const narrow = width < 600;
  const menuCollapsible = collapsible ?? narrow;
  return <View style={styles.root}>
    <View style={styles.pageHeading}>
      <Text role="heading" aria-level={1} style={[styles.title, { color: palette.text || '#fafafa' }]}>{copy.title}</Text>
      <Text style={[styles.subtitle, { color: palette.textMuted || '#a1a1aa' }]}>{copy.subtitle}</Text>
    </View>
    <View style={styles.layout}>
      <View style={[styles.navColumn, narrow && styles.navColumnNarrow]}>
        <SettingsNav navigation={navigation} active={active} onNavigate={onNavigate}
          permissions={permissions} availablePages={availablePages} labels={labels}
          palette={palette} icons={icons} renderIcon={renderIcon}
          collapsible={menuCollapsible} />
      </View>
      <View style={styles.contentColumn}>{children}</View>
    </View>
  </View>;
}

// Page-level heading and section stack. Every settings provider/auth/error page
// composition uses this so the order and spacing do not diverge per platform.
export function SettingsPage({ title, copy, palette = {}, children, actions, heading = true }) {
  return <View style={[styles.content, palette.pageCards && { gap: palette.pageGap ?? 24 }]}>
    {heading ? <View style={styles.contentHeading}>
      <View style={styles.contentHeadingText}>
        <Text role="heading" aria-level={2} style={[styles.pageTitle, { color: palette.text || '#fafafa' }, palette.pageCards && { fontSize: 20 }]}>{title}</Text>
        {copy ? <Text style={[styles.pageCopy, { color: palette.textMuted || '#a1a1aa' }]}>{copy}</Text> : null}
      </View>
      {actions || null}
    </View> : null}
    {children}
  </View>;
}

const styles = StyleSheet.create({
  root: { gap: 32, minWidth: 0 },
  pageHeading: { gap: 8 },
  title: { fontSize: 30, fontWeight: '700', lineHeight: 36 },
  subtitle: { fontSize: 14, lineHeight: 20 },
  layout: { flexDirection: 'row', flexWrap: 'wrap', gap: 32, alignItems: 'flex-start' },
  navColumn: { flexGrow: 0, flexShrink: 0, flexBasis: 256, minWidth: 220, maxWidth: 320 },
  navColumnNarrow: { flexBasis: '100%', maxWidth: '100%', width: '100%' },
  contentColumn: { flexGrow: 1, flexShrink: 1, flexBasis: 320, minWidth: 0 },
  navCard: { overflow: 'hidden' },
  menuButton: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', paddingHorizontal: 16, paddingVertical: 12, minHeight: 44 },
  menuCurrent: { flexDirection: 'row', alignItems: 'center', gap: 12, minWidth: 0 },
  itemIcon: { alignItems: 'center', justifyContent: 'center', width: 20, height: 20 },
  menuText: { fontSize: 14, lineHeight: 20 },
  menuChevron: { fontSize: 14 },
  menuChevronIcon: { width: 16, height: 16, alignItems: 'center', justifyContent: 'center' },
  menuChevronOpen: { transform: [{ rotate: '180deg' }] },
  navBody: { padding: 8, gap: 2 },
  group: { gap: 2, paddingBottom: 4 },
  groupTitle: { paddingHorizontal: 8, paddingTop: 4, paddingBottom: 4, fontSize: 12, lineHeight: 16, fontWeight: '500', textTransform: 'uppercase', letterSpacing: 0.6 },
  content: { gap: 16, minWidth: 0 },
  contentHeading: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'flex-start', justifyContent: 'space-between', gap: 12 },
  contentHeadingText: { gap: 4, flexGrow: 1, flexShrink: 1, minWidth: 0 },
  pageTitle: { fontSize: 22, fontWeight: '600', lineHeight: 28 },
  pageCopy: { fontSize: 13, lineHeight: 19 },
});
