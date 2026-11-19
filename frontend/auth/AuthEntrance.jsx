import React, { useState } from 'react';
import { ActivityIndicator, Pressable, StyleSheet, Text, View } from 'react-native';
import { Chip } from '../settings/Chip';
import { Button } from '../ui/Button';
import { TextField } from '../ui/TextField';
import { SearchIcon } from '../ui/Icon';

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
  radius: 6,
  focusStyle: {},
};

const defaultLabels = {
  loginTitle: 'Sign in to your account',
  firstRunLoginTitle: 'Welcome to Floppy: set up your account to get started',
  signupTitle: 'Create your account',
  firstRunSignupTitle: 'Welcome to Floppy: create your first account',
  recoveryTitle: 'Recover your password',
  username: 'Username',
  login: 'Username',
  password: 'Password',
  confirmPassword: 'Confirm Password',
  currentPassword: 'Current Password',
  authenticatorCode: 'Authenticator Code',
  recoveryCode: 'Recovery Code',
  newPassword: 'New Password',
  confirmNewPassword: 'Confirm New Password',
  signIn: 'Sign In',
  createAccount: 'Create Account',
  createAccountWithAuthenticator: 'Create Account + Set Up Authenticator',
  resetPassword: 'Reset Password',
  forgotPassword: 'Forgot Password',
  registerNow: 'Register now',
  createAccountLink: 'Create your account',
  signInLink: 'Sign in',
  noAccount: 'Need an account?',
  alreadyAccount: 'Already have an account?',
  signupsDisabled: 'Sign-ups are disabled.',
  hostYourOwn: 'Host your own',
  noAccountFirstRun: 'No account exists yet.',
  socialTitle: 'Or continue with a connected account',
  useRecoveryCode: 'I do not have an authenticator code',
  useAuthenticatorCode: 'Use authenticator code instead',
  recoveryHelp: 'No authenticator code and no recovery code? Ask an admin to run a password reset command in the container.',
  authenticatorWarning: 'Set up an authenticator app right after sign up. Without authenticator or recovery details, account recovery may be impossible.',
  recoveryNotice: 'Use your authenticator app code first for self-service recovery. If you do not have an authenticator code, use a recovery code instead.',
  errorsTitle: 'Check the details below',
  busySignIn: 'Signing in…',
  busySignUp: 'Creating account…',
  busyRecovery: 'Resetting password…',
  redirecting: 'Signed in. Continue to Floppy.',
  continue: 'Continue',
  serverAddress: 'Server address',
  serverStepTitle: 'Connect to your Floppy server',
  continueToSignIn: 'Continue',
  changeServer: 'Change',
  localServerPlaceholder: 'http://floppy.local:8000',
  serverPlaceholder: 'floppy.example.com',
  checkServer: 'Check server',
  checkingServer: 'Checking server…',
  serverReady: 'Server found. Choose a sign-in method below.',
  serverOk: 'Server reachable. Check again',
  local: 'Local',
  remote: 'Remote',
  localServerMode: 'Local server mode',
  remoteServerMode: 'Remote server mode',
  remoteServerInfo: 'To reach Floppy away from your home network, configure a secure externally reachable address with a Cloudflare Tunnel, VPN, or another method, then enter that address here.',
  discoverServers: 'Find Floppy servers on this network',
  discoveringServers: 'Searching for Floppy servers…',
  discoverySearching: 'Searching your local network for Floppy servers…',
  discoveryUnavailable: 'Server discovery is unavailable in Expo Go.',
  discoveryPermissionDenied: 'Allow local network access in your device settings to find Floppy servers.',
  discoveryEmpty: 'Couldn’t find an advertised Floppy server on this network. Enable the server’s discovery advertiser, or enter its address manually.',
  discoveredServers: 'Floppy servers found',
  clearServerAddress: 'Clear server address',
};

// The same mark the web login button renders (account/login.html).
const loginIcon = {
  viewBox: '0 0 24 24',
  root: { fill: 'none', stroke: 'currentColor', 'stroke-width': '2', 'stroke-linecap': 'round', 'stroke-linejoin': 'round' },
  children: [
    { tag: 'path', attrs: { d: 'M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4' }, children: [] },
    { tag: 'polyline', attrs: { points: '10 17 15 12 10 7' }, children: [] },
    { tag: 'line', attrs: { x1: '15', x2: '3', y1: '12', y2: '12' }, children: [] },
  ],
};

function Notice({ tone = 'info', title, children, palette }) {
  const toneColor = tone === 'error' ? palette.danger : tone === 'warning' ? palette.warning : tone === 'success' ? palette.success : palette.accent;
  return <View accessibilityLiveRegion="polite" style={[styles.notice, { borderColor: toneColor, backgroundColor: palette.surfaceStrong }]}>
    {title ? <Text style={[styles.noticeTitle, { color: toneColor }]}>{title}</Text> : null}
    {typeof children === 'string'
      ? <Text style={[styles.copy, { color: tone === 'warning' ? palette.warning : palette.textSecondary }]}>{children}</Text>
      : children}
  </View>;
}

export function AuthNotice({ tone = 'info', title, palette = {}, children }) {
  const colors = { ...defaultPalette, ...palette };
  return <Notice tone={tone} title={title} palette={colors}>{children}</Notice>;
}

export function SocialProviders({
  providers = [],
  busyProvider,
  palette = {},
  buttonPalette = {},
  labels = {},
  onProvider,
}) {
  const colors = { ...defaultPalette, ...palette };
  const buttons = { ...defaultButtonPalette, ...buttonPalette };
  const copy = { ...defaultLabels, ...labels };
  if (!providers.length) return null;
  return <View style={styles.section}>
    <View style={[styles.sectionRule, { borderColor: colors.border }]} />
    <Text style={[styles.sectionTitle, { color: colors.text }]}>{copy.socialTitle}</Text>
    <View style={styles.providerList}>
      {providers.map(provider => <Button
        key={provider.id}
        label={busyProvider === provider.id ? `Connecting to ${provider.label}…` : `Continue with ${provider.label}`}
        tone="surface"
        width="full"
        busy={busyProvider === provider.id}
        disabled={Boolean(busyProvider)}
        accessibilityLabel={provider.accessibilityLabel || `Continue with ${provider.label}`}
        onPress={() => onProvider?.(provider)}
        palette={buttons}
      />)}
    </View>
    <Text style={[styles.help, { color: colors.textMuted }]}>Provider sign-in opens the secure browser session. Floppy never receives the provider password.</Text>
  </View>;
}

// One inline control inside the server field: retry when idle, a spinner while
// checking, then a check or an x. It replaces the separate Check server button.
function ServerStatusButton({ state, busy, onPress, palette, labels }) {
  const color = state === 'ok' ? palette.success : state === 'error' ? palette.danger : palette.textMuted;
  const label = busy ? labels.checkingServer : state === 'error' ? labels.clearServerAddress
    : state === 'ok' ? labels.serverOk : labels.checkServer;
  return <Pressable accessibilityRole="button" accessibilityLabel={label}
    accessibilityState={{ busy, disabled: busy }} disabled={busy} onPress={onPress}
    style={({ pressed, focused }) => [styles.serverButton, pressed && { backgroundColor: palette.surfaceMuted },
      focused && palette.focusStyle]}>
    {busy ? <ActivityIndicator size="small" color={color} />
      : <Text aria-hidden style={[styles.serverGlyph, { color }]}>
        {state === 'ok' ? '✓' : state === 'error' ? '×' : '↻'}
      </Text>}
  </Pressable>;
}

function ServerDiscoveryButton({ busy, onPress, palette, labels }) {
  return <Pressable accessibilityRole="button" accessibilityLabel={busy ? labels.discoveringServers : labels.discoverServers}
    accessibilityState={{ busy }} disabled={busy} onPress={onPress}
    style={({ pressed, focused }) => [styles.serverButton, pressed && { backgroundColor: palette.surfaceMuted },
      focused && palette.focusStyle]}>
    {busy ? <ActivityIndicator size="small" color={palette.accent} />
      : <SearchIcon color={palette.textMuted} size={18} />}
  </Pressable>;
}

function LinkButton({ label, onPress, palette, accessibilityLabel }) {
  return <Pressable accessibilityRole="link" accessibilityLabel={accessibilityLabel || label} onPress={onPress}
    style={({ pressed, focused }) => [styles.link, pressed && styles.linkPressed, focused && palette.focusStyle]}>
    <Text style={[styles.linkText, { color: palette.link || palette.accent }]}>{label}</Text>
  </Pressable>;
}

export function AuthEntrance({
  mode = 'login',
  authStep = 'credentials',
  firstRun = false,
  registrationEnabled = true,
  socialOnly = false,
  providers = [],
  serverUrl = '',
  serverError,
  serverHelp,
  serverBusy = false,
  serverChecked = false,
  serverMode = 'local',
  serverHelpVisible = false,
  serverDiscoveryBusy = false,
  serverDiscoverySupported = true,
  serverDiscoveryPermissionDenied = false,
  serverDiscoveryMessage = '',
  discoveredServers = [],
  onServerChange,
  onContinueServer,
  onChangeServer,
  serverLocked = false,
  onClearServerAddress,
  onCheckServer,
  onServerModeChange,
  onToggleServerHelp,
  onDiscoverServers,
  onSelectDiscoveredServer,
  values = {},
  errors = {},
  error,
  success,
  redirectLabel,
  busy = false,
  busyProvider,
  palette = {},
  buttonPalette = {},
  labels = {},
  onChange,
  onSubmit,
  onSwitchMode,
  onForgotPassword,
  onProvider,
  onContinue,
  onHostOwn,
}) {
  const colors = { ...defaultPalette, ...palette };
  const buttons = { ...defaultButtonPalette, ...buttonPalette };
  const copy = { ...defaultLabels, ...labels };
  const [useRecoveryCode, setUseRecoveryCode] = useState(false);
  const update = (name, value) => onChange?.(name, value);
  const submit = options => onSubmit?.(options);

  const title = authStep === 'server' ? copy.serverStepTitle : mode === 'signup'
    ? (firstRun ? copy.firstRunSignupTitle : copy.signupTitle)
    : mode === 'recovery'
      ? copy.recoveryTitle
      : (firstRun ? copy.firstRunLoginTitle : copy.loginTitle);
  const busyLabel = mode === 'signup' ? copy.busySignUp : mode === 'recovery' ? copy.busyRecovery : copy.busySignIn;
  const discoveryAction = serverMode === 'local' && !serverUrl.trim();

  return <View style={styles.root}>
    <View style={styles.heading}>
    <Text role="heading" aria-level={2} style={[styles.title, { color: colors.textMuted }]}>{title}</Text>
    </View>
    <View style={[styles.card, { backgroundColor: colors.surface, borderRadius: colors.radius }]}>

    {authStep === 'server' ? <View style={styles.serverStep}>
    <View style={[styles.fields, styles.serverFields]}>
      <View style={styles.serverLabelRow}>
        <View style={styles.serverLabelGroup}>
          <Text style={[styles.serverLabel, { color: colors.textMuted }]}>{copy.serverAddress}</Text>
          {serverMode === 'remote' ? <Pressable accessibilityRole="button" accessibilityLabel="Remote server information"
            accessibilityState={{ expanded: serverHelpVisible }} onPress={onToggleServerHelp}
            style={({ pressed, focused }) => [styles.serverInfoButton, pressed && { backgroundColor: colors.surfaceMuted },
              focused && colors.focusStyle]}>
            <Text aria-hidden style={[styles.serverInfoGlyph, { color: colors.textSecondary, borderColor: colors.border }]}>i</Text>
          </Pressable> : null}
        </View>
        <View style={styles.serverModeRow}>
          <Chip label={serverMode === 'local' ? copy.local : copy.remote} palette={colors}
            accessibilityLabel={serverMode === 'local' ? copy.localServerMode : copy.remoteServerMode}
            accessibilityHint="Switch server address mode" pressed={serverMode === 'local'}
            onPress={() => onServerModeChange?.(serverMode === 'local' ? 'remote' : 'local')} />
        </View>
      </View>
      {serverMode === 'remote' && serverHelpVisible ? <Text style={[styles.serverMessage, { color: colors.textSecondary }]}>{copy.remoteServerInfo}</Text> : null}
      <TextField size="lg" id="auth-server" name="serverUrl" label={copy.serverAddress} labelHidden type="url"
        value={serverUrl} placeholder={serverMode === 'local' ? copy.localServerPlaceholder : copy.serverPlaceholder} autoComplete="url"
        accessibilityLabel={copy.serverAddress}
        disabled={busy || serverBusy} error={serverError} help={serverHelp}
        palette={colors} onChangeText={value => onServerChange?.(value)}
        trailingWidth={44}
        trailing={discoveryAction
          ? <ServerDiscoveryButton busy={serverDiscoveryBusy} onPress={onDiscoverServers} palette={colors} labels={copy} />
          : <ServerStatusButton
          state={serverBusy ? 'idle' : serverError ? 'error' : serverChecked ? 'ok' : 'idle'}
          busy={serverBusy} onPress={serverError ? onClearServerAddress : onCheckServer} palette={colors} labels={copy} />
        } />
      {serverMode === 'local' && serverDiscoveryMessage ? <Text accessibilityLiveRegion="polite"
        style={[styles.serverMessage, { color: serverDiscoveryPermissionDenied || ['empty', 'unavailable'].includes(serverDiscoveryMessage)
          ? colors.warning : colors.textMuted }]}>
        {serverDiscoveryMessage === 'searching' ? copy.discoverySearching
          : serverDiscoveryPermissionDenied ? copy.discoveryPermissionDenied
          : !serverDiscoverySupported ? copy.discoveryUnavailable
            : serverDiscoveryMessage === 'empty' ? copy.discoveryEmpty
              : serverDiscoveryMessage === 'permission' ? copy.discoveryPermissionDenied
                : serverDiscoveryMessage === 'unavailable' ? copy.discoveryUnavailable : serverDiscoveryMessage}
      </Text> : null}
      {serverMode === 'local' && discoveredServers.length ? <View style={styles.discoveredServers}>
        <Text style={[styles.serverListTitle, { color: colors.textMuted }]}>{copy.discoveredServers}</Text>
        {discoveredServers.map(server => <Pressable key={server.serverUrl} accessibilityRole="button"
          accessibilityLabel={`${server.name}, ${server.serverUrl}`} onPress={() => onSelectDiscoveredServer?.(server)}
          style={({ pressed, focused }) => [styles.discoveredServer, { borderColor: colors.border, backgroundColor: colors.surfaceStrong },
            pressed && { backgroundColor: colors.surfaceMuted }, focused && colors.focusStyle]}>
          <Text style={[styles.serverName, { color: colors.text }]}>{server.name}</Text>
          <Text style={[styles.serverAddress, { color: colors.textMuted }]}>{server.serverUrl}</Text>
        </Pressable>)}
      </View> : null}
    </View>
    {error ? <Notice tone="error" title={copy.errorsTitle} palette={colors}>{error}</Notice> : null}
    <Button label={copy.continueToSignIn} tone="primary" size="lg" width="full"
      busy={serverBusy} disabled={busy || serverBusy || !serverUrl.trim()} onPress={onContinueServer} palette={buttons} />
    </View> : <>
    {serverLocked ? null : <View style={styles.serverSummary}>
      <View style={styles.serverSummaryText}>
        <Text style={[styles.serverLabel, { color: colors.textMuted }]}>{copy.serverAddress}</Text>
        <Text numberOfLines={1} style={[styles.serverSummaryAddress, { color: colors.text }]}>{serverUrl}</Text>
      </View>
      <LinkButton label={copy.changeServer} onPress={onChangeServer} palette={colors} />
    </View>}
    {mode === 'recovery' ? <Text style={[styles.copy, { color: colors.textMuted }]}>{copy.recoveryNotice}</Text> : null}
    {mode === 'signup' ? <Text style={[styles.copy, { color: colors.textMuted }]}>{copy.authenticatorWarning}</Text> : null}

    {error ? <Notice tone="error" title={copy.errorsTitle} palette={colors}>{error}</Notice> : null}
    {success ? <Notice tone="success" palette={colors}>{success}</Notice> : null}
    {redirectLabel ? <Notice tone="success" palette={colors}>
      <Text style={[styles.copy, { color: colors.textSecondary }]}>{copy.redirecting}</Text>
      <View style={styles.inlineAction}>
        <Button label={redirectLabel || copy.continue} tone="primary" onPress={onContinue} palette={buttons} />
      </View>
    </Notice> : null}

    {!socialOnly && mode === 'login' ? <View style={styles.fields}>
      <TextField size="lg" id="auth-login" name="login" label={copy.login} value={values.login}
        placeholder="Enter your username" autoComplete="username" required disabled={busy}
        error={errors.login} palette={colors} onChangeText={value => update('login', value)} />
      <TextField size="lg" id="auth-password" name="password" label={copy.password} type="password"
        value={values.password} placeholder="Enter your password" autoComplete="current-password"
        required disabled={busy} error={errors.password} palette={colors}
        onChangeText={value => update('password', value)}
        onSubmitEditing={() => { if (!busy) submit(); }} />
      <Button label={busy ? busyLabel : copy.signIn} tone="primary" size="lg" width="full" icon={loginIcon}
        busy={busy} disabled={busy} onPress={() => submit()} palette={buttons} />
      {registrationEnabled
        ? <View style={styles.footerLink}>
          <Text style={[styles.copy, { color: colors.textMuted }]}>{firstRun ? copy.noAccountFirstRun : copy.noAccount}</Text>
          <LinkButton label={firstRun ? copy.createAccountLink : copy.registerNow} onPress={() => onSwitchMode?.('signup')} palette={colors} />
        </View>
        : <View style={styles.footerLink}>
          <Text style={[styles.copy, { color: colors.textMuted }]}>{copy.signupsDisabled}</Text>
          <LinkButton label={copy.hostYourOwn} onPress={onHostOwn || (() => onSwitchMode?.('login'))} palette={colors} />
        </View>}
    </View> : null}
    {!socialOnly && mode === 'login' && !firstRun ? <View style={styles.footerBlock}>
      <LinkButton label={copy.forgotPassword} onPress={onForgotPassword} palette={colors} />
    </View> : null}

    {!socialOnly && mode === 'signup' ? <View style={styles.fields}>
      <TextField size="lg" id="auth-username" name="username" label={copy.username} value={values.username}
        placeholder="Choose a username" autoComplete="username" required disabled={busy}
        error={errors.username} palette={colors} onChangeText={value => update('username', value)} />
      <TextField size="lg" id="auth-password1" name="password1" label={copy.password} type="password"
        value={values.password1} placeholder="Choose a password" autoComplete="new-password"
        required disabled={busy} error={errors.password1} palette={colors}
        onChangeText={value => update('password1', value)} />
      <TextField size="lg" id="auth-password2" name="password2" label={copy.confirmPassword} type="password"
        value={values.password2} placeholder="Confirm your password" autoComplete="new-password"
        required disabled={busy} error={errors.password2} palette={colors}
        onChangeText={value => update('password2', value)} />
      <View style={styles.actions}>
        <Button label={busy ? busyLabel : copy.createAccount} tone="primary" size="lg" width="full" busy={busy} disabled={busy}
          onPress={() => submit({ setupAuthenticator: false })} palette={buttons} />
        <Button label={copy.createAccountWithAuthenticator} tone="surface" size="lg" width="full" disabled={busy}
          onPress={() => submit({ setupAuthenticator: true })} palette={buttons} />
      </View>
      <View style={styles.footerLink}>
        <Text style={[styles.copy, { color: colors.textMuted }]}>{copy.alreadyAccount}</Text>
        <LinkButton label={copy.signInLink} onPress={() => onSwitchMode?.('login')} palette={colors} />
      </View>
    </View> : null}

    {!socialOnly && mode === 'recovery' ? <View style={styles.fields}>
      <TextField size="lg" id="recover-username" name="username" label={copy.username} value={values.username}
        placeholder="Your username" autoComplete="username" required disabled={busy}
        error={errors.username} palette={colors} onChangeText={value => update('username', value)} />
      {useRecoveryCode
        ? <TextField size="lg" id="recover-recovery-code" name="recoveryCode" label={copy.recoveryCode}
          value={values.recoveryCode} placeholder="Enter a recovery code" required disabled={busy}
          error={errors.recoveryCode} palette={colors} onChangeText={value => update('recoveryCode', value)} />
        : <TextField size="lg" id="recover-authenticator-code" name="authenticatorCode" label={copy.authenticatorCode}
          value={values.authenticatorCode} placeholder="6-digit code" maxLength={6}
          required disabled={busy} error={errors.authenticatorCode} palette={colors}
          onChangeText={value => update('authenticatorCode', value)} />}
      <View style={styles.methodRow}>
        <Chip label={useRecoveryCode ? copy.useAuthenticatorCode : copy.useRecoveryCode}
          palette={colors} onPress={() => setUseRecoveryCode(current => !current)} />
      </View>
      <TextField size="lg" id="recover-new-password1" name="newPassword1" label={copy.newPassword} type="password"
        value={values.newPassword1} placeholder="Choose a new password" autoComplete="new-password"
        required disabled={busy} error={errors.newPassword1} palette={colors}
        onChangeText={value => update('newPassword1', value)} />
      <TextField size="lg" id="recover-new-password2" name="newPassword2" label={copy.confirmNewPassword} type="password"
        value={values.newPassword2} placeholder="Confirm the new password" autoComplete="new-password"
        required disabled={busy} error={errors.newPassword2} palette={colors}
        onChangeText={value => update('newPassword2', value)} />
      {useRecoveryCode ? <Text style={[styles.help, { color: colors.textMuted }]}>{copy.recoveryHelp}</Text> : null}
      <View style={styles.actions}>
        <Button label={busy ? busyLabel : copy.resetPassword} tone="primary" size="lg" width="full" busy={busy} disabled={busy}
          onPress={() => submit({ useRecoveryCode })} palette={buttons} />
        <View style={styles.footerBlock}>
          <LinkButton label={copy.signInLink} onPress={() => onSwitchMode?.('login')} palette={colors} />
        </View>
      </View>
    </View> : null}

    {providers.length && (mode === 'login' || mode === 'signup') ? <SocialProviders
      providers={providers} busyProvider={busyProvider} palette={colors}
      buttonPalette={buttons} labels={copy} onProvider={onProvider} /> : null}
    </>}
    </View>
  </View>;
}

const styles = StyleSheet.create({
  root: { gap: 32 },
  card: { padding: 32, shadowColor: '#000', shadowOpacity: 0.1, shadowRadius: 15,
    shadowOffset: { width: 0, height: 10 }, elevation: 6 },
  heading: { alignItems: 'center' },
  title: { fontSize: 16, fontWeight: '400', lineHeight: 24, textAlign: 'center' },
  copy: { fontSize: 13, lineHeight: 19 },
  help: { fontSize: 12, lineHeight: 17 },
  fields: { gap: 24 },
  serverFields: { gap: 8 },
  serverStep: { gap: 16 },
  serverSummary: { minHeight: 44, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 12 },
  serverSummaryText: { flex: 1, minWidth: 0, gap: 2 },
  serverSummaryAddress: { fontSize: 13, lineHeight: 18 },
  section: { gap: 8, borderTopWidth: 1, paddingTop: 14 },
  sectionRule: { borderTopWidth: 1 },
  sectionTitle: { fontSize: 13, fontWeight: '600' },
  providerList: { gap: 8 },
  formActions: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', gap: 12 },
  serverButton: { width: 32, height: 32, alignItems: 'center', justifyContent: 'center', borderRadius: 6 },
  serverGlyph: { fontSize: 19, fontWeight: '700', lineHeight: 22 },
  serverLabelRow: { minHeight: 24, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 8 },
  serverLabelGroup: { flexDirection: 'row', alignItems: 'center', gap: 4 },
  serverLabel: { fontSize: 14, fontWeight: '500', lineHeight: 20 },
  serverModeRow: { flexDirection: 'row', alignItems: 'center', gap: 4 },
  serverInfoButton: { width: 24, height: 24, alignItems: 'center', justifyContent: 'center', borderRadius: 12 },
  serverInfoGlyph: { width: 16, height: 16, borderWidth: 1, borderRadius: 8,
    textAlign: 'center', fontSize: 11, fontWeight: '700', lineHeight: 14, overflow: 'hidden' },
  serverMessage: { fontSize: 12, lineHeight: 17 },
  discoveredServers: { gap: 6 },
  serverListTitle: { fontSize: 12, fontWeight: '600' },
  discoveredServer: { borderWidth: 1, borderRadius: 8, paddingHorizontal: 10, paddingVertical: 8, gap: 2 },
  serverName: { fontSize: 13, fontWeight: '600' },
  serverAddress: { fontSize: 12, lineHeight: 16 },
  actions: { gap: 12 },
  footerLink: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', justifyContent: 'center', gap: 6 },
  footerBlock: { alignItems: 'center', marginTop: 8 },
  methodRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  inlineAction: { marginTop: 8 },
  notice: { borderWidth: 1, borderRadius: 8, padding: 10, gap: 4 },
  noticeTitle: { fontSize: 12, fontWeight: '700' },
  link: { paddingVertical: 2 },
  linkPressed: { opacity: 0.7 },
  linkText: { fontSize: 13, fontWeight: '600' },
});
