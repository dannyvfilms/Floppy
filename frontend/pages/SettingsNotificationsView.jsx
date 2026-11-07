import React from 'react';
import { View } from 'react-native';
import {
  ExcludedMediaCard,
  NotificationPreferencesCard,
} from '../settings/NotificationSettings';
import { SettingsPage } from './SettingsView';

export const settingsNotificationsCopy = {
  title: 'Notifications',
  copy: 'Configure how you want to receive notifications about your media.',
};

// Release/premiere/digest preferences, the playback webhook and the excluded
// media list. Stored credentials stay masked in the adapter-supplied model.
export function SettingsNotificationsView({
  preferences = {},
  excluded = {},
  content = null,
  heading = true,
  palette = {},
  buttonPalette = {},
  labels = {},
}) {
  const copy = { ...settingsNotificationsCopy, ...(labels || {}) };
  return <View><SettingsPage title={copy.title} copy={copy.copy} palette={palette} heading={heading}>
    {content || <>
    <NotificationPreferencesCard {...preferences} palette={palette} buttonPalette={buttonPalette} />
    <ExcludedMediaCard {...excluded} palette={palette} buttonPalette={buttonPalette} />
    </>}
  </SettingsPage></View>;
}
