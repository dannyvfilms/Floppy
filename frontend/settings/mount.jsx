import React from 'react';
import { SettingsCard } from './SettingsCard';
import { webPalette } from './webPalette';
import { mountRoot } from './root';
import { UsersManagement } from '../users/UsersManagement';
import { Chip as SharedChip } from './Chip';
import { Tooltip } from '../ui/controls/Tooltip';

const tooltipPalette = {
  triggerText: 'var(--color-text-muted)',
  bubbleBackground: 'var(--color-surface-strong)',
  bubbleBorder: 'var(--color-surface-border)',
  bubbleText: 'var(--color-text)',
  closeText: 'var(--color-text-muted)',
};

const usersPalette = {
  ...webPalette,
  text: 'var(--color-text)',
  textSecondary: 'var(--color-text-secondary)',
  textMuted: 'var(--color-text-muted)',
  border: 'var(--color-surface-border)',
  background: 'var(--color-surface-strong)',
  surface: 'var(--color-surface)',
  surfaceStrong: 'var(--color-surface-strong)',
  surfaceMuted: 'var(--color-surface-muted)',
  accent: 'var(--color-link)',
  accentStrong: 'var(--color-accent)',
  accentText: 'var(--color-accent-contrast)',
  danger: 'var(--color-error-text)',
  success: 'var(--color-status-clean)',
  warning: 'var(--color-warning-text)',
  overlay: 'rgba(0, 0, 0, 0.55)',
  badgeBorder: 'var(--color-surface-border)',
  badgeBackground: 'var(--color-surface-strong)',
  badgeText: 'var(--color-text-secondary)',
  badgeHover: 'var(--color-surface-hover)',
  fontFamily: 'inherit',
  radius: 'var(--theme-radius, 18px)',
  focusStyle: {},
};

function managedUserRequest(url, body, csrfToken) {
  return fetch(url, {
    method: 'POST',
    credentials: 'same-origin',
    headers: {
      Accept: 'application/json',
      'Content-Type': 'application/json',
      'X-CSRFToken': csrfToken,
    },
    body: JSON.stringify(body || {}),
  }).then(async response => {
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error || 'Request failed');
    return data;
  });
}

function managedUserUrl(template, id) {
  return template.replace('{id}', String(id));
}

export function mountLinkChip(host, props) {
  return mountRoot(host, <SharedChip {...props} palette={webPalette} />);
}

export function mountTooltip(host, props) {
  return mountRoot(host, <Tooltip {...props} palette={tooltipPalette} />);
}

export function mountCard(host, props) {
  return mountRoot(host, <SettingsCard {...props} palette={webPalette} framed={false}
      onInfo={props.info_label ? (event) => {
        host.dispatchEvent(new CustomEvent('settings-card:info', {
          bubbles: true, detail: { trigger: event.currentTarget },
        }));
      } : undefined} />);
}

export function mountUsersManagement(host, props) {
  const actions = {
    create: values => managedUserRequest(props.urls.create, values, props.csrfToken),
    update: (id, values) => managedUserRequest(
      managedUserUrl(props.urls.update, id), values, props.csrfToken),
    setPassword: (id, values) => managedUserRequest(
      managedUserUrl(props.urls.password, id), values, props.csrfToken),
    remove: id => managedUserRequest(
      managedUserUrl(props.urls.delete, id), {}, props.csrfToken),
  };
  return mountRoot(host, <UsersManagement initialUsers={props.users}
    labels={props.labels} palette={usersPalette} actions={actions} />);
}
