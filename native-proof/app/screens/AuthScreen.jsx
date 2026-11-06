import React, { useEffect, useState } from 'react';
import { Image, Linking, StyleSheet, Text, View } from 'react-native';
import {
  accountTransport,
  AUTH_ERROR_CODES,
  buildDeviceVerificationUrl,
  buildProviderLoginUrl,
  fetchAuthConfig,
  getAuthState,
  recoverPassword,
  restoreAuthSession,
  signIn,
  signOut,
  signUp,
  testAuthConnection,
  verifyAuthSession,
} from '../data/authTransport';
import { subscribeAuthSession } from '../data/authSession';
import { AuthNotice } from '../../../frontend/auth/AuthEntrance';
import { AuthView } from '../../../frontend/pages/AuthView';
import { SettingsAccountView } from '../../../frontend/pages/SettingsAccountView';
import { Button } from '../../../frontend/ui/Button';
import { Chip } from '../../../frontend/settings/Chip';
import { Screen } from '../components/Screen';
import { palette, radius, spacing } from '../theme';

export const surface = {
  id: 'AUTH',
  status: 'ported',
  title: 'Account and authentication',
  where: 'Login, signup, social, password, TOTP, recovery, connections and deletion guards',
  note: 'Server URL and connection checks, session sign-in/signup/recovery, verified restore, expiry/revocation, sign-out, account profile/password/TOTP/recovery/delete actions and social/device browser intents use the shared React Native presentation and authenticated transport. Browser handoffs remain redirect intents; iOS and Android runtime remain unverified.',
};

const authPalette = {
  background: palette.background,
  surface: palette.surface,
  surfaceStrong: palette.surfaceStrong,
  surfaceMuted: palette.surfaceMuted,
  border: palette.border,
  text: palette.text,
  textSecondary: palette.textSecondary,
  textMuted: palette.textMuted,
  accent: palette.accent,
  accentStrong: palette.accentStrong,
  success: palette.success,
  warning: palette.warning,
  danger: palette.danger,
  badgeBorder: palette.surfaceMuted,
  badgeBackground: palette.surfaceStrong,
  badgeText: palette.textSecondary,
  badgeHover: palette.surfaceMuted,
  overlay: 'rgba(0, 0, 0, 0.65)',
  radius: radius.md,
  focusStyle: {},
};

const buttonPalette = {
  primary: { background: palette.accentStrong, pressed: '#4338ca', hovered: '#4338ca', text: '#ffffff', border: 'transparent' },
  surface: { background: palette.surfaceStrong, pressed: palette.surfaceMuted, hovered: palette.surfaceMuted, text: palette.text, border: palette.border },
  'danger-solid': { background: palette.danger, pressed: '#b91c1c', hovered: '#b91c1c', text: '#ffffff', border: 'transparent' },
  'danger-deep': { background: '#b91c1c', pressed: '#991b1b', hovered: '#991b1b', text: '#ffffff', border: 'transparent' },
  radius: radius.sm,
  focusStyle: {},
};

const views = [
  { key: 'login', label: 'Sign in' },
  { key: 'signup', label: 'Create account' },
  { key: 'recovery', label: 'Recover password' },
  { key: 'account', label: 'Account security' },
];

const emptyAuthValues = {
  login: '',
  password: '',
  username: '',
  password1: '',
  password2: '',
  authenticatorCode: '',
  recoveryCode: '',
  newPassword1: '',
  newPassword2: '',
};

const emptyConfig = {
  providers: [],
  registrationEnabled: true,
  socialOnly: false,
  firstRun: false,
  connectionsUrl: '',
  deviceUrl: '',
};

function errorMessage(error, fallback) {
  if (error && typeof error.message === 'string' && error.message.trim()) return error.message;
  return fallback;
}

function firstFieldError(error, names) {
  for (const name of names) {
    const value = error?.errors?.[name];
    if (Array.isArray(value) && value.length) return String(value[0]);
    if (typeof value === 'string' && value.trim()) return value;
  }
  return '';
}

function GuardChip({ label, active, onPress }) {
  return <Chip label={label} palette={authPalette} pressed={active} onPress={onPress} />;
}

export default function AuthScreen({ onBack }) {
  const initialAuthState = getAuthState();
  const [view, setView] = useState('login');
  const [authState, setAuthState] = useState(initialAuthState);
  const [serverUrl, setServerUrl] = useState(initialAuthState.serverUrl || '');
  const [serverError, setServerError] = useState('');
  const [serverHelp, setServerHelp] = useState('');
  const [serverBusy, setServerBusy] = useState(false);
  const [serverChecked, setServerChecked] = useState(false);
  const [authConfig, setAuthConfig] = useState(emptyConfig);

  const [authValues, setAuthValues] = useState(emptyAuthValues);
  const [authErrors, setAuthErrors] = useState({});
  const [authError, setAuthError] = useState('');
  const [authSuccess, setAuthSuccess] = useState('');
  const [redirectLabel, setRedirectLabel] = useState('');
  const [authBusy, setAuthBusy] = useState(false);
  const [busyProvider, setBusyProvider] = useState('');

  const [account, setAccount] = useState(null);
  const [accountLoading, setAccountLoading] = useState(false);
  const [accountError, setAccountError] = useState('');
  const [accountSuccess, setAccountSuccess] = useState('');

  const [username, setUsername] = useState('');
  const [profileBusy, setProfileBusy] = useState(false);
  const [profileError, setProfileError] = useState('');
  const [profileSuccess, setProfileSuccess] = useState('');

  const [passwordValues, setPasswordValues] = useState({ oldPassword: '', newPassword1: '', newPassword2: '' });
  const [passwordErrors, setPasswordErrors] = useState({});
  const [passwordError, setPasswordError] = useState('');
  const [passwordSuccess, setPasswordSuccess] = useState('');
  const [passwordBusy, setPasswordBusy] = useState(false);

  const [authenticatorValues, setAuthenticatorValues] = useState({ currentPassword: '', code: '' });
  const [authenticatorError, setAuthenticatorError] = useState('');
  const [authenticatorSuccess, setAuthenticatorSuccess] = useState('');
  const [authenticatorBusy, setAuthenticatorBusy] = useState(false);

  const [freshRecoveryCodes, setFreshRecoveryCodes] = useState([]);
  const [recoveryValues, setRecoveryValues] = useState({ currentPassword: '' });
  const [recoveryError, setRecoveryError] = useState('');
  const [recoverySuccess, setRecoverySuccess] = useState('');
  const [recoveryBusy, setRecoveryBusy] = useState(false);

  const [deleteError, setDeleteError] = useState('');
  const [deleteSuccess, setDeleteSuccess] = useState('');
  const [deleteBusy, setDeleteBusy] = useState(false);

  const signedIn = authState.status === 'authenticated';
  const accountUser = account?.user || null;
  const demoAccount = Boolean(accountUser?.isDemo);
  const lastSuperuser = Boolean(accountUser?.isLastSuperuser);
  const authenticatorSetup = account?.authenticator?.setup ?? true;
  const unusedRecoveryCodes = account?.authenticator?.unusedRecoveryCodes ?? 0;
  const providers = authConfig.providers;
  const sessionLabel = accountUser?.username || authState.user?.username || '';

  function applyAccountPayload(payload) {
    if (!payload || typeof payload !== 'object') return;
    setAccount(payload);
    if (payload.user?.username) setUsername(payload.user.username);
    if (Array.isArray(payload.freshRecoveryCodes) && payload.freshRecoveryCodes.length) {
      setFreshRecoveryCodes(payload.freshRecoveryCodes);
    }
    if (payload.message) {
      if (payload.tone === 'error') setAccountError(payload.message);
      else setAccountSuccess(payload.message);
    }
  }

  async function loadAccountState({ force = false } = {}) {
    if (!force && !signedIn) return;
    setAccountLoading(true);
    setAccountError('');
    try {
      applyAccountPayload(await accountTransport.load());
    } catch (error) {
      setAuthState(getAuthState());
      if (error?.code === AUTH_ERROR_CODES.SIGNED_OUT || error?.code === AUTH_ERROR_CODES.EXPIRED || error?.code === AUTH_ERROR_CODES.REVOKED) {
        setAccount(null);
      } else {
        setAccountError(errorMessage(error, 'Could not load account security.'));
      }
    } finally {
      setAccountLoading(false);
    }
  }

  useEffect(() => subscribeAuthSession(() => {
    setAuthState(getAuthState());
  }), []);

  useEffect(() => {
    let cancelled = false;
    restoreAuthSession().then(state => {
      if (cancelled) return;
      setAuthState(state);
      if (state.serverUrl) setServerUrl(state.serverUrl);
      if (state.status !== 'authenticated') return;
      verifyAuthSession()
        .then(next => {
          if (cancelled) return;
          setAuthState(next);
          fetchAuthConfig({ serverUrl: state.serverUrl }).then(config => { if (!cancelled) setAuthConfig(config); }).catch(() => {});
          loadAccountState({ force: true });
        })
        .catch(error => {
          if (cancelled) return;
          setAuthState(getAuthState());
          if (error?.code === AUTH_ERROR_CODES.EXPIRED || error?.code === AUTH_ERROR_CODES.REVOKED) {
            setServerUrl(getAuthState().serverUrl || state.serverUrl || '');
          } else {
            setAuthError(errorMessage(error, 'Could not verify the saved session.'));
          }
        });
    }).catch(() => {});
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    if (view === 'account' && signedIn && !account && !accountLoading) loadAccountState();
  }, [view, signedIn, account, accountLoading]);

  function chooseView(next) {
    setView(next);
    setAuthErrors({});
    setAuthError('');
    setAuthSuccess('');
    setRedirectLabel('');
    setAccountError('');
    setAccountSuccess('');
  }

  function updateAuth(name, value) {
    setAuthValues(current => ({ ...current, [name]: value }));
    setAuthErrors(current => ({ ...current, [name]: undefined }));
    setAuthError('');
    if (name === 'serverUrl') {
      setServerUrl(value);
      setServerChecked(false);
      setServerError('');
    }
  }

  function validateAuth(mode) {
    const next = {};
    if (!serverUrl.trim()) next.serverUrl = 'Enter the address of your Floppy server.';
    if (mode !== 'login' && !authValues.username.trim()) next.username = 'Enter your username.';
    if (mode === 'login' && !authValues.login.trim()) next.login = 'Enter your username.';
    if (mode === 'login' && !authValues.password) next.password = 'Enter your password.';
    if (mode === 'signup') {
      if (!authValues.password1) next.password1 = 'Choose a password.';
      if (authValues.password1 !== authValues.password2) next.password2 = 'The passwords do not match.';
    }
    if (mode === 'recovery') {
      if (!authValues.authenticatorCode && !authValues.recoveryCode) {
        next.authenticatorCode = 'Enter an authenticator or recovery code.';
        next.recoveryCode = 'Enter an authenticator or recovery code.';
      }
      if (!authValues.newPassword1) next.newPassword1 = 'Choose a new password.';
      if (authValues.newPassword1 !== authValues.newPassword2) next.newPassword2 = 'The passwords do not match.';
    }
    setAuthErrors(next);
    if (next.serverUrl) setServerError(next.serverUrl);
    return Object.keys(next).length === 0;
  }

  async function loadConfig() {
    const config = await fetchAuthConfig({ serverUrl });
    setAuthConfig(config);
    if (config.serverUrl) setServerUrl(config.serverUrl);
    return config;
  }

  async function checkServer() {
    setServerError('');
    setServerHelp('');
    setServerChecked(false);
    setServerBusy(true);
    try {
      const reachable = await testAuthConnection({ serverUrl });
      const config = await loadConfig();
      setServerChecked(true);
      setServerHelp(reachable.serverUrl ? `Reached ${reachable.serverUrl}` : 'Server reachable.');
      if (config.firstRun) setServerHelp('First run: create the first account for this server.');
    } catch (error) {
      setServerError(errorMessage(error, 'Could not reach that server.'));
    } finally {
      setServerBusy(false);
    }
  }

  async function submitAuth(options = {}) {
    setAuthError('');
    setAuthSuccess('');
    setRedirectLabel('');
    setServerError('');
    if (!validateAuth(view)) {
      setAuthError('Check the highlighted fields and try again.');
      return;
    }
    setAuthBusy(true);
    try {
      if (view === 'login') {
        const state = await signIn({
          serverUrl,
          username: authValues.login,
          password: authValues.password,
          redirectTo: '/',
        });
        setAuthState(state);
        setAuthValues(emptyAuthValues);
        setServerUrl(state.serverUrl || serverUrl);
        setServerChecked(true);
        loadConfig().catch(() => {});
        await loadAccountState({ force: true });
        setView('account');
        setAccountSuccess('Signed in. Your session is stored securely on this device.');
      } else if (view === 'signup') {
        const state = await signUp({
          serverUrl,
          username: authValues.username,
          password1: authValues.password1,
          password2: authValues.password2,
          setupAuthenticator: Boolean(options.setupAuthenticator),
        });
        setAuthState(state);
        setAuthValues(emptyAuthValues);
        setServerUrl(state.serverUrl || serverUrl);
        setServerChecked(true);
        loadConfig().catch(() => {});
        await loadAccountState({ force: true });
        setView('account');
        setAccountSuccess(options.setupAuthenticator
          ? 'Account created. Verify an authenticator app below.'
          : 'Account created. Set up an authenticator app so recovery is possible.');
      } else {
        await recoverPassword({
          serverUrl,
          username: authValues.username,
          authenticatorCode: authValues.authenticatorCode,
          recoveryCode: authValues.recoveryCode,
          newPassword1: authValues.newPassword1,
          newPassword2: authValues.newPassword2,
        });
        setAuthValues(emptyAuthValues);
        setAuthSuccess('Password updated. Sign in with the new password.');
        setRedirectLabel('Back to sign in');
      }
    } catch (error) {
      if (error?.code === AUTH_ERROR_CODES.INVALID_SERVER) setServerError(errorMessage(error, 'Check the server address.'));
      else setAuthError(errorMessage(error, 'Check the details and try again.'));
    } finally {
      setAuthBusy(false);
    }
  }

  async function signInWithProvider(provider) {
    setBusyProvider(provider.id);
    setAuthError('');
    setAuthSuccess('');
    try {
      const url = provider.loginUrl || buildProviderLoginUrl({ serverUrl, providerId: provider.id });
      await Linking.openURL(url);
      setAuthSuccess(`${provider.name} sign-in opened in the secure browser session. Return to Floppy and sign in with your server account.`);
    } catch (error) {
      setAuthError(errorMessage(error, `Could not open ${provider.name} sign-in.`));
    } finally {
      setBusyProvider('');
    }
  }

  async function openExternal(url, success) {
    setAccountError('');
    setAccountSuccess('');
    try {
      await Linking.openURL(url);
      setAccountSuccess(success);
    } catch {
      setAccountError('The link could not be opened on this device.');
    }
  }

  function continueFromNotice() {
    chooseView(view === 'recovery' ? 'login' : 'account');
  }

  async function saveProfile() {
    setProfileBusy(true);
    setProfileError('');
    setProfileSuccess('');
    try {
      const payload = await accountTransport.updateProfile({ username });
      applyAccountPayload(payload);
      setProfileSuccess(payload?.message || 'Your username has been updated.');
      setAccountError('');
      setAccountSuccess('');
    } catch (error) {
      const fieldError = firstFieldError(error, ['username']);
      setProfileError(fieldError || errorMessage(error, 'Could not update your username.'));
    } finally {
      setProfileBusy(false);
    }
  }

  async function savePassword() {
    setPasswordError('');
    setPasswordSuccess('');
    const next = {};
    if (!passwordValues.oldPassword) next.oldPassword = 'Enter your current password.';
    if (!passwordValues.newPassword1) next.newPassword1 = 'Choose a new password.';
    if (passwordValues.newPassword1 !== passwordValues.newPassword2) next.newPassword2 = 'The passwords do not match.';
    setPasswordErrors(next);
    if (Object.keys(next).length) return;
    setPasswordBusy(true);
    try {
      const payload = await accountTransport.changePassword(passwordValues);
      applyAccountPayload(payload);
      setPasswordValues({ oldPassword: '', newPassword1: '', newPassword2: '' });
      setPasswordSuccess(payload?.message || 'Your password has been updated.');
      setAccountError('');
      setAccountSuccess('');
    } catch (error) {
      setPasswordErrors({
        oldPassword: firstFieldError(error, ['old_password']),
        newPassword1: firstFieldError(error, ['new_password1']),
        newPassword2: firstFieldError(error, ['new_password2']),
      });
      setPasswordError(firstFieldError(error, ['old_password', 'new_password1', 'new_password2', 'non_field_errors']) || errorMessage(error, 'Could not update your password.'));
    } finally {
      setPasswordBusy(false);
    }
  }

  async function enableAuthenticator() {
    setAuthenticatorError('');
    setAuthenticatorSuccess('');
    if (!authenticatorValues.currentPassword) {
      setAuthenticatorError('Enter your current password to confirm this change.');
      return;
    }
    if (!authenticatorValues.code.trim()) {
      setAuthenticatorError('Enter the 6-digit code from the authenticator app.');
      return;
    }
    setAuthenticatorBusy(true);
    try {
      const payload = await accountTransport.enableAuthenticator(authenticatorValues);
      applyAccountPayload(payload);
      setAuthenticatorValues({ currentPassword: '', code: '' });
      setAuthenticatorSuccess(payload?.message || 'Authenticator app enabled. Save your recovery codes now.');
    } catch (error) {
      setAuthenticatorError(firstFieldError(error, ['code', 'current_password', 'non_field_errors']) || errorMessage(error, 'Could not enable the authenticator.'));
    } finally {
      setAuthenticatorBusy(false);
    }
  }

  async function startAuthenticatorSetup() {
    setAuthenticatorError('');
    setAuthenticatorSuccess('');
    if (!authenticatorValues.currentPassword) {
      setAuthenticatorError('Enter your current password to replace the authenticator.');
      return;
    }
    setAuthenticatorBusy(true);
    try {
      const payload = await accountTransport.startAuthenticatorSetup({ currentPassword: authenticatorValues.currentPassword });
      applyAccountPayload(payload);
      setFreshRecoveryCodes([]);
      setAuthenticatorValues({ currentPassword: '', code: '' });
      setAuthenticatorSuccess(payload?.message || 'Scan and verify a code from the new authenticator app to finish setup.');
    } catch (error) {
      setAuthenticatorError(firstFieldError(error, ['current_password', 'non_field_errors']) || errorMessage(error, 'Could not start authenticator setup.'));
    } finally {
      setAuthenticatorBusy(false);
    }
  }

  async function disableAuthenticator() {
    setAuthenticatorError('');
    setAuthenticatorSuccess('');
    if (!authenticatorValues.currentPassword) {
      setAuthenticatorError('Enter your current password to deactivate the authenticator.');
      return;
    }
    setAuthenticatorBusy(true);
    try {
      const payload = await accountTransport.disableAuthenticator({ currentPassword: authenticatorValues.currentPassword });
      applyAccountPayload(payload);
      setFreshRecoveryCodes([]);
      setAuthenticatorValues({ currentPassword: '', code: '' });
      setAuthenticatorSuccess(payload?.message || 'Authenticator app deactivated.');
    } catch (error) {
      setAuthenticatorError(firstFieldError(error, ['current_password', 'non_field_errors']) || errorMessage(error, 'Could not deactivate the authenticator.'));
    } finally {
      setAuthenticatorBusy(false);
    }
  }

  async function regenerateRecoveryCodes() {
    setRecoveryError('');
    setRecoverySuccess('');
    if (!recoveryValues.currentPassword) {
      setRecoveryError('Enter your current password to regenerate recovery codes.');
      return;
    }
    setRecoveryBusy(true);
    try {
      const payload = await accountTransport.regenerateRecoveryCodes(recoveryValues);
      applyAccountPayload(payload);
      setRecoveryValues({ currentPassword: '' });
      setRecoverySuccess(payload?.message || 'Recovery codes regenerated. Store them securely now.');
    } catch (error) {
      setRecoveryError(firstFieldError(error, ['current_password', 'non_field_errors']) || errorMessage(error, 'Could not regenerate recovery codes.'));
    } finally {
      setRecoveryBusy(false);
    }
  }

  async function deleteAccount(details = {}) {
    setDeleteError('');
    setDeleteSuccess('');
    if (demoAccount) {
      setDeleteError('This section is view-only for demo accounts.');
      return;
    }
    if (lastSuperuser) {
      setDeleteError('Promote another account before deleting this one.');
      return;
    }
    setDeleteBusy(true);
    try {
      const payload = await accountTransport.deleteAccount(details);
      setAccount(null);
      setAuthState(getAuthState());
      setView('login');
      setAuthValues(emptyAuthValues);
      setAuthSuccess(payload?.message || 'Your account and all its data have been deleted.');
      setRedirectLabel('');
    } catch (error) {
      setDeleteError(firstFieldError(error, ['current_password', 'confirm_username', 'confirm_delete', 'non_field_errors']) || errorMessage(error, 'Could not delete the account.'));
    } finally {
      setDeleteBusy(false);
    }
  }

  async function handleSignOut() {
    await signOut().catch(() => {});
    setAuthState(getAuthState());
    setAccount(null);
    setAuthValues(emptyAuthValues);
    setView('login');
    setAuthSuccess('Signed out.');
    setRedirectLabel('');
  }

  const sessionNotice = authState.status === 'expired'
    ? 'Your session expired. Sign in again to continue.'
    : authState.status === 'revoked'
      ? 'This session was revoked or is no longer valid. Sign in again.'
      : '';

  return <Screen title="Account" subtitle="Authentication and account security" onBack={onBack}>
    <View style={styles.viewRow}>
      {views.map(item => <GuardChip key={item.key} label={item.label} active={view === item.key} onPress={() => chooseView(item.key)} />)}
    </View>

    {sessionNotice ? <AuthNotice tone="warning" palette={authPalette}>{sessionNotice}</AuthNotice> : null}

    {view === 'login' || view === 'signup' || view === 'recovery' ? <AuthView
      mode={view}
      notice={null}
      palette={authPalette}
      buttonPalette={buttonPalette}
      entrance={{
        firstRun: authConfig.firstRun,
        registrationEnabled: authConfig.registrationEnabled,
        socialOnly: authConfig.socialOnly,
        providers,
        serverUrl,
        serverError,
        serverHelp,
        serverBusy,
        serverChecked,
        values: authValues,
        errors: authErrors,
        error: authError,
        success: authSuccess,
        redirectLabel,
        busy: authBusy,
        busyProvider,
        onChange: (name, value) => updateAuth(name, value),
        onServerChange: value => updateAuth('serverUrl', value),
        onCheckServer: checkServer,
        onSubmit: submitAuth,
        onSwitchMode: chooseView,
        onForgotPassword: () => chooseView('recovery'),
        onProvider: signInWithProvider,
        onContinue: continueFromNotice,
      }} /> : null}

    {view === 'account' ? <View style={styles.viewStack}>
      {!signedIn || !account ? <>
        {!signedIn ? <AuthNotice tone="warning" palette={authPalette}>Sign in first to load your account and security settings.</AuthNotice> : null}
        {signedIn && accountLoading ? <Text style={[styles.loading, { color: palette.textMuted }]}>Loading account security…</Text> : null}
        {accountError ? <AuthNotice tone="error" palette={authPalette}>{accountError}</AuthNotice> : null}
        {accountSuccess ? <AuthNotice tone="success" palette={authPalette}>{accountSuccess}</AuthNotice> : null}
      </> : <SettingsAccountView
        labels={{
          title: 'Account security',
          copy: sessionLabel ? `Signed in to ${authState.serverUrl} as ${sessionLabel}.` : 'Manage your account and security settings.',
        }}
        notices={<>
          {accountError ? <AuthNotice tone="error" palette={authPalette}>{accountError}</AuthNotice> : null}
          {accountSuccess ? <AuthNotice tone="success" palette={authPalette}>{accountSuccess}</AuthNotice> : null}
          {demoAccount ? <AuthNotice tone="warning" palette={authPalette}>Demo accounts are view-only for authenticator, recovery, profile and deletion changes.</AuthNotice> : null}
          {lastSuperuser ? <AuthNotice tone="warning" palette={authPalette}>You are the only active superuser. Promote another account before deleting this one.</AuthNotice> : null}
          {deleteSuccess ? <AuthNotice tone="success" palette={authPalette}>{deleteSuccess}</AuthNotice> : null}
        </>}
        actions={<Button label="Sign out" tone="surface" onPress={handleSignOut} palette={buttonPalette} />}
        profile={{
          username, error: profileError, success: profileSuccess, busy: profileBusy,
          disabled: demoAccount, onChangeUsername: setUsername, onSave: saveProfile,
        }}
        accountType={{ isSuperuser: Boolean(accountUser?.isSuperuser), username }}
        password={{
          values: passwordValues, errors: passwordErrors, error: passwordError,
          success: passwordSuccess, busy: passwordBusy, disabled: demoAccount,
          onChange: (name, value) => {
            setPasswordValues(current => ({ ...current, [name]: value }));
            setPasswordErrors(current => ({ ...current, [name]: undefined }));
            setPasswordError('');
          },
          onSubmit: savePassword,
        }}
        authenticator={{
          configured: Boolean(account?.authenticator?.configured), setup: authenticatorSetup,
          demo: demoAccount, values: authenticatorValues, error: authenticatorError,
          success: authenticatorSuccess, busy: authenticatorBusy,
          qrSlot: account?.authenticator?.qrDataUri
            ? <Image accessibilityLabel="Authenticator setup QR code" source={{ uri: account.authenticator.qrDataUri }} style={styles.qrImage} />
            : null,
          secretSlot: account?.authenticator?.secret
            ? <Text selectable style={[styles.secret, { color: palette.textSecondary }]}>{account.authenticator.secret}</Text>
            : <Text style={[styles.secretHint, { color: palette.textMuted }]}>The server did not return a setup secret.</Text>,
          onChange: (name, value) => {
            setAuthenticatorValues(current => ({ ...current, [name]: value }));
            setAuthenticatorError('');
          },
          onEnable: enableAuthenticator,
          onStartSetup: startAuthenticatorSetup,
          onDisable: disableAuthenticator,
        }}
        recovery={{
          unusedCount: unusedRecoveryCodes, freshCodes: freshRecoveryCodes,
          values: recoveryValues, error: recoveryError, success: recoverySuccess,
          busy: recoveryBusy, demo: demoAccount,
          onChange: (name, value) => {
            setRecoveryValues(current => ({ ...current, [name]: value }));
            setRecoveryError('');
          },
          onRegenerate: regenerateRecoveryCodes,
        }}
        connections={{
          providerCount: account.providers?.length || 0, disabled: demoAccount,
          onManageConnections: () => openExternal(account.connectionsUrl, 'Account connections opened in the secure browser session.'),
          onApproveDevice: () => openExternal(account.deviceUrl || buildDeviceVerificationUrl({ serverUrl: authState.serverUrl || serverUrl }), 'Device sign-in approval opened in the secure browser session.'),
        }}
        deletion={{
          account: {
            username: accountUser?.username || username,
            isDemo: demoAccount,
            isLastSuperuser: lastSuperuser,
            hasUsablePassword: accountUser?.hasUsablePassword !== false,
            isSuperuser: Boolean(accountUser?.isSuperuser),
          },
          error: deleteError, busy: deleteBusy, onDelete: deleteAccount,
        }}
        palette={authPalette} buttonPalette={buttonPalette} />}
    </View> : null}
  </Screen>;
}

const styles = StyleSheet.create({
  viewStack: { gap: spacing.md, minWidth: 0 },
  viewRow: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm },
  guardRow: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm },
  loading: { fontSize: 13, lineHeight: 19 },
  qrImage: { width: 128, height: 128 },
  secret: { fontFamily: 'Courier', fontSize: 12, lineHeight: 17 },
  secretHint: { fontSize: 12, lineHeight: 17 },
});
