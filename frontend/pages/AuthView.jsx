import React from 'react';
import { StyleSheet, Text, View } from 'react-native';
import {
  AccountTypeCard,
  AuthenticatorCard,
  ConnectionsCard,
  DeleteAccountCard,
  PasswordCard,
  ProfileCard,
  RecoveryCodesCard,
} from '../auth/AccountSecurity';
import { AuthEntrance } from '../auth/AuthEntrance';

const authModes = {
  login: {
    title: 'Sign in',
    copy: 'Credentials go straight to your Floppy server. This device keeps only the server session in secure storage.',
  },
  signup: {
    title: 'Create account',
    copy: 'Create an account on this Floppy server. Your tracking data stays on the server.',
  },
  recovery: {
    title: 'Recover password',
    copy: 'Enter your username to start password recovery for this server.',
  },
};

// Login/signup/recovery page composition. The entrance form, social options,
// notices and mode switching are shared; the adapter supplies server state,
// values, errors and redirect intents.
export function AuthView({
  mode = 'login',
  title,
  copy,
  notice = null,
  footer = null,
  labels = {},
  palette = {},
  buttonPalette = {},
  entrance = {},
}) {
  const defaults = authModes[mode] || authModes.login;
  return <View style={styles.page}>
    <View style={styles.heading}>
      <Text role="heading" aria-level={2} style={[styles.title, { color: palette.text || '#fafafa' }]}>{title || defaults.title}</Text>
      <Text style={[styles.copy, { color: palette.textMuted || '#a1a1aa' }]}>{copy || defaults.copy}</Text>
    </View>
    {notice}
    <AuthEntrance mode={mode} labels={labels} palette={palette}
      buttonPalette={buttonPalette} {...entrance} />
    {footer}
  </View>;
}

// Account-security page content shared by Settings > Account and the native
// account screen. Card order follows users/account.html.
export function AccountSecurityView({
  profile = {},
  accountType = {},
  password = {},
  authenticator = {},
  recovery = {},
  connections = {},
  deletion = {},
  notices = null,
  actions = null,
  palette = {},
  buttonPalette = {},
}) {
  return <View style={styles.cards}>
    {notices}
    {actions}
    <ProfileCard {...profile} palette={palette} buttonPalette={buttonPalette} />
    <AccountTypeCard {...accountType} palette={palette} buttonPalette={buttonPalette} />
    <PasswordCard {...password} palette={palette} buttonPalette={buttonPalette} />
    <AuthenticatorCard {...authenticator} palette={palette} buttonPalette={buttonPalette} />
    <RecoveryCodesCard {...recovery} palette={palette} buttonPalette={buttonPalette} />
    <ConnectionsCard {...connections} palette={palette} buttonPalette={buttonPalette} />
    <DeleteAccountCard {...deletion} palette={palette} buttonPalette={buttonPalette} />
  </View>;
}

const styles = StyleSheet.create({
  page: { gap: 16, minWidth: 0 },
  heading: { gap: 6 },
  title: { fontSize: 22, fontWeight: '600', lineHeight: 28 },
  copy: { fontSize: 13, lineHeight: 19 },
  cards: { gap: 16, minWidth: 0 },
});
