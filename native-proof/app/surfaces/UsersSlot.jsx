import React, { useRef } from 'react';
import { UsersManagement } from '../../../frontend/users/UsersManagement';
import { palette } from '../theme';

export const surface = {
  id: 'SET-USERS',
  title: 'User accounts',
  where: 'Settings users',
  status: 'ported',
  note: 'Superuser account list, search, status and role filters, account creation, activate/deactivate, promote/demote, password replacement and confirmed deletion render from the shared React Native user-management component with realistic demo users, permission guards, validation errors and busy/success state. Authenticated transport, CSRF and iOS/Android runtime verification remain unverified.',
};

const labels = {
  accounts: 'Accounts',
  overviewTitle: 'User accounts',
  overviewCopy: 'Manage the accounts on this Floppy instance. Only superusers can see this page.',
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
  createCopy: 'Create an account for someone else on this instance. Leave the password blank to create the account without one.',
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
    id: 1, username: 'owner', email: 'owner@example.com',
    dateJoined: 'Jan. 4, 2025, 9:41 a.m.', lastLogin: 'Nov. 4, 2026, 8:12 p.m.',
    isActive: true, isSuperuser: true, isSelf: true, canDelete: false,
  },
  {
    id: 2, username: 'archivist', email: 'archive@example.com',
    dateJoined: 'Feb. 18, 2025, 2:05 p.m.', lastLogin: 'Nov. 3, 2026, 10:26 a.m.',
    isActive: true, isSuperuser: true, isSelf: false, canDelete: true,
  },
  {
    id: 3, username: 'household', email: 'home@example.com',
    dateJoined: 'Jun. 9, 2025, 7:30 p.m.', lastLogin: 'Nov. 2, 2026, 6:03 p.m.',
    isActive: true, isSuperuser: false, isSelf: false, canDelete: true,
  },
  {
    id: 4, username: 'guest', email: '',
    dateJoined: 'Sep. 27, 2025, 11:18 a.m.', lastLogin: '',
    isActive: false, isSuperuser: false, isSelf: false, canDelete: true,
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

const usernamePattern = /^[\w.@+-]+$/;
const emailPattern = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const shortPassword = 'This password is too short. It must contain at least 8 characters.';

function wait(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

function isLastActiveSuperuser(member, members) {
  return member.isSuperuser && member.isActive
    && members.filter(other => other.isSuperuser && other.isActive).length === 1;
}

function withPermissions(members) {
  return members.map(member => ({
    ...member,
    canDelete: !member.isSelf && !isLastActiveSuperuser(member, members),
  }));
}

export default function UsersSlot() {
  const membersRef = useRef(withPermissions(demoUsers.map(member => ({ ...member }))));
  const nextIdRef = useRef(Math.max(...demoUsers.map(member => member.id)) + 1);

  function currentMembers() {
    return membersRef.current;
  }

  function findMember(id) {
    return currentMembers().find(member => member.id === id);
  }

  function apply(mutate) {
    membersRef.current = withPermissions(mutate(currentMembers().map(member => ({ ...member }))));
    return membersRef.current;
  }

  const actions = {
    create: async values => {
      await wait(450);
      const username = String(values.username || '').trim();
      const email = String(values.email || '').trim();
      const password = String(values.password || '');
      if (!username) throw new Error('Enter a username.');
      if (username.length > 150) throw new Error('That username is too long.');
      if (!usernamePattern.test(username)) {
        throw new Error('Usernames can only contain letters, numbers and @/./+/-/_ characters.');
      }
      if (currentMembers().some(member => member.username.toLowerCase() === username.toLowerCase())) {
        throw new Error('An account with that username already exists.');
      }
      if (email && !emailPattern.test(email)) throw new Error('Enter a valid email address.');
      if (password && password.length < 8) throw new Error(shortPassword);
      if (password && /^\d+$/.test(password)) throw new Error('This password is entirely numeric.');
      const id = nextIdRef.current++;
      const created = {
        id, username, email, dateJoined: 'Just now', lastLogin: '',
        isActive: true, isSuperuser: false, isSelf: false, canDelete: true,
      };
      apply(members => [...members, created]);
      return { user: findMember(id) };
    },
    update: async (id, values) => {
      await wait(350);
      const member = findMember(id);
      if (!member) throw new Error('That account no longer exists.');
      const updates = {};
      if ('isActive' in values) updates.isActive = Boolean(values.isActive);
      if ('isSuperuser' in values) updates.isSuperuser = Boolean(values.isSuperuser);
      if (!Object.keys(updates).length) throw new Error('Nothing to update.');
      if (member.isSelf && updates.isActive === false) {
        throw new Error('You cannot deactivate your own account.');
      }
      if (member.isSelf && updates.isSuperuser === false) {
        throw new Error('You cannot remove your own superuser access.');
      }
      if (isLastActiveSuperuser(member, currentMembers())
        && (updates.isActive === false || updates.isSuperuser === false)) {
        throw new Error('Promote another account before changing the last superuser.');
      }
      apply(members => members.map(other => (other.id === id ? { ...other, ...updates } : other)));
      return { user: findMember(id) };
    },
    setPassword: async (id, values) => {
      await wait(450);
      const member = findMember(id);
      if (!member) throw new Error('That account no longer exists.');
      const password = String(values.password || '');
      if (!password) throw new Error('Enter a new password.');
      if (password.length < 8) throw new Error(shortPassword);
      if (/^\d+$/.test(password)) throw new Error('This password is entirely numeric.');
      return { message: 'Password updated.' };
    },
    remove: async id => {
      await wait(500);
      const member = findMember(id);
      if (!member) throw new Error('That account no longer exists.');
      if (member.isSelf) throw new Error('You cannot delete your own account.');
      if (isLastActiveSuperuser(member, currentMembers())) {
        throw new Error('Promote another account before deleting the last superuser.');
      }
      apply(members => members.filter(other => other.id !== id));
      return { deleted: id };
    },
  };

  return <UsersManagement initialUsers={currentMembers()} labels={labels}
    palette={settingsPalette} actions={actions} />;
}
