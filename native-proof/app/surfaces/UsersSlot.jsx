import React, { useState } from 'react';
import { UsersManagement } from '../../../frontend/users/UsersManagement';
import { palette } from '../theme';

export const surface = {
  id: 'SET-USERS',
  title: 'User accounts',
  where: 'Settings users',
  status: 'in_progress',
  note: 'Superuser account list, search, role and active-state changes, account creation, password replacement and confirmed deletion. Demo data only; the native client still needs authenticated transport.',
};

const labels = {
  accounts: 'Accounts',
  overviewTitle: 'User accounts',
  overviewCopy: 'Manage the accounts on this Floppy instance.',
  search: 'Search users',
  statusFilter: 'Status',
  statusAll: 'All statuses',
  statusActive: 'Active',
  statusInactive: 'Inactive',
  roleFilter: 'Role',
  roleAll: 'All roles',
  roleSuperuser: 'Superuser',
  roleUser: 'User',
  createTitle: 'Add a user',
  createCopy: 'Create an account for someone else on this instance.',
  username: 'Username',
  email: 'Email',
  password: 'Password',
  passwordHelp: 'Optional. The person can set their own password later.',
  createAction: 'Create user',
  createdStatus: 'User created.',
  empty: 'No users match these filters.',
  noUsers: 'No users have been created yet.',
  never: 'Never',
  joined: 'Joined',
  lastLogin: 'Last login',
  superuser: 'Superuser',
  inactive: 'Inactive',
  thisIsYou: 'This is you',
  activate: 'Activate',
  deactivate: 'Deactivate',
  makeSuperuser: 'Make superuser',
  removeSuperuser: 'Remove superuser',
  resetPassword: 'Set password',
  deleteUser: 'Delete',
  deleteTitle: 'Delete user?',
  deleteCopy: 'This permanently deletes {username} and all of their tracked media, history, ratings, lists and settings. This cannot be undone.',
  cancel: 'Cancel',
  confirmDelete: 'Delete user',
  deleteStatus: 'User deleted.',
  passwordTitle: 'Set a new password',
  passwordCopy: 'Set a new password for {username}. Share it with them securely; they should change it after signing in.',
  newPassword: 'New password',
  savePassword: 'Save password',
  passwordStatus: 'Password updated.',
  error: 'Something went wrong. Try again.',
  close: 'Close',
};

const demoUsers = [
  {
    id: 1, username: 'owner', email: 'owner@example.com', dateJoined: 'Jan 4, 2025',
    lastLogin: 'Nov 4, 2026', isActive: true, isSuperuser: true,
    isSelf: true, canDelete: false,
  },
  {
    id: 2, username: 'household', email: 'home@example.com', dateJoined: 'Feb 18, 2025',
    lastLogin: 'Nov 2, 2026', isActive: true, isSuperuser: false,
    isSelf: false, canDelete: true,
  },
  {
    id: 3, username: 'guest', email: '', dateJoined: 'Jun 9, 2025',
    lastLogin: '', isActive: false, isSuperuser: false,
    isSelf: false, canDelete: true,
  },
];

const settingsPalette = {
  text: palette.text,
  textSecondary: palette.textSecondary,
  textMuted: palette.textMuted,
  border: palette.border,
  background: palette.surface,
  surface: palette.surface,
  surfaceStrong: palette.surfaceStrong,
  surfaceMuted: palette.surfaceMuted,
  accent: palette.accent,
  accentStrong: palette.accentStrong,
  accentText: '#ffffff',
  danger: palette.danger,
  success: palette.success,
  warning: palette.warning,
  overlay: 'rgba(0, 0, 0, 0.55)',
  badgeBorder: palette.surfaceMuted,
  badgeBackground: palette.surfaceStrong,
  badgeText: palette.textSecondary,
  badgeHover: palette.surfaceMuted,
  focusStyle: {},
};

export default function UsersSlot() {
  const [seed] = useState(demoUsers);
  const actions = {
    create: async values => ({
      user: {
        id: 100, username: values.username || 'new-user', email: values.email || '',
        dateJoined: 'Today', lastLogin: '', isActive: true,
        isSuperuser: false, isSelf: false, canDelete: true,
      },
    }),
    update: async (id, values) => ({
      user: { ...seed.find(member => member.id === id), ...values },
    }),
    setPassword: async () => ({ message: 'Password updated.' }),
    remove: async id => ({ deleted: id }),
  };
  return <UsersManagement initialUsers={seed} labels={labels}
    palette={settingsPalette} actions={actions} />;
}
