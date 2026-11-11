import React, { useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { SettingsCard } from '../settings/SettingsCard';
import { Button } from '../ui/Button';
import { ConfirmDialog } from '../settings/ConfirmDialog';
import { TextField } from '../ui/TextField';
import { ToggleChip } from '../ui/ToggleChip';

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
  overlay: 'rgba(0, 0, 0, 0.65)',
  radius: 6,
  focusStyle: {},
};

const defaultButtonPalette = {
  primary: { background: '#4f46e5', pressed: '#4338ca', hovered: '#4338ca', text: '#ffffff', border: 'transparent' },
  surface: { background: '#3f3f46', pressed: '#52525b', hovered: '#52525b', text: '#fafafa', border: '#3f3f46' },
  'danger-solid': { background: '#dc2626', pressed: '#b91c1c', hovered: '#b91c1c', text: '#ffffff', border: 'transparent' },
  'danger-deep': { background: '#b91c1c', pressed: '#991b1b', hovered: '#991b1b', text: '#ffffff', border: 'transparent' },
  radius: 6,
  focusStyle: {},
};

const defaultLabels = {
  profileTitle: 'Profile Information',
  username: 'Username',
  saveChanges: 'Save Changes',
  saving: 'Saving…',
  accountTypeTitle: 'Account Type',
  superuserCopy: 'You are a Superuser. You have full administrative access to this Floppy instance.',
  regularCopy: 'You are a regular user. Superuser access grants full administrative control over this Floppy instance.',
  promoteTitle: 'Upgrading to Superuser',
  promoteCopy: 'Floppy never grants superuser access automatically. If you have access to the host or container running this instance, promote this account from a terminal:',
  promoteHelp: 'This must be run from a terminal with access to the Floppy container. It cannot be done from this UI.',
  passwordTitle: 'Change Password',
  currentPassword: 'Current Password',
  newPassword: 'New Password',
  confirmNewPassword: 'Confirm New Password',
  updatePassword: 'Update Password',
  authenticatorTitle: 'Account Recovery & Authenticator',
  authenticatorIntro: 'Floppy cannot send password reset emails or text messages. Authenticator codes, recovery codes, or an admin password reset in the container terminal are the only recovery options.',
  authenticatorEnabled: 'Authenticator app is enabled.',
  authenticatorEnabledCopy: 'Add a new authenticator app to replace the active one, or deactivate authenticator access for this account.',
  scanQr: 'Scan this QR code with your authenticator app. If scanning is unavailable, enter the secret manually.',
  manualSecret: 'Manual entry secret',
  verifyIntro: 'Verify with a 6-digit code to activate authenticator login recovery.',
  authenticatorCode: 'Authenticator Code',
  verifyAuthenticator: 'Verify Authenticator',
  addAuthenticator: 'Add New Authenticator App',
  deactivateAuthenticator: 'Deactivate Authenticator',
  recoveryTitle: 'Recovery Codes',
  unusedCodes: 'Unused recovery codes:',
  freshCodesWarning: 'Save these recovery codes now. They are shown only once.',
  regenerate: 'Regenerate Recovery Codes',
  connectionsTitle: 'Third-Party Connections',
  connectionsCopy: 'Manage your connected third-party accounts for easier sign-in.',
  manageConnections: 'Manage Account Connections',
  approveDevice: 'Approve a Device Sign-in',
  deleteTitle: 'Delete Account',
  deleteCopy: 'This permanently removes your account, tracking history, lists, tags, integrations, API tokens and scheduled syncs. It cannot be undone. Other users are not affected.',
  deletePassword: 'Current Password',
  deleteUsername: 'Type your username to confirm',
  deleteConfirm: 'I understand this cannot be undone',
  deleteButton: 'Delete My Account',
  lastSuperuser: 'You are the only superuser. Promote another account before deleting this one.',
  demoViewOnly: 'This section is view-only for demo accounts.',
  dialogTitle: 'Delete account permanently?',
  dialogMessage: 'Your account and all of its data will be removed. This cannot be undone.',
  dialogConfirm: 'Delete My Account',
  cancel: 'Cancel',
  codeHint: 'Recovery codes are shown once after they are generated. Store them somewhere safe.',
  sessionRequired: 'Sign in with your username and password to manage this.',
};

function StateMessage({ tone = 'error', palette, children }) {
  const color = tone === 'success' ? palette.success : tone === 'warning' ? palette.warning : palette.danger;
  return <Text accessibilityLiveRegion="polite" style={[styles.state, { color }]}>{children}</Text>;
}

export function ProfileCard({
  username = '',
  error,
  success,
  busy = false,
  disabled = false,
  palette = {},
  buttonPalette = {},
  labels = {},
  onChangeUsername,
  onSave,
}) {
  const colors = { ...defaultPalette, ...palette };
  const buttons = { ...defaultButtonPalette, ...buttonPalette };
  const copy = { ...defaultLabels, ...labels };
  return <SettingsCard title={copy.profileTitle} palette={colors}>
    <TextField id="account-username" name="username" label={copy.username} value={username}
      autoComplete="username" disabled={disabled || busy} error={error}
      palette={colors} onChangeText={onChangeUsername} />
    {success ? <StateMessage tone="success" palette={colors}>{success}</StateMessage> : null}
    <Button label={busy ? copy.saving : copy.saveChanges} tone="primary" busy={busy}
      disabled={disabled || busy} onPress={onSave} palette={buttons} />
  </SettingsCard>;
}

export function AccountTypeCard({ isSuperuser = false, username = '', palette = {}, labels = {} }) {
  const colors = { ...defaultPalette, ...palette };
  const copy = { ...defaultLabels, ...labels };
  return <SettingsCard title={copy.accountTypeTitle} palette={colors}>
    <Text style={[styles.copy, { color: colors.textMuted }]}>
      {isSuperuser ? copy.superuserCopy : copy.regularCopy}
    </Text>
    {isSuperuser ? null : <View style={[styles.panel, { borderColor: colors.border, backgroundColor: colors.surfaceStrong }]}>
      <Text style={[styles.panelTitle, { color: colors.warning }]}>{copy.promoteTitle}</Text>
      <Text style={[styles.copy, { color: colors.textSecondary }]}>{copy.promoteCopy}</Text>
      <Text style={[styles.code, { color: colors.textSecondary, backgroundColor: colors.surface }]}>
        {`docker exec floppy python manage.py promote_superuser ${username}`}
      </Text>
      <Text style={[styles.copy, { color: colors.textSecondary }]}>{copy.promoteHelp}</Text>
    </View>}
  </SettingsCard>;
}

export function PasswordCard({
  values = {},
  errors = {},
  error,
  success,
  busy = false,
  disabled = false,
  sessionRequired = false,
  palette = {},
  buttonPalette = {},
  labels = {},
  onChange,
  onSubmit,
}) {
  const colors = { ...defaultPalette, ...palette };
  const buttons = { ...defaultButtonPalette, ...buttonPalette };
  const copy = { ...defaultLabels, ...labels };
  const update = (name, value) => onChange?.(name, value);
  if (sessionRequired) return <SettingsCard title={copy.passwordTitle} palette={colors}>
    <Text style={[styles.copy, { color: colors.textMuted }]}>{copy.sessionRequired}</Text>
  </SettingsCard>;
  return <SettingsCard title={copy.passwordTitle} palette={colors}>
    <TextField id="account-current-password" name="oldPassword" label={copy.currentPassword}
      type="password" value={values.oldPassword} autoComplete="current-password"
      disabled={disabled || busy} error={errors.oldPassword} palette={colors}
      onChangeText={value => update('oldPassword', value)} />
    <TextField id="account-new-password" name="newPassword1" label={copy.newPassword}
      type="password" value={values.newPassword1} autoComplete="new-password"
      disabled={disabled || busy} error={errors.newPassword1} palette={colors}
      onChangeText={value => update('newPassword1', value)} />
    <TextField id="account-confirm-password" name="newPassword2" label={copy.confirmNewPassword}
      type="password" value={values.newPassword2} autoComplete="new-password"
      disabled={disabled || busy} error={errors.newPassword2} palette={colors}
      onChangeText={value => update('newPassword2', value)} />
    {error ? <StateMessage palette={colors}>{error}</StateMessage> : null}
    {success ? <StateMessage tone="success" palette={colors}>{success}</StateMessage> : null}
    <Button label={busy ? copy.saving : copy.updatePassword} tone="primary" busy={busy}
      disabled={disabled || busy} onPress={onSubmit} palette={buttons} />
  </SettingsCard>;
}

export function AuthenticatorCard({
  children,
  configured = false,
  setup = false,
  values = {},
  errors = {},
  error,
  success,
  busy = false,
  disabled = false,
  sessionRequired = false,
  demo = false,
  qrSlot,
  secretSlot,
  palette = {},
  buttonPalette = {},
  labels = {},
  onChange,
  onStartSetup,
  onEnable,
  onDisable,
}) {
  const colors = { ...defaultPalette, ...palette };
  const buttons = { ...defaultButtonPalette, ...buttonPalette };
  const copy = { ...defaultLabels, ...labels };
  const update = (name, value) => onChange?.(name, value);
  if (sessionRequired) return <SettingsCard title={copy.authenticatorTitle} palette={colors}>
    <Text style={[styles.copy, { color: colors.textMuted }]}>{copy.sessionRequired}</Text>
    {children}
  </SettingsCard>;
  return <SettingsCard title={copy.authenticatorTitle} palette={colors}>
    <Text style={[styles.copy, { color: colors.textMuted }]}>{copy.authenticatorIntro}</Text>
    {demo ? <View style={[styles.panel, { borderColor: colors.border, backgroundColor: colors.surfaceStrong }]}>
      <Text style={[styles.copy, { color: colors.textSecondary }]}>{copy.demoViewOnly}</Text>
    </View> : null}

    {!demo && setup ? <View style={styles.setup}>
      <View style={styles.qrRow}>
        {qrSlot ? <View style={[styles.qrFrame, { backgroundColor: '#ffffff' }]}>{qrSlot}</View> : null}
        <View style={styles.setupCopy}>
          <Text style={[styles.copy, { color: colors.textSecondary }]}>{copy.scanQr}</Text>
          <Text style={[styles.help, { color: colors.textMuted }]}>{copy.manualSecret}</Text>
          {secretSlot || <Text style={[styles.code, { color: colors.textSecondary, backgroundColor: colors.surfaceStrong }]}>Shown only in the secure setup adapter</Text>}
        </View>
      </View>
      <Text style={[styles.copy, { color: colors.textSecondary }]}>{copy.verifyIntro}</Text>
      <TextField id="authenticator-password" name="currentPassword" label={copy.currentPassword}
        type="password" value={values.currentPassword} autoComplete="current-password"
        disabled={disabled || busy} error={errors.currentPassword} palette={colors}
        onChangeText={value => update('currentPassword', value)} />
      <TextField id="authenticator-code" name="code" label={copy.authenticatorCode}
        value={values.code} placeholder="123456" maxLength={6} disabled={disabled || busy}
        error={errors.code} palette={colors} onChangeText={value => update('code', value)} />
      <Button label={copy.verifyAuthenticator} tone="primary" busy={busy}
        disabled={disabled || busy} onPress={onEnable} palette={buttons} />
    </View> : null}

    {!demo && !setup ? <View style={styles.setup}>
      <Text style={[styles.copy, { color: colors.success }]}>{copy.authenticatorEnabled}</Text>
      <Text style={[styles.copy, { color: colors.textMuted }]}>{copy.authenticatorEnabledCopy}</Text>
      <TextField id="authenticator-manage-password" name="currentPassword" label={copy.currentPassword}
        type="password" value={values.currentPassword} autoComplete="current-password"
        disabled={disabled || busy} error={errors.currentPassword} palette={colors}
        onChangeText={value => update('currentPassword', value)} />
      <View style={styles.actionRow}>
        <Button label={copy.addAuthenticator} tone="surface" disabled={disabled || busy}
          onPress={onStartSetup} palette={buttons} />
        <Button label={copy.deactivateAuthenticator} tone="danger-deep" disabled={disabled || busy}
          onPress={onDisable} palette={buttons} />
      </View>
    </View> : null}

    {error ? <StateMessage palette={colors}>{error}</StateMessage> : null}
    {success ? <StateMessage tone="success" palette={colors}>{success}</StateMessage> : null}
    {children}
  </SettingsCard>;
}

export function RecoveryCodesCard({
  embedded = false,
  unusedCount = 0,
  freshCodes = [],
  values = {},
  errors = {},
  error,
  success,
  busy = false,
  disabled = false,
  sessionRequired = false,
  demo = false,
  palette = {},
  buttonPalette = {},
  labels = {},
  onChange,
  onRegenerate,
}) {
  const colors = { ...defaultPalette, ...palette };
  const buttons = { ...defaultButtonPalette, ...buttonPalette };
  const copy = { ...defaultLabels, ...labels };
  if (sessionRequired) return <SettingsCard title={embedded ? undefined : copy.recoveryTitle} framed={!embedded} palette={colors}>
    <Text style={[styles.copy, { color: colors.textMuted }]}>{copy.sessionRequired}</Text>
  </SettingsCard>;
  return <SettingsCard title={embedded ? undefined : copy.recoveryTitle} framed={!embedded} palette={colors}>
    <Text style={[styles.copy, { color: colors.textSecondary }]}>
      {`${copy.unusedCodes} ${unusedCount}`}
    </Text>
    {freshCodes.length ? <View style={[styles.panel, { borderColor: colors.warning, backgroundColor: colors.surfaceStrong }]}>
      <Text style={[styles.copy, { color: colors.warning }]}>{copy.freshCodesWarning}</Text>
      <View style={styles.codes}>
        {freshCodes.map(code => <Text key={code} style={[styles.code, { color: colors.textSecondary, backgroundColor: colors.surface }]}>{code}</Text>)}
      </View>
    </View> : null}
    {!embedded ? <Text style={[styles.help, { color: colors.textMuted }]}>{copy.codeHint}</Text> : null}
    {demo ? <View style={[styles.panel, { borderColor: colors.border, backgroundColor: colors.surfaceStrong }]}>
      <Text style={[styles.copy, { color: colors.textSecondary }]}>{copy.demoViewOnly}</Text>
    </View> : <View style={styles.setup}>
      <TextField id="recovery-current-password" name="currentPassword" label={copy.currentPassword}
        type="password" value={values.currentPassword} autoComplete="current-password"
        disabled={disabled || busy} error={errors.currentPassword} palette={colors}
        onChangeText={value => onChange?.('currentPassword', value)} />
      {error ? <StateMessage palette={colors}>{error}</StateMessage> : null}
      {success ? <StateMessage tone="success" palette={colors}>{success}</StateMessage> : null}
      <Button label={copy.regenerate} tone="primary" busy={busy} disabled={disabled || busy}
        onPress={onRegenerate} palette={buttons} />
    </View>}
  </SettingsCard>;
}

export function ConnectionsCard({
  providerCount = 0,
  disabled = false,
  palette = {},
  buttonPalette = {},
  labels = {},
  onManageConnections,
  onApproveDevice,
}) {
  const colors = { ...defaultPalette, ...palette };
  const buttons = { ...defaultButtonPalette, ...buttonPalette };
  const copy = { ...defaultLabels, ...labels };
  return <SettingsCard title={copy.connectionsTitle} palette={colors}>
    <Text style={[styles.copy, { color: colors.textMuted }]}>{copy.connectionsCopy}</Text>
    <View style={styles.actionRow}>
      <Button label={copy.manageConnections} tone="primary" disabled={disabled}
        onPress={onManageConnections} palette={buttons} />
      <Button label={copy.approveDevice} tone="surface" disabled={disabled}
        onPress={onApproveDevice} palette={buttons} />
    </View>
    <Text style={[styles.help, { color: colors.textMuted }]}>
      {`${providerCount} connected provider${providerCount === 1 ? '' : 's'} available.`}
    </Text>
  </SettingsCard>;
}

export function DeleteAccountCard({
  account = {},
  error,
  busy = false,
  palette = {},
  buttonPalette = {},
  labels = {},
  onDelete,
}) {
  const colors = { ...defaultPalette, ...palette };
  const buttons = { ...defaultButtonPalette, ...buttonPalette };
  const copy = { ...defaultLabels, ...labels };
  const [currentPassword, setCurrentPassword] = useState('');
  const [confirmUsername, setConfirmUsername] = useState('');
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [dialogOpen, setDialogOpen] = useState(false);
  const demo = Boolean(account.isDemo);
  const lastSuperuser = Boolean(account.isLastSuperuser);
  const usablePassword = account.hasUsablePassword !== false;
  const identityReady = usablePassword ? currentPassword.length > 0 : confirmUsername === account.username;
  const ready = !demo && !lastSuperuser && identityReady && confirmDelete;
  const submit = () => {
    setDialogOpen(false);
    onDelete?.({
      currentPassword: usablePassword ? currentPassword : undefined,
      confirmUsername: usablePassword ? undefined : confirmUsername,
      confirmDelete,
    });
  };
  return <SettingsCard title={copy.deleteTitle} palette={colors}>
    <Text style={[styles.copy, { color: colors.textMuted }]}>{copy.deleteCopy}</Text>
    {demo ? <View style={[styles.panel, { borderColor: colors.border, backgroundColor: colors.surfaceStrong }]}>
      <Text style={[styles.copy, { color: colors.textSecondary }]}>{copy.demoViewOnly}</Text>
    </View> : lastSuperuser ? <View style={[styles.panel, { borderColor: colors.warning, backgroundColor: colors.surfaceStrong }]}>
      <Text style={[styles.copy, { color: colors.warning }]}>{copy.lastSuperuser}</Text>
    </View> : <View style={styles.setup}>
      {usablePassword
        ? <TextField id="delete-account-password" name="currentPassword" label={copy.deletePassword}
          type="password" value={currentPassword} autoComplete="current-password"
          disabled={busy} palette={colors} onChangeText={setCurrentPassword} />
        : <TextField id="delete-account-username" name="confirmUsername"
          label={`${copy.deleteUsername} (${account.username})`} value={confirmUsername}
          autoComplete="off" disabled={busy} palette={colors} onChangeText={setConfirmUsername} />}
      <ToggleChip label={copy.deleteConfirm} value={confirmDelete} offLabel="Not confirmed"
        onLabel={copy.deleteConfirm} palette={colors} disabled={busy}
        onChange={setConfirmDelete} />
      {error ? <StateMessage palette={colors}>{error}</StateMessage> : null}
      <Button label={copy.deleteButton} tone="danger-solid" busy={busy}
        disabled={busy || !ready} onPress={() => setDialogOpen(true)} palette={buttons} />
    </View>}
    <ConfirmDialog visible={dialogOpen} title={copy.dialogTitle} message={copy.dialogMessage}
      warning={account.username ? `Deleting ${account.username}` : undefined}
      confirmLabel={copy.dialogConfirm} cancelLabel={copy.cancel}
      busy={busy} palette={colors} buttonPalette={buttons}
      onCancel={() => setDialogOpen(false)} onConfirm={submit} />
  </SettingsCard>;
}

const styles = StyleSheet.create({
  copy: { fontSize: 13, lineHeight: 19 },
  help: { fontSize: 12, lineHeight: 17 },
  state: { fontSize: 12, lineHeight: 17 },
  panel: { borderWidth: 1, borderRadius: 8, padding: 12, gap: 6 },
  panelTitle: { fontSize: 13, fontWeight: '700' },
  code: { fontFamily: 'Courier', fontSize: 12, borderRadius: 6, paddingHorizontal: 8, paddingVertical: 6 },
  setup: { gap: 10 },
  setupCopy: { flexShrink: 1, gap: 6 },
  qrRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 12, alignItems: 'flex-start' },
  qrFrame: { padding: 6, borderRadius: 8 },
  actionRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  codes: { flexDirection: 'row', flexWrap: 'wrap', gap: 6 },
});
