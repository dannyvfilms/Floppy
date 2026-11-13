import React from 'react';
import { View } from 'react-native';
import { mountRoot } from './root';
import { SettingsView } from '../pages/SettingsView';
import { SettingsAccountView } from '../pages/SettingsAccountView';
import { SettingsPreferencesView } from '../pages/SettingsPreferencesView';
import { SettingsAppearanceView } from '../pages/SettingsAppearanceView';
import { SettingsCardsView } from '../pages/SettingsCardsView';
import { SettingsHomeView } from '../pages/SettingsHomeScreenView';
import { SettingsNotificationsView } from '../pages/SettingsNotificationsView';
import { SettingsDataView } from '../pages/SettingsDataView';
import { SettingsAccessView } from '../pages/SettingsAccessView';
import { SettingsAdvancedView } from '../pages/SettingsAdvancedView';
import { SettingsAboutView } from '../pages/SettingsAboutView';
import { SettingsUsersView } from '../pages/SettingsUsersView';
import { ProvidersView, ProviderActivityPage } from '../pages/ProvidersView';

// Browser adapter for the shared settings page composition. The navigation model
// (groups, order, labels, URLs and parsed icons) comes from the server, the same
// shape the Expo tab uses. Existing server-owned forms stay in the DOM and are
// moved into the composition's page slot, so CSRF, posts, validation, Alpine and
// provider islands keep working while React owns the settings chrome.
const PAGES = {
  settingsAccount: SettingsAccountView,
  settingsPreferences: SettingsPreferencesView,
  settingsAppearance: SettingsAppearanceView,
  settingsCards: SettingsCardsView,
  settingsHome: SettingsHomeView,
  settingsNotifications: SettingsNotificationsView,
  settingsData: SettingsDataView,
  settingsAccess: SettingsAccessView,
  settingsAdvanced: SettingsAdvancedView,
  settingsAbout: SettingsAboutView,
  settingsUsers: SettingsUsersView,
  providers: ProvidersView,
  providerActivity: ProviderActivityPage,
};

const pagePalette = {
  text: 'var(--color-text)',
  textSecondary: 'var(--color-text-secondary)',
  textMuted: 'var(--color-text-muted)',
  surface: 'var(--color-surface)',
  surfaceStrong: 'var(--color-surface-strong)',
  surfaceMuted: 'var(--color-surface-muted)',
  border: 'var(--color-surface-border)',
  accent: 'var(--color-link)',
  accentStrong: 'var(--color-link)',
  focusStyle: {},
  radius: 8,
};

// Keep the server-rendered page body in place. React mounts a plain container and
// the original node is re-parented into it; unmount restores the cloned fallback.
function ServerContent({ node }) {
  const attach = element => {
    if (element && node && node.parentNode !== element) element.appendChild(node);
  };
  return <View ref={attach} style={{ minWidth: 0 }} />;
}

export function mountSettingsView(host, props) {
  const content = host.querySelector('[data-settings-page-content]');
  const Page = PAGES[props.page];
  const contentSlot = content ? <ServerContent node={content} /> : null;
  const dispose = mountRoot(host, <SettingsView
    active={props.active}
    navigation={props.navigation}
    permissions={props.permissions}
    availablePages={props.availablePages}
    labels={props.labels}
    icons={props.icons}
    palette={pagePalette}>
    {Page
      ? <Page heading={false} content={contentSlot} labels={props.labels} palette={pagePalette} />
      : contentSlot}
  </SettingsView>);
  // Anchors rendered by React are new to HTMX. Boost only the navigation card so
  // settings links keep the body-swap behavior and content links keep their
  // normal navigation, matching the server fallback.
  const nav = host.querySelector('[data-testid="settings-nav"]');
  if (nav) {
    nav.setAttribute('hx-boost', 'true');
    if (typeof window !== 'undefined' && window.htmx?.process) window.htmx.process(nav);
  }
  return dispose;
}
