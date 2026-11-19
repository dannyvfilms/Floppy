import React, { useEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import { View } from 'react-native';
import { mountRoot } from './root';
import { SelectField } from '../ui/SelectField';
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

const preferenceFieldPalette = {
  surface: 'var(--color-panel)',
  surfaceStrong: 'var(--color-surface-strong)',
  surfaceMuted: 'var(--color-surface-muted)',
  border: 'var(--color-surface-border)',
  fieldBorder: 'var(--color-surface-border)',
  text: 'var(--color-text)',
  textSecondary: 'var(--color-text-secondary)',
  textMuted: 'var(--color-text-muted)',
  accent: 'var(--color-link)',
  accentStrong: 'var(--color-link)',
  accentText: 'var(--color-text)',
  overlay: 'rgba(0, 0, 0, 0.55)',
  disabled: 'var(--color-text-muted)',
  preferenceCards: true,
};

function DefaultEditEntryDateField({ field }) {
  const fallback = field?.querySelector('[data-default-edit-entry-date-fallback]');
  const fallbackSelect = fallback?.querySelector('select[name="default_edit_entry_date"]');
  const reactRoot = field?.querySelector('[data-default-edit-entry-date-react]');
  const valueInput = field?.querySelector('[data-default-edit-entry-date-value]');
  const [value, setValue] = useState(fallbackSelect?.value || 'current_date');

  useEffect(() => {
    if (!fallback || !fallbackSelect || !reactRoot || !valueInput) return undefined;
    valueInput.value = fallbackSelect.value;
    valueInput.disabled = false;
    fallbackSelect.disabled = true;
    fallback.hidden = true;
    reactRoot.hidden = false;
    return () => {
      fallbackSelect.value = valueInput.value;
      fallbackSelect.disabled = false;
      valueInput.disabled = true;
      fallback.hidden = false;
      reactRoot.hidden = true;
    };
  }, [fallback, fallbackSelect, reactRoot, valueInput]);

  if (!fallbackSelect || !reactRoot || !valueInput) return null;
  const options = Array.from(fallbackSelect.options, option => ({
    value: option.value,
    label: option.textContent || '',
  }));
  const change = event => {
    const nextValue = String(event.target.value);
    setValue(nextValue);
    valueInput.value = nextValue;
    valueInput.dispatchEvent(new Event('input', { bubbles: true }));
    valueInput.dispatchEvent(new Event('change', { bubbles: true }));
  };

  return createPortal(<SelectField
    id="default_edit_entry_date"
    name="default_edit_entry_date"
    label={field.dataset.label}
    help={field.dataset.help}
    options={options}
    value={value}
    palette={preferenceFieldPalette}
    iconChevron
    onChange={change}
  />, reactRoot);
}

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
  const defaultEndDateField = props.page === 'settingsPreferences'
    ? content?.querySelector('[data-default-edit-entry-date-field]')
    : null;
  const Page = PAGES[props.page];
  const contentSlot = content ? <ServerContent node={content} /> : null;
  const dispose = mountRoot(host, <>
    <SettingsView
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
    </SettingsView>
    {defaultEndDateField ? <DefaultEditEntryDateField field={defaultEndDateField} /> : null}
  </>);
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
