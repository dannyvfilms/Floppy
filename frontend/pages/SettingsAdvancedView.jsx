import React from 'react';
import { View } from 'react-native';
import {
  CacheManagementCard,
  ImageCacheCard,
  LogsCard,
  ServerPortCard,
} from '../settings/AdvancedSettings';
import { SettingsPage } from './SettingsView';

export const settingsAdvancedCopy = {
  title: 'Advanced',
  copy: '',
};

// Advanced administration cards in the server page order. Permission-gated
// actions receive their isSuperuser/canManage flags from the adapter.
export function SettingsAdvancedView({
  logs = {},
  imageCache = {},
  cacheManagement = {},
  serverPort = {},
  content = null,
  heading = true,
  palette = {},
  buttonPalette = {},
  labels = {},
  icons = {},
}) {
  const copy = { ...settingsAdvancedCopy, ...(labels || {}) };
  return <View><SettingsPage title={copy.title} copy={copy.copy} palette={palette} heading={heading}>
    {content || <>
    <LogsCard {...logs} palette={palette} buttonPalette={buttonPalette} labels={labels.logs || labels} icons={icons} />
    <ImageCacheCard {...imageCache} palette={palette} buttonPalette={buttonPalette} labels={labels.imageCache || labels} icons={icons} />
    <CacheManagementCard {...cacheManagement} palette={palette} buttonPalette={buttonPalette} labels={labels.cache || labels} icons={icons} />
    <ServerPortCard {...serverPort} palette={palette} buttonPalette={buttonPalette} labels={labels.serverPort || labels} icons={icons} />
    </>}
  </SettingsPage></View>;
}
