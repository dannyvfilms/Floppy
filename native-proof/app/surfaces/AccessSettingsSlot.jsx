import React, { useRef, useState } from 'react';
import { Text } from 'react-native';
import { Icon } from '../../../frontend/ui/Icon';
import { settingsNavIcons } from '../settingsNavIcons';
import { SettingsAccessView } from '../../../frontend/pages/SettingsAccessView';
import { copyText } from '../data/fileFlows';
import {
  applicationsFromPayload,
  maskToken,
  tokensFromPayload,
} from '../data/settingsTransport';
import SettingsLoadState from './SettingsLoadState';
import { useSettingsPalettes } from './settingsPalettes';
import { useSettingsResource } from './useSettingsResource';

// One status line per card: busy flag, last error and last success message.
function useCardStatus() {
  const [status, setStatus] = useState({ busy: false, error: '', success: '' });
  async function run(action, successMessage, failureMessage) {
    setStatus({ busy: true, error: '', success: '' });
    try {
      const result = await action();
      setStatus({ busy: false, error: '', success: typeof successMessage === 'function' ? successMessage(result) : successMessage });
      return result;
    } catch (cause) {
      const error = cause?.message || failureMessage;
      setStatus({ busy: false, error, success: '' });
      throw cause;
    }
  }
  return [status, run, setStatus];
}

function AccessForm({ transport, data, page, onOpenApplications }) {
  const { settingsPalette, buttonPalette } = useSettingsPalettes();
  const [token, setToken] = useState(data.account.token || '');
  const [tokenStatus, runToken, setTokenStatus] = useCardStatus();
  const [appTokens, setAppTokens] = useState(() => tokensFromPayload(data.tokens));
  const [appStatus, runApp, setAppStatus] = useCardStatus();
  const secretRef = useRef(null);
  const [oneTimeSecret, setOneTimeSecret] = useState(null);
  const [applications, setApplications] = useState(() => applicationsFromPayload(data.applications));
  const [applicationStatus, runApplication] = useCardStatus();

  async function copyToken() {
    try {
      await copyText(token);
      setTokenStatus({ busy: false, error: '', success: 'API token copied.' });
    } catch {
      setTokenStatus({ busy: false, error: 'The token could not be copied.', success: '' });
    }
  }

  async function regenerate() {
    const result = await runToken(
      () => transport.regenerateAccountToken(),
      'Token regenerated successfully.',
      'Could not regenerate the token.',
    );
    setToken(result?.token || '');
  }

  async function createToken({ name, expiresInDays, scopes }) {
    const created = await runApp(
      () => transport.createAppToken({ name, expiresInDays, scopes }),
      result => `Created token '${result.name}'. Copy the secret now.`,
      'Could not create the token.',
    );
    secretRef.current = created.secret;
    setOneTimeSecret({ id: created.id, name: created.name, preview: `${created.prefix}…` });
    const [row] = tokensFromPayload({ results: [created], scope_choices: [] }).tokens;
    setAppTokens(current => ({ ...current, tokens: [row, ...current.tokens] }));
  }

  async function revokeToken(item) {
    await runApp(() => transport.revokeAppToken({ id: item.id }), `Revoked token '${item.name}'.`, 'Could not revoke the token.');
    setAppTokens(current => ({ ...current, tokens: current.tokens.filter(entry => entry.id !== item.id) }));
    if (oneTimeSecret?.id === item.id) {
      secretRef.current = null;
      setOneTimeSecret(null);
    }
  }

  async function copySecret() {
    try {
      await copyText(secretRef.current || '');
      setAppStatus(current => ({ ...current, error: '', success: 'One-time secret copied.' }));
    } catch {
      setAppStatus(current => ({ ...current, error: 'The secret could not be copied.', success: '' }));
    }
  }

  async function revokeApplication(application) {
    await runApplication(
      () => transport.revokeApplication({ clientId: application.clientId }),
      `Access for '${application.name}' revoked.`,
      'Could not revoke access.',
    );
    setApplications(current => current.filter(entry => entry.id !== application.id));
  }

  return <SettingsAccessView
    showCatalogGrants={false}
    applicationsOnly={page === 'applications'} onOpenApplications={onOpenApplications}
    accountToken={{
      sessionRequired: !transport.canManageCredentials,
      icon: <Icon spec={settingsNavIcons.padlock} color={settingsPalette.link} size={20} />,
      tokenSlot: <Text selectable accessibilityLabel="API token" style={{ color: settingsPalette.textSecondary, fontFamily: 'monospace', fontSize: 14, flex: 1 }}>{token}</Text>,
      labels: { accountTokenDescription: 'This token authenticates webhook requests from your media servers. It has full access to your account, so for apps and API clients create an app token below instead. Those can be limited and revoked one at a time.' },
      maskedToken: maskToken(token) || 'No token yet', ...tokenStatus,
      onCopy: copyToken, onRegenerate: regenerate,
    }}
    appTokens={{
      icon: <Icon spec={settingsNavIcons.padlock} color={settingsPalette.link} size={20} />,
      secretSlot: oneTimeSecret ? <Text selectable accessibilityLabel="New token secret" style={{ color: settingsPalette.textSecondary, fontFamily: 'monospace', fontSize: 14, flex: 1 }}>{secretRef.current}</Text> : null,
      model: { sessionRequired: !transport.canManageCredentials, tokens: appTokens.tokens, scopes: appTokens.scopes, presetScopes: appTokens.presetScopes, oneTimeSecret, collapsible: true },
      ...appStatus, onCreate: createToken, onRevoke: revokeToken, onCopySecret: copySecret,
    }}
    applications={{ applications, ...applicationStatus, onRevoke: revokeApplication, separateHeader: page === 'applications',
      labels: { oauthTitle: 'Connected Applications', oauthDescription: "Review applications authorised through Floppy's OAuth device flow and revoke access when it is no longer needed.", noApplications: 'No applications currently have OAuth access to your Floppy account.' } }}
    palette={page === 'applications' ? { ...settingsPalette, pageCards: true } : { ...settingsPalette, pageCards: 'access', background: settingsPalette.surfaceStrong }} buttonPalette={buttonPalette} />;
}

export default function AccessSettingsSlot({ page = 'access', onOpenApplications }) {
  const resource = useSettingsResource(transport => transport.loadAccess());
  if (resource.state !== 'ready') {
    return <SettingsLoadState state={resource.state} message={resource.message} onRetry={resource.reload} />;
  }
  return <AccessForm transport={resource.transport} data={resource.data} page={page} onOpenApplications={onOpenApplications} />;
}
