import React from 'react';
import { View } from 'react-native';
import { AccountSecurityView } from './AuthView';
import { SettingsPage } from './SettingsView';

export const settingsAccountCopy = {
  title: 'Account',
  copy: 'Manage your profile, password, recovery and connected accounts.',
};

// Settings > Account. The card stack is the same account-security composition
// used by the native account screen; this page adds the settings heading.
export function SettingsAccountView({
  profile,
  accountType,
  password,
  authenticator,
  recovery,
  connections,
  deletion,
  notices,
  actions,
  labels = {},
  content = null,
  heading = true,
  palette = {},
  buttonPalette = {},
}) {
  const copy = { ...settingsAccountCopy, ...(labels || {}) };
  return <View><SettingsPage title={copy.title} copy={copy.copy} palette={palette} heading={heading}>
    {content || <>
    <AccountSecurityView profile={profile} accountType={accountType} password={password}
      authenticator={authenticator} recovery={recovery} connections={connections}
      deletion={deletion} notices={notices} actions={actions}
      palette={palette} buttonPalette={buttonPalette} />
    </>}
  </SettingsPage></View>;
}
