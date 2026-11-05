import React, { useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';
import '../data/authTransport';
import { AuthEntrance, AuthNotice } from '../../../frontend/auth/AuthEntrance';
import {
  AccountTypeCard,
  AuthenticatorCard,
  ConnectionsCard,
  DeleteAccountCard,
  PasswordCard,
  ProfileCard,
  RecoveryCodesCard,
} from '../../../frontend/auth/AccountSecurity';
import { Chip } from '../../../frontend/settings/Chip';
import { Screen, Section } from '../components/Screen';
import { palette, radius, spacing } from '../theme';

export const surface = {
  id: 'AUTH',
  status: 'in_progress',
  title: 'Account and authentication',
  where: 'Login, signup, social, password, TOTP, recovery, connections and deletion guards',
  note: 'Auth finishing pass in progress: wiring the shared entrance and account-security presentation to the authenticated transport (server URL, sign-in, session lifecycle, redirect intents and account actions). iOS and Android runtime remain unverified.',
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

const providers = [
  { id: 'plex', label: 'Plex' },
  { id: 'trakt', label: 'Trakt' },
  { id: 'authentik', label: 'Authentik' },
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

function wait(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

function GuardChip({ label, active, onPress }) {
  return <Chip label={label} palette={authPalette} pressed={active} onPress={onPress} />;
}

export default function AuthScreen({ onBack }) {
  const [view, setView] = useState('login');
  const [authValues, setAuthValues] = useState(emptyAuthValues);
  const [authErrors, setAuthErrors] = useState({});
  const [authError, setAuthError] = useState('');
  const [authSuccess, setAuthSuccess] = useState('');
  const [redirectLabel, setRedirectLabel] = useState('');
  const [authBusy, setAuthBusy] = useState(false);
  const [busyProvider, setBusyProvider] = useState('');

  const [guard, setGuard] = useState('owner');
  const [username, setUsername] = useState('nova');
  const [profileBusy, setProfileBusy] = useState(false);
  const [profileError, setProfileError] = useState('');
  const [profileSuccess, setProfileSuccess] = useState('');
  const [passwordValues, setPasswordValues] = useState({ oldPassword: '', newPassword1: '', newPassword2: '' });
  const [passwordErrors, setPasswordErrors] = useState({});
  const [passwordError, setPasswordError] = useState('');
  const [passwordSuccess, setPasswordSuccess] = useState('');
  const [passwordBusy, setPasswordBusy] = useState(false);
  const [authenticatorSetup, setAuthenticatorSetup] = useState(true);
  const [authenticatorValues, setAuthenticatorValues] = useState({ currentPassword: '', code: '' });
  const [authenticatorError, setAuthenticatorError] = useState('');
  const [authenticatorSuccess, setAuthenticatorSuccess] = useState('');
  const [authenticatorBusy, setAuthenticatorBusy] = useState(false);
  const [unusedRecoveryCodes, setUnusedRecoveryCodes] = useState(8);
  const [freshRecoveryCodes, setFreshRecoveryCodes] = useState([]);
  const [recoveryValues, setRecoveryValues] = useState({ currentPassword: '' });
  const [recoveryError, setRecoveryError] = useState('');
  const [recoverySuccess, setRecoverySuccess] = useState('');
  const [recoveryBusy, setRecoveryBusy] = useState(false);
  const [deleteError, setDeleteError] = useState('');
  const [deleteSuccess, setDeleteSuccess] = useState('');
  const [deleteBusy, setDeleteBusy] = useState(false);

  const demoAccount = guard === 'demo';
  const lastSuperuser = guard === 'last';
  const account = {
    username,
    isDemo: demoAccount,
    isLastSuperuser: lastSuperuser,
    hasUsablePassword: true,
    isSuperuser: lastSuperuser,
  };

  function chooseView(next) {
    setView(next);
    setAuthErrors({});
    setAuthError('');
    setAuthSuccess('');
    setRedirectLabel('');
  }

  function updateAuth(name, value) {
    setAuthValues(current => ({ ...current, [name]: value }));
    setAuthErrors(current => ({ ...current, [name]: undefined }));
  }

  function validateAuth(mode) {
    const next = {};
    if (!authValues.username.trim() && mode !== 'login') next.username = 'Enter your username.';
    if (!authValues.login.trim() && mode === 'login') next.login = 'Enter your username.';
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
    return Object.keys(next).length === 0;
  }

  async function submitAuth(options = {}) {
    setAuthError('');
    setAuthSuccess('');
    setRedirectLabel('');
    if (!validateAuth(view)) {
      setAuthError('Check the highlighted fields and try again.');
      return;
    }
    setAuthBusy(true);
    await wait(500);
    setAuthBusy(false);
    if (view === 'login') {
      setAuthSuccess('Signed in. The platform adapter would store the session securely and redirect to the requested page.');
      setRedirectLabel('Continue to Home');
    } else if (view === 'signup') {
      setAuthSuccess(options.setupAuthenticator
        ? 'Account created. Continue into authenticator setup, or choose to set it up from Account security later.'
        : 'Account created. Set up an authenticator app from Account security so recovery is possible.');
      setRedirectLabel(options.setupAuthenticator ? 'Continue to authenticator setup' : 'Continue to onboarding');
    } else {
      setAuthSuccess('Password updated. Sign in with the new password using the authenticator or recovery code you verified.');
      setRedirectLabel('Back to sign in');
      setAuthValues(emptyAuthValues);
    }
  }

  async function signInWithProvider(provider) {
    setBusyProvider(provider.id);
    setAuthError('');
    setAuthSuccess('');
    await wait(500);
    setBusyProvider('');
    setAuthSuccess(`Opening the ${provider.label} sign-in session in the platform browser adapter.`);
    setRedirectLabel('Return to Floppy');
  }

  function continueFromNotice() {
    chooseView(view === 'recovery' ? 'login' : 'account');
  }

  async function saveProfile() {
    setProfileBusy(true);
    setProfileError('');
    setProfileSuccess('');
    await wait(400);
    setProfileBusy(false);
    if (!username.trim()) {
      setProfileError('Enter a username.');
      return;
    }
    setProfileSuccess('Your username has been updated.');
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
    await wait(450);
    setPasswordBusy(false);
    setPasswordSuccess('Your password has been updated.');
    setPasswordValues({ oldPassword: '', newPassword1: '', newPassword2: '' });
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
    await wait(450);
    setAuthenticatorBusy(false);
    setAuthenticatorSetup(false);
    setAuthenticatorSuccess('Authenticator app enabled. Save your recovery codes now.');
    setFreshRecoveryCodes(['H4K2-Q9Z7', 'M8R3-T2V6', 'B6P1-L5N8', 'C3W9-X7D2']);
    setUnusedRecoveryCodes(8);
    setAuthenticatorValues({ currentPassword: '', code: '' });
  }

  async function startAuthenticatorSetup() {
    setAuthenticatorError('');
    setAuthenticatorSuccess('');
    if (!authenticatorValues.currentPassword) {
      setAuthenticatorError('Enter your current password to replace the authenticator.');
      return;
    }
    setAuthenticatorBusy(true);
    await wait(350);
    setAuthenticatorBusy(false);
    setAuthenticatorSetup(true);
    setFreshRecoveryCodes([]);
    setAuthenticatorSuccess('Scan and verify a code from the new authenticator app to finish setup.');
  }

  async function disableAuthenticator() {
    setAuthenticatorError('');
    setAuthenticatorSuccess('');
    if (!authenticatorValues.currentPassword) {
      setAuthenticatorError('Enter your current password to deactivate the authenticator.');
      return;
    }
    setAuthenticatorBusy(true);
    await wait(350);
    setAuthenticatorBusy(false);
    setAuthenticatorSetup(true);
    setFreshRecoveryCodes([]);
    setAuthenticatorSuccess('Authenticator app deactivated.');
  }

  async function regenerateRecoveryCodes() {
    setRecoveryError('');
    setRecoverySuccess('');
    if (!recoveryValues.currentPassword) {
      setRecoveryError('Enter your current password to regenerate recovery codes.');
      return;
    }
    setRecoveryBusy(true);
    await wait(400);
    setRecoveryBusy(false);
    setFreshRecoveryCodes(['H4K2-Q9Z7', 'M8R3-T2V6', 'B6P1-L5N8', 'C3W9-X7D2', 'T5J8-K2M4', 'R7N3-V9P1', 'D2F6-H8L5', 'Y9B4-C7X3']);
    setUnusedRecoveryCodes(8);
    setRecoverySuccess('Recovery codes regenerated. Store them securely now.');
    setRecoveryValues({ currentPassword: '' });
  }

  async function deleteAccount() {
    if (demoAccount) {
      setDeleteError('This section is view-only for demo accounts.');
      return;
    }
    if (lastSuperuser) {
      setDeleteError('Promote another account before deleting this one.');
      return;
    }
    setDeleteBusy(true);
    setDeleteError('');
    await wait(500);
    setDeleteBusy(false);
    setDeleteSuccess(`Demo state: ${username}'s account and data would be deleted, then the session would return to sign in.`);
  }

  function setGuardState(next) {
    setGuard(next);
    setDeleteError('');
    setDeleteSuccess('');
  }

  return <Screen title="Account" subtitle="Authentication and account security" onBack={onBack}>
    <View style={styles.viewRow}>
      {views.map(item => <GuardChip key={item.key} label={item.label} active={view === item.key} onPress={() => chooseView(item.key)} />)}
    </View>

    {view === 'login' || view === 'signup' || view === 'recovery' ? <Section
      title={view === 'login' ? 'Sign in' : view === 'signup' ? 'Create account' : 'Recover password'}
      copy="Authentication uses the server session and CSRF contract. This screen holds demo values only.">
      <AuthEntrance
        mode={view}
        firstRun={view === 'signup'}
        providers={providers}
        values={authValues}
        errors={authErrors}
        error={authError}
        success={authSuccess}
        redirectLabel={redirectLabel}
        busy={authBusy}
        busyProvider={busyProvider}
        palette={authPalette}
        buttonPalette={buttonPalette}
        onChange={updateAuth}
        onSubmit={submitAuth}
        onSwitchMode={chooseView}
        onForgotPassword={() => chooseView('recovery')}
        onProvider={signInWithProvider}
        onContinue={continueFromNotice}
      />
    </Section> : null}

    {view === 'account' ? <Section title="Account security" copy="Signed in as nova. Guard states below are presentation-only; deletion, authenticator and recovery writes stay in the server adapter.">
      <View style={styles.guardRow}>
        <GuardChip label="Regular account" active={guard === 'owner'} onPress={() => setGuardState('owner')} />
        <GuardChip label="Demo account" active={guard === 'demo'} onPress={() => setGuardState('demo')} />
        <GuardChip label="Only superuser" active={guard === 'last'} onPress={() => setGuardState('last')} />
      </View>

      {demoAccount ? <AuthNotice tone="warning" palette={authPalette}>Demo accounts are view-only for authenticator, recovery, profile and deletion changes.</AuthNotice> : null}
      {lastSuperuser ? <AuthNotice tone="warning" palette={authPalette}>You are the only active superuser. Promote another account before deleting this one.</AuthNotice> : null}

      <ProfileCard username={username} error={profileError} success={profileSuccess}
        busy={profileBusy} disabled={demoAccount} palette={authPalette}
        buttonPalette={buttonPalette} onChangeUsername={setUsername} onSave={saveProfile} />

      <AccountTypeCard isSuperuser={lastSuperuser} username={username} palette={authPalette} />

      <PasswordCard values={passwordValues} errors={passwordErrors} error={passwordError}
        success={passwordSuccess} busy={passwordBusy} disabled={demoAccount}
        palette={authPalette} buttonPalette={buttonPalette}
        onChange={(name, value) => {
          setPasswordValues(current => ({ ...current, [name]: value }));
          setPasswordErrors(current => ({ ...current, [name]: undefined }));
        }}
        onSubmit={savePassword} />

      <AuthenticatorCard configured={!authenticatorSetup} setup={authenticatorSetup}
        demo={demoAccount} values={authenticatorValues} error={authenticatorError}
        success={authenticatorSuccess} busy={authenticatorBusy}
        palette={authPalette} buttonPalette={buttonPalette}
        qrSlot={<View style={styles.qrPlaceholder}><Text style={styles.qrLabel}>QR</Text></View>}
        secretSlot={<Text style={[styles.secretHint, { color: palette.textMuted }]}>Manual secret is supplied by the secure setup adapter.</Text>}
        onChange={(name, value) => {
          setAuthenticatorValues(current => ({ ...current, [name]: value }));
          setAuthenticatorError('');
        }}
        onEnable={enableAuthenticator}
        onStartSetup={startAuthenticatorSetup}
        onDisable={disableAuthenticator} />

      <RecoveryCodesCard unusedCount={unusedRecoveryCodes} freshCodes={freshRecoveryCodes}
        values={recoveryValues} error={recoveryError} success={recoverySuccess}
        busy={recoveryBusy} demo={demoAccount} palette={authPalette}
        buttonPalette={buttonPalette}
        onChange={(name, value) => {
          setRecoveryValues(current => ({ ...current, [name]: value }));
          setRecoveryError('');
        }}
        onRegenerate={regenerateRecoveryCodes} />

      <ConnectionsCard providerCount={providers.length} disabled={demoAccount}
        palette={authPalette} buttonPalette={buttonPalette} onManageConnections={() => {}} />

      {deleteSuccess ? <AuthNotice tone="success" palette={authPalette}>{deleteSuccess}</AuthNotice> : null}
      <DeleteAccountCard account={account} error={deleteError} busy={deleteBusy}
        palette={authPalette} buttonPalette={buttonPalette} onDelete={deleteAccount} />
    </Section> : null}
  </Screen>;
}

const styles = StyleSheet.create({
  viewRow: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm },
  guardRow: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm },
  qrPlaceholder: { width: 128, height: 128, alignItems: 'center', justifyContent: 'center' },
  qrLabel: { color: '#18181b', fontSize: 28, fontWeight: '800', letterSpacing: 2 },
  secretHint: { fontSize: 12, lineHeight: 17 },
});
