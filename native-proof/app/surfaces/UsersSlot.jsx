import React from 'react';
import { SettingsUsersView } from '../../../frontend/pages/SettingsUsersView';
import SettingsLoadState from './SettingsLoadState';
import { useSettingsPalettes } from './settingsPalettes';
import { useSettingsResource } from './useSettingsResource';

export const surface = {
  id: 'SET-USERS',
  title: 'User accounts',
  where: 'Settings users',
  status: 'in_progress',
  note: 'The account list and page copy load from GET /api/v1/admin/users/; create, activate, promote, password and delete go through the session views that already enforce superuser access, last-superuser and self-protection rules, via /api/v1/admin/users/. A non-superuser gets 403 from the server and the settings navigation hides the entry from the is_superuser field of /api/v1/user/preferences/. Browser and device runtime interaction were not exercised.',
};

export default function UsersSlot() {
  const resource = useSettingsResource(transport => transport.loadUsers());
  const { settingsPalette } = useSettingsPalettes();
  if (resource.state !== 'ready') {
    return <SettingsLoadState state={resource.state} message={resource.message} onRetry={resource.reload} />;
  }
  const { transport } = resource;
  const actions = {
    sessionRequired: !transport.canManageCredentials,
    create: values => transport.createUser(values),
    update: (id, values) => transport.updateUser(id, values),
    setPassword: (id, values) => transport.setUserPassword(id, values),
    remove: id => transport.deleteUser(id),
  };
  return <SettingsUsersView heading={false} users={resource.data.users || []} labels={resource.data.labels || {}}
    palette={{ ...settingsPalette, pageCards: true }} actions={actions} />;
}
