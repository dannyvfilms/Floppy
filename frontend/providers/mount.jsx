import React from 'react';
import { mountRoot } from '../settings/root';
import { ProviderPageView } from './ProviderPageView';
import { ProviderSettingsView } from './ProviderSettingsView';
import { ProviderActivityView } from './ProviderActivityView';
import { ProviderMetadataView } from './ProviderMetadataView';
import {
  confirmAction,
  copyText,
  readThemePalette,
  savePreferenceValues,
  submitNativeForm,
} from './transport.web';

const palette = {
  background: 'var(--color-surface)',
  surface: 'var(--color-surface)',
  surfaceStrong: 'var(--color-surface-strong)',
  surfaceMuted: 'var(--color-surface-muted)',
  border: 'var(--color-surface-border)',
  text: 'var(--color-text)',
  textSecondary: 'var(--color-text-secondary)',
  textMuted: 'var(--color-text-muted)',
  link: 'var(--color-link)',
  accent: 'var(--color-accent)',
  accentStrong: 'var(--color-accent)',
  accentText: 'var(--color-accent-contrast)',
  danger: 'var(--color-error-text)',
  success: 'var(--color-status-clean)',
  warning: 'var(--color-warning-text)',
  focus: 'var(--color-accent)',
  radius: 'var(--theme-radius, .5rem)',
  badgeBorder: 'var(--color-surface-border)',
  badgeBackground: 'var(--color-surface-strong)',
  badgeText: 'var(--color-text-secondary)',
  badgeHover: 'var(--color-surface-hover)',
  fontFamily: 'inherit',
  interactiveStyle: {
    cursor: 'pointer', textDecorationLine: 'none',
    transitionProperty: 'background-color, border-color, color, box-shadow',
  },
  focusStyle: {},
  infoBorder: 'rgba(99, 102, 241, .3)',
  infoBackground: 'rgba(99, 102, 241, .1)',
  infoBadgeBorder: 'rgba(99, 102, 241, .3)',
  infoBadgeBackground: 'rgba(99, 102, 241, .1)',
  infoBadgeText: 'var(--color-info-text)',
  warningBorder: 'rgba(245, 158, 11, .3)',
  warningBackground: 'rgba(245, 158, 11, .1)',
  warningBadgeBorder: 'rgba(245, 158, 11, .4)',
  warningBadgeBackground: 'rgba(245, 158, 11, .2)',
  warningBadgeText: 'var(--color-warning-text)',
};

function providerPalette() {
  return { ...readThemePalette(), ...palette };
}

function draftFromFallback(host, model) {
  // Preserve edits made to the fallback while the lazy module was loading.
  // These are local drafts only; no saved keys arrive in the serialized model.
  const draft = { instance: {}, personal: {}, preferences: {} };
  for (const form of host.querySelectorAll('form')) {
    const scope = form.getAttribute('action') === model.credentials?.personalUrl ? 'personal' : 'instance';
    for (const input of form.querySelectorAll('input[name="client_id"], input[name="client_secret"]')) {
      if (!input.disabled && input.value !== input.defaultValue) draft[scope][input.name] = input.value;
    }
  }
  const username = host.querySelector('input[name="user"]');
  if (username && username.value !== username.defaultValue) draft.username = username.value;
  const privateImport = host.querySelector('input[x-model="usePrivateImport"]');
  if (privateImport?.checked) draft.privateImport = true;
  for (const [name, key] of [['import_frequency', 'frequency'], ['import_mode', 'mode'], ['import_time', 'time']]) {
    const field = host.querySelector(`[name="${name}"]`);
    if (!field) continue;
    const original = field.tagName === 'SELECT' ? [...field.options].find(option => option.defaultSelected)?.value ?? field.options[0].value : field.defaultValue;
    if (field.value !== original) draft.preferences[key] = field.value;
  }
  return draft;
}

function importValues(preferences = {}) {
  return {
    frequency: preferences.frequency ?? '',
    time: preferences.time ?? '',
    mode: preferences.mode ?? '',
  };
}

export function mountProvider(host, model) {
  const draft = draftFromFallback(host, model);
  const colors = providerPalette();
  const t = text => model.labels?.[text] ?? text;
  const onOpenUrl = url => { if (url) window.location.assign(url); };
  const onNavigate = url => { if (url) window.location.assign(url); };
  const credentials = model.credentials;
  const imports = model.imports || model.import;
  const account = model.account || model.accountConnection;
  const metadata = model.metadata;
  const csrf = model.csrf;
  const returnTo = model.next;

  function saveCredentials(kind, values) {
    return submitNativeForm({
      action: kind === 'personal' ? credentials?.personalUrl : credentials?.saveUrl,
      csrf,
      returnTo,
      values,
    });
  }

  function clearCredentials() {
    return submitNativeForm({ action: credentials?.clearUrl, csrf, returnTo, values: {} });
  }

  function setDefaultProvider(item) {
    return submitNativeForm({
      action: item?.action,
      csrf,
      returnTo,
      values: { source: credentials?.slug },
    });
  }

  function savePreferences(values) {
    return savePreferenceValues({ url: imports?.saveUrl, csrf, values });
  }

  function startImport({ private: isPrivate, username, preferences }) {
    return submitNativeForm({
      action: isPrivate ? imports?.privateUrl : imports?.publicUrl,
      csrf,
      returnTo,
      values: { ...importValues(preferences), ...(isPrivate ? {} : { user: username }) },
    });
  }

  function connectAccount(values) {
    return submitNativeForm({ action: account?.connectUrl, csrf, returnTo, values });
  }

  function disconnectAccount(instanceId) {
    return submitNativeForm({
      action: account?.disconnectUrl,
      csrf,
      returnTo,
      values: instanceId ? { instance_id: instanceId } : {},
    });
  }

  function saveProxy(url) {
    return submitNativeForm({
      action: metadata?.proxy?.action,
      csrf,
      returnTo,
      values: { tmdb_proxy_url: url ?? '' },
    });
  }

  function saveSource({ source, animeMode, action }) {
    return submitNativeForm({
      action,
      csrf,
      returnTo,
      values: {
        source,
        ...(animeMode !== undefined ? { anime_library_mode: animeMode } : {}),
      },
    });
  }

  function moveEntries({ action }) {
    return submitNativeForm({ action, csrf, returnTo, values: {} });
  }

  async function fetchActivity({ page, signal }) {
    if (!model.activityUrl) throw new Error('Activity is not available.');
    const separator = model.activityUrl.includes('?') ? '&' : '?';
    const response = await fetch(`${model.activityUrl}${separator}page=${page}`, {
      signal,
      credentials: 'same-origin',
      headers: { Accept: 'application/json' },
    });
    if (!response.ok || !response.headers.get('content-type')?.includes('application/json')) {
      throw new Error('Activity unavailable');
    }
    return response.json();
  }

  const onOpenLink = url => { if (url) window.open(url, '_blank', 'noopener'); };
  const linkPropsForUrl = url => url ? {
    href: url,
    hrefAttrs: { target: '_blank', rel: 'noopener noreferrer' },
  } : {};
  const browserModel = {
    ...model,
    overviewCards: (model.overviewCards || []).map(card => ({
      ...card,
      linkProps: card.url ? {
        href: card.url,
        // RN Web does not forward an HTML title on Pressable. Keep the real
        // browser hover hint in the web adapter; native uses accessibilityHint.
        ref: node => {
          if (node && card.tooltip) node.setAttribute('title', card.tooltip);
        },
      } : {},
    })),
  };

  return mountRoot(host, <ProviderPageView
    model={browserModel}
    draft={draft}
    palette={colors}
    onOpenUrl={onOpenUrl}
    onNavigate={onNavigate}
    slots={{
      connection: ({ palette: slotPalette, buttonPalette }) => <ProviderSettingsView
        model={{ ...model, credentials, account, labels: model.labels }}
        tab="connection"
        palette={slotPalette}
        buttonPalette={buttonPalette}
        onSave={saveCredentials}
        onClear={clearCredentials}
        onOpenLink={onOpenLink}
        linkPropsForUrl={linkPropsForUrl}
        onSetDefault={setDefaultProvider}
        onFollowUp={onNavigate}
        onConnect={connectAccount}
        onDisconnect={disconnectAccount}
        onCopy={copyText}
        labels={model.credentials?.labels}
      />,
      import: ({ palette: slotPalette, buttonPalette }) => <ProviderSettingsView
        model={{ ...model, imports, labels: model.labels }}
        tab="import"
        palette={slotPalette}
        buttonPalette={buttonPalette}
        onImport={startImport}
        onSavePreferences={savePreferences}
        onConfigure={() => onNavigate(model.urls?.connection)}
        onOpenLink={onOpenLink}
        onCopy={copyText}
        labels={model.imports?.labels}
      />,
      activity: ({ palette: slotPalette, buttonPalette }) => <ProviderActivityView
        model={{ labels: model.labels, csrf, next: returnTo }}
        palette={slotPalette}
        buttonPalette={buttonPalette}
        onFetch={fetchActivity}
        onCopy={copyText}
        onConfirm={confirmAction}
        onSubmit={submitNativeForm}
        t={t}
      />,
      metadata: ({ palette: slotPalette, buttonPalette }) => <ProviderMetadataView
        model={model}
        palette={slotPalette}
        buttonPalette={buttonPalette}
        onSaveProxy={saveProxy}
        onSaveSource={saveSource}
        onMove={moveEntries}
        onOpenLink={onNavigate}
      />,
    }}
  />);
}
