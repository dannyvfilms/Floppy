import React from 'react';
import { View } from 'react-native';
import {
  ExportHistoryCard,
  ExportScheduleCard,
  RestoreBackupCard,
  RssFeedCard,
  ScheduledExportsCard,
} from '../settings/DataSettings';
import { SettingsPage } from './SettingsView';

export const settingsDataCopy = {
  title: 'Data Management',
  copy: 'Export, restore and publish your library data.',
};

// Export schedule, scheduled exports, history, restore and RSS feed builder in
// the order used by the server data-management page.
export function SettingsDataView({
  schedule = {},
  scheduled = {},
  history = {},
  restore = {},
  rss = {},
  content = null,
  heading = true,
  palette = {},
  buttonPalette = {},
  labels = {},
}) {
  const copy = { ...settingsDataCopy, ...(labels || {}) };
  return <View><SettingsPage title={copy.title} copy={copy.copy} palette={palette} heading={heading}>
    {content || <>
    <ExportScheduleCard {...schedule} palette={palette} buttonPalette={buttonPalette} />
    <ScheduledExportsCard {...scheduled} palette={palette} buttonPalette={buttonPalette} />
    <ExportHistoryCard {...history} palette={palette} />
    <RestoreBackupCard {...restore} palette={palette} buttonPalette={buttonPalette} />
    <RssFeedCard {...rss} palette={palette} buttonPalette={buttonPalette} />
    </>}
  </SettingsPage></View>;
}
