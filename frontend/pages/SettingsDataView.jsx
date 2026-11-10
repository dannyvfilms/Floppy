import React from 'react';
import { Pressable, Text, View } from 'react-native';
import {
  ExportHistoryCard,
  ExportOtherSitesCard,
  ExportScheduleCard,
  ImportSettingsCard,
  LibraryMaintenanceCard,
  RestoreBackupCard,
  RssFeedCard,
  ScheduledExportsCard,
} from '../settings/DataSettings';
import { SettingsPage } from './SettingsView';

export const settingsDataCopy = {
  title: 'Data Management',
  copy: '',
};

// Export schedule, scheduled exports, history, restore and RSS feed builder in
// the order used by the server data-management page.
export function SettingsDataView({
  schedule = {},
  sites = null,
  importSettings = null,
  scheduled = {},
  history = {},
  restore = {},
  rss = {},
  onOpenRss,
  onDownloadTemplate,
  maintenance = null,
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
    {sites ? <ExportOtherSitesCard {...sites} palette={palette} buttonPalette={buttonPalette} /> : null}
    <ScheduledExportsCard {...scheduled} palette={palette} buttonPalette={buttonPalette} />
    <ExportHistoryCard {...history} palette={palette} />
    <RestoreBackupCard {...restore} palette={palette} buttonPalette={buttonPalette} />
    {importSettings ? <ImportSettingsCard {...importSettings} palette={palette} /> : null}
    {onOpenRss ? <Pressable accessibilityRole="link" onPress={onOpenRss}>
      <Text style={{ color: palette.link, fontSize: 16, lineHeight: 24, textDecorationLine: 'underline' }}>RSS feeds</Text>
    </Pressable> : <RssFeedCard {...rss} palette={palette} buttonPalette={buttonPalette} />}
    {onDownloadTemplate ? <Pressable accessibilityRole="link" onPress={onDownloadTemplate}>
      <Text style={{ color: palette.link, fontSize: 16, lineHeight: 24, textDecorationLine: 'underline' }}>Download an import template</Text>
    </Pressable> : null}
    {maintenance ? <LibraryMaintenanceCard {...maintenance} palette={palette} buttonPalette={buttonPalette} /> : null}
    </>}
  </SettingsPage></View>;
}
