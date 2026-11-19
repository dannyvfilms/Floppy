import React from 'react';
import { Pressable, Text, View } from 'react-native';
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
  applicationsOnly = false,
  onOpenApplications,
  showCatalogGrants = true,
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
  const accessPage = palette.pageCards === 'access';
  return <View><SettingsPage title={copy.title} copy={copy.copy} palette={palette} heading={heading && !accessPage && !applicationsOnly}>
    {content || <>
    {accessPage && !applicationsOnly ? <>
      <Text role="heading" aria-level={2} style={{ color: palette.text, fontSize: 20, lineHeight: 28, fontWeight: '600' }}>{copy.title}</Text>
      <Text style={{ color: palette.textMuted, fontSize: 14, lineHeight: 20 }}>{copy.copy}</Text>
    </> : null}
    {!applicationsOnly && onOpenApplications ? <Pressable accessibilityRole="link" onPress={onOpenApplications}>
      <Text style={{ color: palette.link, fontSize: 16, lineHeight: 24, textDecorationLine: 'underline' }}>Authorized applications</Text>
    </Pressable> : null}
    {!applicationsOnly ? <>
    <AccessTokenCard {...accountToken} palette={palette} buttonPalette={buttonPalette} />
    <AppTokensCard {...appTokens} palette={palette} buttonPalette={buttonPalette} />
    {showCatalogGrants ? <CatalogGrantsCard {...catalogGrants} palette={palette} buttonPalette={buttonPalette} /> : null}
    </> : null}
    {applicationsOnly || !onOpenApplications ? <AuthorizedApplicationsCard {...applications} palette={palette} buttonPalette={buttonPalette} /> : null}
    </>}
  </SettingsPage></View>;
}
