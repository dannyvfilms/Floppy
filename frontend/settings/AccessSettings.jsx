import React, { useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { Button } from '../ui/Button';
import { SelectField } from '../ui/SelectField';
import { TextField } from '../ui/TextField';
import { ToggleChip } from '../ui/ToggleChip';
import { Chip } from './Chip';
import { ConfirmDialog } from './ConfirmDialog';
import { SettingsCard } from './SettingsCard';
import { Icon } from '../ui/Icon';
import { actionIcons } from '../ui/actionIcons';

const defaultPalette = {
  background: '#18181b',
  surface: '#27272a',
  surfaceStrong: '#3f3f46',
  surfaceMuted: '#52525b',
  border: '#52525b',
  text: '#fafafa',
  textSecondary: '#d4d4d8',
  textMuted: '#a1a1aa',
  accent: '#6366f1',
  accentStrong: '#4f46e5',
  success: '#10b981',
  warning: '#f59e0b',
  danger: '#ef4444',
  badgeBorder: '#52525b',
  badgeBackground: '#3f3f46',
  badgeText: '#d4d4d8',
  badgeHover: '#52525b',
  radius: 6,
  focusStyle: {},
};

const defaultButtonPalette = {
  primary: { background: '#4f46e5', pressed: '#4338ca', hovered: '#4338ca', text: '#ffffff', border: 'transparent' },
  surface: { background: '#3f3f46', pressed: '#52525b', hovered: '#52525b', text: '#fafafa', border: '#3f3f46' },
  'danger-solid': { background: '#dc2626', pressed: '#b91c1c', hovered: '#b91c1c', text: '#ffffff', border: 'transparent' },
  'ghost-danger': { background: 'transparent', pressed: 'rgba(220, 38, 38, 0.18)', hovered: 'rgba(220, 38, 38, 0.18)', text: '#f87171', border: 'transparent' },
  radius: 6,
  focusStyle: {},
};

const defaultLabels = {
  accountTokenTitle: 'API Token',
  accountTokenBadge: 'Full access',
  accountTokenDescription: 'This token authenticates webhook requests from your media servers. It has full access to your account, so for apps and API clients create an app token below instead, those can be limited and revoked one at a time.',
  copy: 'Copy',
  regenerate: 'Regenerate',
  regenerateTitle: 'Regenerate the API token?',
  regenerateCopy: 'The previous token stops working immediately. Webhooks and RSS feed links that use it will fail until they are updated.',
  appTokensTitle: 'App tokens',
  appTokensDescription: 'Give each app its own token with only the permissions it needs. Revoking one leaves your other apps connected.',
  appTokenCreated: 'Token created',
  appTokenCopy: 'Copy it now. Floppy stores only a hash, so this is the only time it can be shown.',
  copySecret: 'Copy secret',
  noAppTokens: 'No app tokens yet.',
  name: 'Name',
  namePlaceholder: 'Nuvio living room',
  expires: 'Expires',
  permissions: 'Permissions',
  presetHint: 'Pre-selected for a tracking client: scrobbling, resume progress and saved items.',
  createToken: 'Create token',
  creatingToken: 'Creating token…',
  revoke: 'Revoke',
  revokeTitle: 'Revoke this token?',
  revokeCopy: 'The token stops working immediately. Your other apps are unaffected.',
  expired: 'Expired',
  created: 'Created',
  lastUsed: 'Last used',
  neverUsed: 'Never used',
  expiresOn: 'Expires',
  catalogTitle: 'Install credentials',
  catalogDescription: 'Create one credential per install. Revoking it breaks only that install, not your account token.',
  noGrants: 'No install credentials yet. The add-on URL uses your account token.',
  installName: 'Install name',
  installPlaceholder: 'Living room TV',
  allowPlayback: 'Mark items in progress on playback',
  createInstall: 'Create install',
  creatingInstall: 'Creating install…',
  catalogsOnly: 'Catalogs only',
  oauthTitle: 'Connected applications',
  oauthDescription: 'Applications authorised through the OAuth device flow. Revoke access when it is no longer needed.',
  noApplications: 'No applications currently have OAuth access to your account.',
  clientRevoked: 'Client revoked',
  connected: 'Connected',
  oauthRevoke: 'Revoke access',
  oauthRevokeTitle: 'Revoke application access?',
  oauthRevokeCopy: 'Every OAuth token issued to this application for your account is revoked immediately.',
};

const expiryOptions = [
  { value: '', label: 'Never' },
  { value: '30', label: '30 days' },
  { value: '90', label: '90 days' },
  { value: '365', label: '1 year' },
];

function StatusLine({ busy, error, success, palette }) {
  if (!busy && !error && !success) return null;
  const color = error ? palette.danger : success ? palette.success : palette.textMuted;
  return <Text accessibilityRole={error ? 'alert' : undefined} accessibilityLiveRegion="polite"
    style={[styles.status, { color }]}>{error || success || (typeof busy === 'string' ? busy : 'Working…')}</Text>;
}

function ScopeChips({ scopes = [], palette }) {
  if (!scopes.length) return null;
  return <View style={styles.chipRow}>{scopes.map(scope => <Chip key={scope} label={scope} palette={palette} />)}</View>;
}

function TokenMeta({ createdAt, lastUsedAt, expiresAt, expired, palette, labels }) {
  return <>
    <Text style={[styles.meta, { color: palette.textMuted }]}>{labels.created} {createdAt} · {lastUsedAt ? `${labels.lastUsed} ${lastUsedAt}` : labels.neverUsed}{expiresAt ? ` · ${labels.expiresOn} ${expiresAt}` : ''}</Text>
    {expired ? <Chip label={labels.expired} palette={{ ...palette, badgeBorder: palette.warning, badgeBackground: 'rgba(245, 158, 11, 0.15)', badgeText: '#fde68a' }} /> : null}
  </>;
}

export function AccessTokenCard({
  sessionRequired = false,
  icon,
  tokenSlot,
  labels: suppliedLabels,
  maskedToken = '••••••••••••',
  busy = false,
  error,
  success,
  palette = {},
  buttonPalette = {},
  onCopy,
  onRegenerate,
}) {
  const colors = { ...defaultPalette, ...palette };
  const buttons = { ...defaultButtonPalette, ...buttonPalette };
  const labels = { ...defaultLabels, ...suppliedLabels };
  const [confirming, setConfirming] = useState(false);
  const [confirmError, setConfirmError] = useState('');

  async function regenerate() {
    setConfirmError('');
    try {
      await onRegenerate?.();
      setConfirming(false);
    } catch (failure) {
      setConfirmError(failure?.message || 'Could not regenerate the token.');
    }
  }

  return <SettingsCard title={labels.accountTokenTitle} icon={icon} badge={colors.pageCards ? undefined : labels.accountTokenBadge} palette={colors}>
    <Text style={[styles.copy, { color: colors.textMuted }, colors.pageCards && { fontSize: 14, lineHeight: 20 }]}>{labels.accountTokenDescription}</Text>
    {sessionRequired ? <Text style={[styles.copy, { color: colors.textMuted }]}>Sign in with your username and password to manage this.</Text> : <>
    <View style={[styles.secretRow, { backgroundColor: colors.surfaceDim || colors.surfaceStrong, borderColor: colors.border }, colors.pageCards && { borderWidth: 0, padding: 12 }]}>
      {tokenSlot || <Text style={[styles.secret, { color: colors.textSecondary }]}>{maskedToken}</Text>}
      <Button label={labels.copy} tone="surface" onPress={onCopy} palette={buttons} />
    </View>
    <Text style={[styles.warning, { color: colors.warning }]}>{colors.pageCards ? 'Regenerating will invalidate the previous token' : 'Regenerating invalidates the previous token and every feed link that uses it.'}</Text>
    <StatusLine busy={busy} error={error} success={success} palette={colors} />
    <Button label={labels.regenerate} tone={colors.pageCards ? 'primary' : 'danger-solid'} busy={busy} disabled={busy}
      onPress={() => { setConfirmError(''); setConfirming(true); }} palette={buttons} />
    <ConfirmDialog visible={confirming} title={labels.regenerateTitle} message={labels.regenerateCopy}
      warning="This cannot be undone." confirmLabel={labels.regenerate} busy={busy}
      error={confirmError} palette={colors} buttonPalette={buttons}
      onCancel={() => setConfirming(false)} onConfirm={regenerate} />
    </>}
  </SettingsCard>;
}

export function AppTokensCard({
  icon,
  secretSlot,
  model = {},
  busy = false,
  error,
  success,
  palette = {},
  buttonPalette = {},
  onCreate,
  onRevoke,
  onCopySecret,
}) {
  const colors = { ...defaultPalette, ...palette };
  const buttons = { ...defaultButtonPalette, ...buttonPalette };
  const labels = { ...defaultLabels, ...(model.labels || {}) };
  const tokens = model.tokens || [];
  const scopes = model.scopes || [];
  const expiry = model.expiryOptions || expiryOptions;
  const [name, setName] = useState('');
  const [expiresInDays, setExpiresInDays] = useState('');
  const [selectedScopes, setSelectedScopes] = useState(model.presetScopes || []);
  const [pending, setPending] = useState(null);
  const [confirmError, setConfirmError] = useState('');
  const [formError, setFormError] = useState('');
  const [creating, setCreating] = useState(false);
  const [formOpen, setFormOpen] = useState(false);

  function toggleScope(value, active) {
    setSelectedScopes(current => active ? [...current, value] : current.filter(item => item !== value));
  }

  async function create() {
    setFormError('');
    if (!name.trim()) {
      setFormError('Give the token a name.');
      return;
    }
    if (!selectedScopes.length) {
      setFormError('Choose at least one permission.');
      return;
    }
    setCreating(true);
    try {
      await onCreate?.({ name: name.trim(), expiresInDays, scopes: selectedScopes });
      setName('');
      setExpiresInDays('');
      setFormOpen(false);
    } catch (failure) {
      setFormError(failure?.message || 'Could not create the token.');
    } finally {
      setCreating(false);
    }
  }

  async function revoke() {
    setConfirmError('');
    try {
      await onRevoke?.(pending);
      setPending(null);
    } catch (failure) {
      setConfirmError(failure?.message || 'Could not revoke the token.');
    }
  }

  return <SettingsCard title={labels.appTokensTitle} icon={icon} palette={colors}>
    <Text style={[styles.copy, { color: colors.textMuted }, colors.pageCards && { fontSize: 14, lineHeight: 20 }]}>{labels.appTokensDescription}</Text>
    {model.oneTimeSecret ? <View style={[styles.oneTime, { backgroundColor: colors.surfaceStrong, borderColor: colors.accent }]}>
      <Text style={[styles.rowTitle, { color: colors.text }]}>{labels.appTokenCreated}: {model.oneTimeSecret.name}</Text>
      <Text style={[styles.copy, { color: colors.textMuted }]}>{labels.appTokenCopy}</Text>
      <View style={styles.secretRow}>
        {secretSlot || <Text style={[styles.secret, { color: colors.textSecondary }]}>{model.oneTimeSecret.preview || 'flp_new…'}</Text>}
        <Button label={labels.copySecret} tone="surface" onPress={onCopySecret} palette={buttons} />
      </View>
    </View> : null}
    <StatusLine busy={busy} error={error} success={success} palette={colors} />
    {tokens.length ? tokens.map(token => <View key={token.id} style={[styles.rowCard, { backgroundColor: colors.surfaceStrong, borderColor: colors.border }]}>
      <View style={styles.rowHeading}>
        <View style={styles.rowBody}>
          <View style={styles.chipRow}>
            <Text style={[styles.rowTitle, { color: colors.text }]}>{token.name}</Text>
            {token.expired ? <Chip label={labels.expired} palette={{ ...colors, badgeBorder: colors.warning, badgeBackground: 'rgba(245, 158, 11, 0.15)', badgeText: '#fde68a' }} /> : null}
          </View>
          <Text style={[styles.prefix, { color: colors.textMuted }]}>{token.prefix}…</Text>
          <TokenMeta createdAt={token.createdAt} lastUsedAt={token.lastUsedAt} expiresAt={token.expiresAt}
            expired={false} palette={colors} labels={labels} />
          <ScopeChips scopes={token.scopes} palette={colors} />
        </View>
        <Button label={labels.revoke} tone="ghost-danger" disabled={Boolean(busy)}
          onPress={() => { setConfirmError(''); setPending(token); }} palette={buttons} />
      </View>
    </View>) : <View style={[styles.empty, { borderColor: colors.border }, colors.pageCards && { borderWidth: 0, padding: 0, alignItems: 'flex-start' }]}>
      <Text style={[styles.copy, { color: colors.textMuted }, colors.pageCards && { fontSize: 14, lineHeight: 20 }]}>{labels.noAppTokens}</Text>
    </View>}
    {model.sessionRequired ? <Text style={[styles.copy, { color: colors.textMuted }]}>Sign in with your username and password to manage this.</Text> :
    <View style={[styles.form, { backgroundColor: colors.surfaceDim || colors.surfaceStrong, borderColor: colors.border }, colors.pageCards && { borderWidth: 0, padding: 16 }]}>
      {model.collapsible ? <Pressable accessibilityRole="button" accessibilityLabel="Create an app token" aria-expanded={formOpen}
        onPress={() => setFormOpen(value => !value)} style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
        <View style={formOpen ? { transform: [{ rotate: '90deg' }] } : undefined}><Icon spec={actionIcons.chevronRight} color={colors.textMuted} size={12} /></View>
        <Text style={[styles.sectionTitle, { color: colors.text }]}>Create an app token</Text>
      </Pressable> : <Text style={[styles.sectionTitle, { color: colors.text }]}>{labels.createToken}</Text>}
      {!model.collapsible || formOpen ? <View style={{ gap: 10 }}>
      <TextField label={labels.name} name="name" value={name} placeholder={labels.namePlaceholder}
        maxLength={255} palette={colors} onChangeText={setName} />
      <SelectField label={labels.expires} name="expires_in_days" value={expiresInDays}
        iconChevron={Boolean(colors.pageCards)}
        options={expiry} palette={colors} onChange={event => setExpiresInDays(event.target.value)} />
      <Text style={[styles.sectionTitle, { color: colors.text }]}>{labels.permissions}</Text>
      <Text style={[styles.copy, { color: colors.textMuted }]}>{labels.presetHint}</Text>
      <View style={styles.toggleList}>{scopes.map(scope => <View key={scope.value} style={styles.scopeRow}>
        <ToggleChip label={scope.value} help={scope.description} value={selectedScopes.includes(scope.value)}
          checkbox={Boolean(colors.pageCards)} offLabel="Off" onLabel="On" palette={{ ...colors, fontFamily: colors.pageCards ? 'monospace' : colors.fontFamily }}
          onChange={active => toggleScope(scope.value, active)} />
      </View>)}</View>
      {formError ? <Text accessibilityRole="alert" style={[styles.error, { color: colors.danger }]}>{formError}</Text> : null}
      <Button label={creating ? labels.creatingToken : labels.createToken} busy={creating}
        disabled={creating || Boolean(busy)} onPress={create} palette={buttons} />
      </View> : null}
    </View>}
    <ConfirmDialog visible={Boolean(pending)} title={labels.revokeTitle} message={labels.revokeCopy}
      warning={pending ? `${pending.name} stops working immediately.` : undefined}
      confirmLabel={labels.revoke} busy={Boolean(busy)} error={confirmError}
      palette={colors} buttonPalette={buttons}
      onCancel={() => setPending(null)} onConfirm={revoke} />
  </SettingsCard>;
}

export function CatalogGrantsCard({
  sessionRequired = false,
  oneTimeSecret,
  secretSlot,
  onCopySecret,
  grants = [],
  busy = false,
  error,
  success,
  palette = {},
  buttonPalette = {},
  onCreate,
  onRevoke,
}) {
  const colors = { ...defaultPalette, ...palette };
  const buttons = { ...defaultButtonPalette, ...buttonPalette };
  const labels = defaultLabels;
  const [name, setName] = useState('');
  const [allowPlaybackStart, setAllowPlaybackStart] = useState(true);
  const [pending, setPending] = useState(null);
  const [confirmError, setConfirmError] = useState('');
  const [formError, setFormError] = useState('');
  const [creating, setCreating] = useState(false);

  async function create() {
    setFormError('');
    if (!name.trim()) {
      setFormError('Give the install a name.');
      return;
    }
    setCreating(true);
    try {
      await onCreate?.({ name: name.trim(), allowPlaybackStart });
      setName('');
      setAllowPlaybackStart(true);
    } catch (failure) {
      setFormError(failure?.message || 'Could not create the install credential.');
    } finally {
      setCreating(false);
    }
  }

  async function revoke() {
    setConfirmError('');
    try {
      await onRevoke?.(pending);
      setPending(null);
    } catch (failure) {
      setConfirmError(failure?.message || 'Could not revoke the install credential.');
    }
  }

  return <SettingsCard title={labels.catalogTitle} palette={colors}>
    <Text style={[styles.copy, { color: colors.textMuted }]}>{labels.catalogDescription}</Text>
    {oneTimeSecret ? <View style={[styles.oneTime, { backgroundColor: colors.surfaceDim || colors.surfaceStrong, borderColor: colors.accent }]}>
      <Text style={[styles.rowTitle, { color: colors.text }]}>Install credential created: {oneTimeSecret.name}</Text>
      <Text style={[styles.copy, { color: colors.textMuted }]}>Copy this credential before leaving this page.</Text>
      <View style={styles.secretRow}>
        {secretSlot}
        <Button label={labels.copySecret} tone="surface" onPress={onCopySecret} palette={buttons} />
      </View>
    </View> : null}
    <StatusLine busy={busy} error={error} success={success} palette={colors} />
    {grants.length ? grants.map(grant => <View key={grant.id} style={[styles.rowCard, { backgroundColor: colors.surfaceStrong, borderColor: colors.border }]}>
      <View style={styles.rowHeading}>
        <View style={styles.rowBody}>
          <Text style={[styles.rowTitle, { color: colors.text }]}>{grant.name}</Text>
          <Text style={[styles.meta, { color: colors.textMuted }]}>{labels.created} {grant.createdAt} · {grant.lastUsedAt ? `${labels.lastUsed} ${grant.lastUsedAt}` : labels.neverUsed} · {grant.allowPlaybackStart ? 'Playback allowed' : labels.catalogsOnly}</Text>
        </View>
        <Button label={labels.revoke} tone="ghost-danger" disabled={busy}
          onPress={() => { setConfirmError(''); setPending(grant); }} palette={buttons} />
      </View>
    </View>) : <View style={[styles.empty, { borderColor: colors.border }]}>
      <Text style={[styles.copy, { color: colors.textMuted }]}>{labels.noGrants}</Text>
    </View>}
    {sessionRequired ? <Text style={[styles.copy, { color: colors.textMuted }]}>Sign in with your username and password to manage this.</Text> :
    <View style={[styles.form, { backgroundColor: colors.surfaceStrong, borderColor: colors.border }]}>
      <TextField label={labels.installName} name="grant_name" value={name} placeholder={labels.installPlaceholder}
        maxLength={255} palette={colors} onChangeText={setName} />
      <ToggleChip label={labels.allowPlayback} value={allowPlaybackStart} offLabel="Catalogs only"
        onLabel="Playback allowed" palette={colors} onChange={setAllowPlaybackStart} />
      {formError ? <Text accessibilityRole="alert" style={[styles.error, { color: colors.danger }]}>{formError}</Text> : null}
      <Button label={creating ? labels.creatingInstall : labels.createInstall} busy={creating}
        disabled={creating || Boolean(busy)} onPress={create} palette={buttons} />
    </View>}
    <ConfirmDialog visible={Boolean(pending)} title={labels.revokeTitle} message={labels.revokeCopy}
      warning={pending ? `${pending.name} stops working immediately.` : undefined}
      confirmLabel={labels.revoke} busy={Boolean(busy)} error={confirmError}
      palette={colors} buttonPalette={buttons}
      onCancel={() => setPending(null)} onConfirm={revoke} />
  </SettingsCard>;
}

export function AuthorizedApplicationsCard({
  separateHeader = false,
  labels: suppliedLabels,
  applications = [],
  busy = false,
  error,
  success,
  palette = {},
  buttonPalette = {},
  onRevoke,
}) {
  const colors = { ...defaultPalette, ...palette };
  const buttons = { ...defaultButtonPalette, ...buttonPalette };
  const labels = { ...defaultLabels, ...suppliedLabels };
  const [pending, setPending] = useState(null);
  const [confirmError, setConfirmError] = useState('');

  async function revoke() {
    setConfirmError('');
    try {
      await onRevoke?.(pending);
      setPending(null);
    } catch (failure) {
      setConfirmError(failure?.message || 'Could not revoke access.');
    }
  }

  const content = <>
    <StatusLine busy={busy} error={error} success={success} palette={colors} />
    {applications.length ? applications.map(application => <View key={application.id}
      style={[styles.rowCard, { backgroundColor: separateHeader ? colors.surface : colors.surfaceStrong, borderColor: colors.border }, separateHeader && { borderWidth: 0, padding: 24 }]}>
      <View style={styles.rowHeading}>
        <View style={styles.rowBody}>
          <View style={styles.chipRow}>
            <Text style={[styles.rowTitle, { color: colors.text }]}>{application.name}</Text>
            {!application.active ? <Chip label={labels.clientRevoked} palette={colors} /> : null}
          </View>
          <Text style={[styles.prefix, { color: colors.textMuted }]}>{application.clientId}</Text>
          <Text style={[styles.meta, { color: colors.textMuted }]}>
            {application.connectedAt ? `${labels.connected} ${application.connectedAt}` : ''}
            {application.lastUsedAt ? ` · ${labels.lastUsed} ${application.lastUsedAt}` : ''}
          </Text>
          <View style={styles.chipRow}>{(application.scopes || []).map(scope => <Chip key={scope.label}
            label={scope.label} accessibilityLabel={`${scope.label}: ${scope.description || ''}`} palette={colors} />)}</View>
        </View>
        <Button label={labels.oauthRevoke} tone="ghost-danger" disabled={busy}
          onPress={() => { setConfirmError(''); setPending(application); }} palette={buttons} />
      </View>
    </View>) : <View style={[styles.empty, { borderColor: colors.border }, separateHeader && { borderWidth: 0, padding: 24, alignItems: 'flex-start', backgroundColor: colors.surface }]}>
      <Text style={[styles.copy, { color: colors.textMuted }, separateHeader && { fontSize: 14, lineHeight: 20 }]}>{labels.noApplications}</Text>
    </View>}
    <ConfirmDialog visible={Boolean(pending)} title={labels.oauthRevokeTitle} message={labels.oauthRevokeCopy}
      warning={pending ? `${pending.name} loses access immediately.` : undefined}
      confirmLabel={labels.oauthRevoke} busy={busy} error={confirmError}
      palette={colors} buttonPalette={buttons}
      onCancel={() => setPending(null)} onConfirm={revoke} />
  </>;
  return <View style={separateHeader ? { gap: 24 } : undefined}>
    <SettingsCard title={labels.oauthTitle} contentGap={separateHeader ? 8 : undefined} palette={colors}>
      <Text style={[styles.copy, { color: colors.textMuted }, separateHeader && { fontSize: 14, lineHeight: 20 }]}>{labels.oauthDescription}</Text>
      {!separateHeader ? content : null}
    </SettingsCard>
    {separateHeader ? content : null}
  </View>;
}

const styles = StyleSheet.create({
  copy: { fontSize: 12, lineHeight: 18 },
  warning: { fontSize: 12, lineHeight: 18, fontWeight: '600' },
  status: { fontSize: 12, lineHeight: 18 },
  error: { fontSize: 12, lineHeight: 18 },
  secretRow: { borderWidth: 1, borderRadius: 8, padding: 10, gap: 8, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap' },
  secret: { fontSize: 12, letterSpacing: 1, flexShrink: 1, flexGrow: 1, minWidth: 160 },
  rowCard: { borderWidth: 1, borderRadius: 8, padding: 12, gap: 8 },
  rowHeading: { flexDirection: 'row', alignItems: 'flex-start', justifyContent: 'space-between', gap: 10, flexWrap: 'wrap' },
  rowBody: { gap: 4, flexShrink: 1, flexGrow: 1, minWidth: 0 },
  rowTitle: { fontSize: 13, fontWeight: '600' },
  prefix: { fontSize: 12 },
  meta: { fontSize: 12, lineHeight: 17 },
  chipRow: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', gap: 6 },
  empty: { borderWidth: 1, borderStyle: 'dashed', borderRadius: 8, padding: 14, alignItems: 'center' },
  oneTime: { borderWidth: 1, borderRadius: 8, padding: 12, gap: 8 },
  form: { borderWidth: 1, borderRadius: 8, padding: 12, gap: 10 },
  sectionTitle: { fontSize: 14, fontWeight: '600' },
  toggleList: { gap: 8 },
  scopeRow: { gap: 2 },
});
