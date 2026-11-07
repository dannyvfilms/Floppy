import React from 'react';
import { View } from 'react-native';
import {
  AccessTokenCard,
  AppTokensCard,
  AuthorizedApplicationsCard,
  CatalogGrantsCard,
} from '../settings/AccessSettings';
import { SettingsPage } from './SettingsView';

export const settingsAccessCopy = {
  title: 'Access & Tokens',
  copy: 'Manage credentials and applications allowed to access your Floppy account.',
};

// Account token, application tokens, install credentials and OAuth grants.
// Minted secrets never enter the model; only masked previews and copy intents.
export function SettingsAccessView({
  accountToken = {},
  appTokens = {},
  catalogGrants = {},
  applications = {},
  content = null,
  heading = true,
  palette = {},
  buttonPalette = {},
  labels = {},
}) {
  const copy = { ...settingsAccessCopy, ...(labels || {}) };
  return <View><SettingsPage title={copy.title} copy={copy.copy} palette={palette} heading={heading}>
    {content || <>
    <AccessTokenCard {...accountToken} palette={palette} buttonPalette={buttonPalette} />
    <AppTokensCard {...appTokens} palette={palette} buttonPalette={buttonPalette} />
    <CatalogGrantsCard {...catalogGrants} palette={palette} buttonPalette={buttonPalette} />
    <AuthorizedApplicationsCard {...applications} palette={palette} buttonPalette={buttonPalette} />
    </>}
  </SettingsPage></View>;
}
