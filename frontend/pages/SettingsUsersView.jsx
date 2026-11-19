import React from 'react';
import { View } from 'react-native';
import { UsersManagement } from '../users/UsersManagement';
import { SettingsPage } from './SettingsView';

export const settingsUsersCopy = {
  title: 'Users',
  copy: '',
};

// Superuser-only account management. The adapter supplies server rows, labels
// and the authenticated create/update/password/delete actions.
export function SettingsUsersView({
  users = [],
  labels = {},
  palette = {},
  actions = {},
  content = null,
  heading = true,
}) {
  const copy = { ...settingsUsersCopy, ...(labels || {}) };
  return <View><SettingsPage title={copy.title} copy={copy.copy} palette={palette} heading={heading}>
    {content || <>
    <UsersManagement initialUsers={users} labels={labels} palette={palette} actions={actions} />
    </>}
  </SettingsPage></View>;
}
