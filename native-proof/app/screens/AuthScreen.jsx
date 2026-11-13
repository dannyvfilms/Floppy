import React, { useEffect, useRef, useState } from 'react';
import { Image, Linking, StyleSheet, Text, View } from 'react-native';
import {
  accountTransport,
  AUTH_ERROR_CODES,
  beginProviderSignIn,
  buildDeviceVerificationUrl,
  fetchAuthConfig,
  getAuthState,
  isBrowserAuth,
  pollDeviceSignIn,
  recoverPassword,
  restoreAuthSession,
  signIn,
  signOut,
  signUp,
  startDeviceSignIn,
  testAuthConnection,
  verifyAuthSession,
} from '../data/authTransport';
import { subscribeAuthSession } from '../data/authSession';
import { findFloppyServers } from '../data/serverDiscovery';
import { verifyDiscoveredServers } from '../data/serverDiscoveryCore';
import { AuthNotice } from '../../../frontend/auth/AuthEntrance';
import { AuthView } from '../../../frontend/pages/AuthView';
import { SettingsAccountView } from '../../../frontend/pages/SettingsAccountView';
import { Button } from '../../../frontend/ui/Button';
import { Chip } from '../../../frontend/settings/Chip';
import { Screen } from '../components/Screen';
import { palette, radius, spacing } from '../theme';
import { useSettingsPalettes } from '../surfaces/settingsPalettes';

export const surface = {
  id: 'AUTH',
  status: 'ported',
  title: 'Account and authentication',
  where: 'Login, signup, social, password, TOTP, recovery, connections and deletion guards',
  note: 'Server URL and connection checks, session sign-in/signup/recovery, verified restore, expiry/revocation, sign-out, account profile/password/TOTP/recovery/delete actions and social/device browser intents use the shared React Native presentation and authenticated transport. Social and OIDC sign-in completes in the app: native uses the OAuth device flow as the first-party Floppy app client (authorize, approve full account access in the browser, poll for a refreshable token that can also open account security; a server without that client falls back to registering and a scoped token), web redirects through the provider and back with the session cookie. The Expo web build adopts the same-origin session and sends the CSRF cookie value on writes. iOS, Android and browser runtime remain unverified.',
};

const authPalette = {
  background: palette.background,
  surface: palette.surface,
  surfaceStrong: palette.surfaceStrong,
  surfaceMuted: palette.surfaceMuted,
  border: '#4b5563',
  text: palette.text,
  textSecondary: palette.textSecondary,
  textMuted: palette.textMuted,
  accent: palette.accent,
  accentStrong: palette.accentStrong,
  link: palette.link,
  success: palette.success,
  warning: palette.warning,
  danger: palette.danger,
  badgeBorder: palette.surfaceMuted,
  badgeBackground: palette.surfaceStrong,
  badgeText: palette.textSecondary,
  badgeHover: palette.surfaceMuted,
  overlay: 'rgba(0, 0, 0, 0.65)',
  radius: 12,
  inputBackground: '#39404b',
  focusStyle: {},
};

const buttonPalette = {
  primary: { background: palette.accentStrong, pressed: '#4338ca', hovered: '#4338ca', text: '#ffffff', border: 'transparent' },
  surface: { background: palette.surfaceStrong, pressed: palette.surfaceMuted, hovered: palette.surfaceMuted, text: palette.text, border: palette.border },
  'danger-solid': { background: palette.danger, pressed: '#b91c1c', hovered: '#b91c1c', text: '#ffffff', border: 'transparent' },
  'danger-deep': { background: '#b91c1c', pressed: '#991b1b', hovered: '#991b1b', text: '#ffffff', border: 'transparent' },
  radius: 12,
  focusStyle: {},
};

const views = [
  { key: 'login', label: 'Sign In' },
  { key: 'signup', label: 'Create Account' },
  { key: 'recovery', label: 'Recover Password' },
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

export default function AuthScreen({ onBack, entranceOnly = false, embedded = false }) {
  const { settingsPalette, buttonPalette: settingsButtons } = useSettingsPalettes();
  const initialAuthState = getAuthState();
  const [view, setView] = useState(embedded ? 'account' : 'login');
  const [authStep, setAuthStep] = useState(isBrowserAuth ? 'credentials' : 'server');
  const deviceSignIn = useRef(null);
  const [authState, setAuthState] = useState(initialAuthState);
  const [serverUrl, setServerUrl] = useState(initialAuthState.serverUrl || '');
  const [serverError, setServerError] = useState('');
  const [serverHelp, setServerHelp] = useState('');
  const [serverBusy, setServerBusy] = useState(false);
  const [serverChecked, setServerChecked] = useState(isBrowserAuth);
  const [serverMode, setServerMode] = useState('local');
  const [serverHelpVisible, setServerHelpVisible] = useState(false);
  const [serverDiscoveryBusy, setServerDiscoveryBusy] = useState(false);
  const [serverDiscoverySupported, setServerDiscoverySupported] = useState(true);
  const [serverDiscoveryPermissionDenied, setServerDiscoveryPermissionDenied] = useState(false);
  const [serverDiscoveryMessage, setServerDiscoveryMessage] = useState('');
  const [discoveredServers, setDiscoveredServers] = useState([]);
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

  // The web build talks to the server it was loaded from, so there is no
  // address to enter: read the sign-in options straight away.
  useEffect(() => {
    if (!isBrowserAuth) return undefined;
    let cancelled = false;
    fetchAuthConfig({}).then(config => {
      if (cancelled) return;
      setAuthConfig(config);
      setServerUrl(config.serverUrl);
    }).catch(error => {
      if (!cancelled) setAuthError(errorMessage(error, 'Could not reach the Floppy server.'));
    });
    return () => { cancelled = true; };
  }, []);

  useEffect(() => () => { deviceSignIn.current?.abort(); }, []);

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
      setServerDiscoveryMessage('');
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
      return true;
    } catch (error) {
      setServerError(errorMessage(error, 'Could not reach that server.'));
      return false;
    } finally {
      setServerBusy(false);
    }
  }

  async function continueToCredentials() {
    if (serverChecked || await checkServer()) setAuthStep('credentials');
  }

  function clearServerAddress() {
    updateAuth('serverUrl', '');
    setServerError('');
    setServerHelp('');
    setServerChecked(false);
    setDiscoveredServers([]);
    setServerDiscoveryMessage('');
  }

  async function discoverServers() {
    setServerDiscoveryBusy(true);
    setServerDiscoveryPermissionDenied(false);
    setServerError('');
    setAuthErrors(current => ({ ...current, serverUrl: undefined }));
    setServerHelp('');
    setServerDiscoveryMessage('searching');
    setDiscoveredServers([]);
    try {
      const result = await findFloppyServers();
      setServerDiscoverySupported(result.supported);
      if (!result.supported) {
        setServerDiscoveryMessage('unavailable');
        return;
      }
      if (result.permissionDenied) {
        setServerDiscoveryPermissionDenied(true);
        setServerDiscoveryMessage('permission');
        return;
      }

      const verified = await verifyDiscoveredServers(result.servers, fetchAuthConfig);
      setDiscoveredServers(verified);
      setServerDiscoveryMessage(verified.length ? '' : 'empty');
    } catch {
      setServerDiscoveryMessage('Could not search this network for Floppy servers. Try again or enter the address manually.');
    } finally {
      setServerDiscoveryBusy(false);
    }
  }

  function selectDiscoveredServer(server) {
    setServerUrl(server.serverUrl);
    setServerError('');
    setServerChecked(true);
    setServerHelp(`${server.name} found at ${server.serverUrl}`);
    setAuthConfig(server.config);
  }

  async function submitAuth(options = {}) {
    setAuthError('');
    setAuthSuccess('');
    setRedirectLabel('');
    setServerError('');
    if (!validateAuth(view)) {
      setAuthError('Check the details and try again.');
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
        setAccountSuccess(isBrowserAuth ? 'Signed in.' : 'Signed in. Your session is stored securely on this device.');
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
        setAuthSuccess('Password updated. Sign in with your new password.');
        setRedirectLabel('Back to sign in');
      }
    } catch (error) {
      if (error?.code === AUTH_ERROR_CODES.INVALID_SERVER) {
        setServerError(errorMessage(error, 'Check the server address.'));
        setAuthStep('server');
      }
      else setAuthError(errorMessage(error, 'Check the details and try again.'));
    } finally {
      setAuthBusy(false);
    }
  }

  async function signInWithProvider(provider) {
    setBusyProvider(provider.id);
    setAuthError('');
    setAuthSuccess('');
    deviceSignIn.current?.abort();
    try {
      if (beginProviderSignIn) {
        // Web: the provider login redirects back to this app with the session cookie.
        await beginProviderSignIn({ provider });
        return;
      }
      // Native: the server's device page signs in with the provider and the app
      // collects a scoped token, so the session returns here.
      const controller = new AbortController();
      deviceSignIn.current = controller;
      const grant = await startDeviceSignIn({ serverUrl });
      await Linking.openURL(grant.verificationUriComplete);
      setAuthSuccess(`Sign in with ${provider.name} in your browser and approve this device. Code ${grant.userCode}.`);
      const state = await pollDeviceSignIn({ ...grant, signal: controller.signal });
      setAuthState(state);
      setAuthSuccess('');
      setAuthValues(emptyAuthValues);
    } catch (error) {
      if (error?.code === AUTH_ERROR_CODES.SIGNED_OUT) setAuthSuccess('');
      else {
        setAuthSuccess('');
        setAuthError(errorMessage(error, `Could not sign in with ${provider.name}.`));
      }
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
      setPasswordSuccess(payload?.message || 'Password updated.');
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
      setDeleteError('You are the only superuser. Promote another account before deleting this one.');
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
    try {
      await signOut();
    } catch (error) {
      // A browser session can only end on the server, so report a failure.
      setAccountError(errorMessage(error, 'Could not sign out. Try again.'));
      return;
    }
    setAuthState(getAuthState());
    setAccount(null);
    setAuthValues(emptyAuthValues);
    setView('login');
    setAuthStep(isBrowserAuth ? 'credentials' : 'server');
    setAuthSuccess('Signed out.');
    setRedirectLabel('');
  }

  const sessionNotice = authState.status === 'expired'
    ? 'Your session expired. Sign in again to continue.'
    : authState.status === 'revoked'
      ? 'This session was revoked or is no longer valid. Sign in again.'
      : '';

  const authForm = view === 'login' || view === 'signup' || view === 'recovery' ? <AuthView
    mode={view}
    heading={false}
    notice={null}
    palette={authPalette}
    buttonPalette={buttonPalette}
    entrance={{
      authStep,
      firstRun: authConfig.firstRun,
      registrationEnabled: authConfig.registrationEnabled,
      socialOnly: authConfig.socialOnly,
      providers,
      serverUrl,
      serverError,
      serverHelp,
      serverBusy,
      serverChecked,
      serverMode,
      serverHelpVisible,
      serverDiscoveryBusy,
      serverDiscoverySupported,
      serverDiscoveryPermissionDenied,
      serverDiscoveryMessage,
      discoveredServers,
      values: authValues,
      errors: authErrors,
      error: authError,
      success: authSuccess,
      redirectLabel,
      busy: authBusy,
      busyProvider,
      onChange: (name, value) => updateAuth(name, value),
      onServerChange: value => updateAuth('serverUrl', value),
      onContinueServer: continueToCredentials,
      onChangeServer: () => setAuthStep('server'),
      serverLocked: isBrowserAuth,
      onClearServerAddress: clearServerAddress,
      onCheckServer: checkServer,
      onServerModeChange: setServerMode,
      onToggleServerHelp: () => setServerHelpVisible(current => !current),
      onDiscoverServers: discoverServers,
      onSelectDiscoveredServer: selectDiscoveredServer,
      onSubmit: submitAuth,
      onSwitchMode: chooseView,
      onForgotPassword: () => chooseView('recovery'),
      onProvider: signInWithProvider,
      onContinue: continueFromNotice,
    }} /> : null;

  if (entranceOnly) {
    return <View style={styles.entrance}>
      {sessionNotice ? <AuthNotice tone="warning" palette={authPalette}>{sessionNotice}</AuthNotice> : null}
      {authForm}
    </View>;
  }

  const Container = embedded ? View : Screen;
  return <Container {...(embedded ? { style: styles.viewStack } : { title: 'Account', subtitle: 'Authentication and account security', onBack })}>
    {!embedded ? <View style={styles.viewRow}>
      {views.map(item => <GuardChip key={item.key} label={item.label} active={view === item.key} onPress={() => chooseView(item.key)} />)}
    </View> : null}

    {sessionNotice ? <AuthNotice tone="warning" palette={authPalette}>{sessionNotice}</AuthNotice> : null}

    {authForm}

    {view === 'account' ? <View style={styles.viewStack}>
      {!signedIn || !account ? <>
        {!signedIn ? <AuthNotice tone="warning" palette={authPalette}>Sign in first to load your account and security settings.</AuthNotice> : null}
        {signedIn && accountLoading ? <Text style={[styles.loading, { color: palette.textMuted }]}>Loading account security…</Text> : null}
        {accountError ? <AuthNotice tone="error" palette={authPalette}>{accountError}</AuthNotice> : null}
        {accountSuccess ? <AuthNotice tone="success" palette={authPalette}>{accountSuccess}</AuthNotice> : null}
      </> : <SettingsAccountView
        heading={!embedded}
        labels={{
          title: 'Account security',
          copy: sessionLabel ? `Signed in to ${authState.serverUrl} as ${sessionLabel}.` : 'Manage your account and security settings.',
        }}
        notices={<>
          {accountError ? <AuthNotice tone="error" palette={authPalette}>{accountError}</AuthNotice> : null}
          {accountSuccess ? <AuthNotice tone="success" palette={authPalette}>{accountSuccess}</AuthNotice> : null}
          {demoAccount ? <AuthNotice tone="warning" palette={authPalette}>Demo accounts are view-only for authenticator, recovery, profile and deletion changes.</AuthNotice> : null}
          {lastSuperuser && !embedded ? <AuthNotice tone="warning" palette={authPalette}>You are the only active superuser. Promote another account before deleting this one.</AuthNotice> : null}
          {deleteSuccess ? <AuthNotice tone="success" palette={authPalette}>{deleteSuccess}</AuthNotice> : null}
        </>}
        actions={embedded ? null : <Button label="Sign out" tone="surface" onPress={handleSignOut} palette={buttonPalette} />}
        profile={{
          username, error: profileError, success: profileSuccess, busy: profileBusy,
          disabled: demoAccount, onChangeUsername: setUsername, onSave: saveProfile,
        }}
        accountType={{ isSuperuser: Boolean(accountUser?.isSuperuser), username }}
        password={{
          sessionRequired: Boolean(account.credentialSessionRequired),
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
          sessionRequired: Boolean(account.credentialSessionRequired),
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
          sessionRequired: Boolean(account.credentialSessionRequired),
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
          visible: !embedded,
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
        palette={embedded ? { ...settingsPalette, pageCards: true } : authPalette} buttonPalette={embedded ? settingsButtons : buttonPalette} />}
    </View> : null}
  </Container>;
}

const styles = StyleSheet.create({
  entrance: { gap: 8 },
  viewStack: { gap: spacing.md, minWidth: 0 },
  viewRow: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm },
  guardRow: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm },
  loading: { fontSize: 13, lineHeight: 19 },
  qrImage: { width: 128, height: 128 },
  secret: { fontFamily: 'Courier', fontSize: 12, lineHeight: 17 },
  secretHint: { fontSize: 12, lineHeight: 17 },
});
