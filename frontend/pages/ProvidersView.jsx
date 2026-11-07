import React from 'react';
import { View } from 'react-native';
import { ProviderActivityView } from '../providers/ProviderActivityView';
import { ProviderDirectoryView } from '../providers/ProviderDirectoryView';
import { SettingsPage } from './SettingsView';

export const providersCopy = {
  title: 'Providers',
  copy: 'Find services and their available settings.',
};

export const providerActivityCopy = {
  title: 'Activity',
  copy: 'Import and sync activity across your providers.',
};

// Provider directory page. The shared directory owns filters, rows and empty
// states; the adapter supplies the server catalog and navigation.
export function ProvidersView({
  directory = {},
  content = null,
  heading = true,
  palette = {},
  buttonPalette = {},
  labels = {},
}) {
  const copy = { ...providersCopy, ...(labels || {}) };
  return <View><SettingsPage title={copy.title} copy={copy.copy} palette={palette} heading={heading}>
    {content || <>
    <ProviderDirectoryView {...directory} labels={labels} palette={palette} buttonPalette={buttonPalette} />
    </>}
  </SettingsPage></View>;
}

// Provider activity page. The AniList activity contract is shared today; other
// providers still return their activity from server-rendered templates.
export function ProviderActivityPage({
  activity = {},
  content = null,
  heading = true,
  palette = {},
  buttonPalette = {},
  labels = {},
}) {
  const copy = { ...providerActivityCopy, ...(labels || {}) };
  return <View><SettingsPage title={copy.title} copy={copy.copy} palette={palette} heading={heading}>
    {content || <>
    <ProviderActivityView {...activity} labels={labels} palette={palette} buttonPalette={buttonPalette} />
    </>}
  </SettingsPage></View>;
}
