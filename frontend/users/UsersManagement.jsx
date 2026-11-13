import React, { useMemo, useState } from 'react';
import { Modal, Pressable, StyleSheet, Text, View } from 'react-native';
import { Chip } from '../settings/Chip';
import { Button } from '../ui/Button';
import { SelectField } from '../ui/SelectField';
import { TextField } from '../ui/TextField';

const defaultPalette = {
  text: '#fafafa',
  textSecondary: '#d4d4d8',
  textMuted: '#a1a1aa',
  border: '#52525b',
  background: '#27272a',
  surface: '#27272a',
  surfaceStrong: '#3f3f46',
  surfaceMuted: '#52525b',
  accent: '#6366f1',
  accentStrong: '#4f46e5',
  accentText: '#ffffff',
  danger: '#ef4444',
  success: '#10b981',
  warning: '#f59e0b',
  overlay: 'rgba(0, 0, 0, 0.55)',
  badgeBorder: '#52525b',
  badgeBackground: '#3f3f46',
  badgeText: '#d4d4d8',
  badgeHover: '#52525b',
  radius: 8,
};

const buttonPalette = {
  primary: { background: '#4f46e5', pressed: '#4338ca', hovered: '#4338ca', text: '#ffffff', border: 'transparent' },
  surface: { background: '#3f3f46', pressed: '#52525b', hovered: '#52525b', text: '#fafafa', border: '#3f3f46' },
  'danger-solid': { background: '#dc2626', pressed: '#b91c1c', hovered: '#b91c1c', text: '#ffffff', border: 'transparent' },
  radius: 6,
  focusStyle: {},
};

const defaultLabels = {
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
  active: 'Active',
  inactive: 'Inactive',
  superuser: 'Superuser',
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
  sessionRequired: 'Sign in with your username and password to manage this.',
};

function fill(template, values) {
  return String(template || '').replace(/\{(\w+)\}/g, (match, key) => (
    values[key] === undefined || values[key] === null ? '' : String(values[key])
  ));
}

function Panel({ title, badge, palette, children }) {
  return <View style={[styles.panel, { backgroundColor: palette.surface, borderRadius: palette.radius }]}>
    <View style={styles.panelHeading}>
      <Text role="heading" aria-level={2} style={[styles.panelTitle, { color: palette.text }]}>{title}</Text>
      {badge ?? null}
    </View>
    {children}
  </View>;
}

function roleOptions(labels) {
  return [
    { value: 'all', label: labels.roleAll },
    { value: 'superuser', label: labels.roleSuperuser },
    { value: 'user', label: labels.roleUser },
  ];
}

function statusOptions(labels) {
  return [
    { value: 'all', label: labels.statusAll },
    { value: 'active', label: labels.statusActive },
    { value: 'inactive', label: labels.statusInactive },
  ];
}

function ConfirmDialog({ open, title, copy, confirmLabel, cancelLabel, busy, error, onConfirm, onCancel, palette }) {
  return <Modal transparent visible={open} animationType="fade" accessibilityViewIsModal onRequestClose={onCancel}>
    <View style={[styles.overlay, { backgroundColor: palette.overlay }]}>
      <Pressable accessibilityRole="button" accessibilityLabel={cancelLabel} onPress={onCancel} style={styles.backdrop} />
      <View style={[styles.dialog, { borderColor: palette.border, backgroundColor: palette.surface }]}>
        <Text role="heading" aria-level={2} style={[styles.dialogTitle, { color: palette.text }]}>{title}</Text>
        <Text style={[styles.dialogCopy, { color: palette.textSecondary }]}>{copy}</Text>
        {error ? <Text accessibilityRole="alert" style={[styles.dialogCopy, { color: palette.danger }]}>{error}</Text> : null}
        <View style={styles.dialogActions}>
          <Button label={cancelLabel} tone="surface" disabled={busy} onPress={onCancel} palette={buttonPalette} />
          <Button label={confirmLabel} tone="danger-solid" busy={busy} disabled={busy} onPress={onConfirm} palette={buttonPalette} />
        </View>
      </View>
    </View>
  </Modal>;
}

function PasswordDialog({ open, title, copy, value, label, saveLabel, cancelLabel, busy, error,
  onChange, onSave, onCancel, palette }) {
  return <Modal transparent visible={open} animationType="fade" accessibilityViewIsModal onRequestClose={onCancel}>
    <View style={[styles.overlay, { backgroundColor: palette.overlay }]}>
      <Pressable accessibilityRole="button" accessibilityLabel={cancelLabel} onPress={onCancel} style={styles.backdrop} />
      <View style={[styles.dialog, { borderColor: palette.border, backgroundColor: palette.surface }]}>
        <Text role="heading" aria-level={2} style={[styles.dialogTitle, { color: palette.text }]}>{title}</Text>
        <Text style={[styles.dialogCopy, { color: palette.textSecondary }]}>{copy}</Text>
        <TextField id="managed-user-password" label={label} type="password" value={value}
          onChangeText={onChange} error={error || undefined} autoComplete="new-password" palette={palette} />
        <View style={styles.dialogActions}>
          <Button label={cancelLabel} tone="surface" disabled={busy} onPress={onCancel} palette={buttonPalette} />
          <Button label={saveLabel} busy={busy} disabled={busy || !value} onPress={onSave} palette={buttonPalette} />
        </View>
      </View>
    </View>
  </Modal>;
}

function UserRow({ member, labels, palette, busy, sessionRequired, onToggle, onPassword, onDelete }) {
  const rowBusy = busy.startsWith(`${member.id}:`);
  return <View style={[styles.row, { backgroundColor: palette.surfaceStrong, borderRadius: palette.radius }]}>
    <View style={styles.rowTop}>
      <View style={styles.identity}>
        <Text style={[styles.username, { color: palette.text }]}>{member.username}</Text>
        {member.email ? <Text style={[styles.meta, { color: palette.textMuted }]}>{member.email}</Text> : null}
      </View>
      <View style={styles.badges}>
        {member.isSuperuser ? <Chip label={labels.superuser} palette={palette} /> : null}
        {!member.isActive ? <Chip label={labels.inactive} palette={palette} /> : null}
        {member.isSelf ? <Chip label={labels.thisIsYou} palette={palette} /> : null}
      </View>
    </View>
    <View style={styles.metaRows}>
      <Text style={[styles.meta, { color: palette.textMuted }]}>
        {labels.joined}: {member.dateJoined || labels.never}
      </Text>
      <Text style={[styles.meta, { color: palette.textMuted }]}>
        {labels.lastLogin}: {member.lastLogin || labels.never}
      </Text>
    </View>
    <View style={styles.actions}>
      <Button label={member.isActive ? labels.deactivate : labels.activate}
        tone="surface" disabled={sessionRequired || rowBusy || member.isSelf}
        onPress={() => onToggle(member, 'isActive')} palette={buttonPalette} />
      <Button label={member.isSuperuser ? labels.removeSuperuser : labels.makeSuperuser}
        tone="surface" disabled={sessionRequired || rowBusy || member.isSelf}
        onPress={() => onToggle(member, 'isSuperuser')} palette={buttonPalette} />
      <Button label={labels.resetPassword} tone="surface" disabled={sessionRequired || rowBusy}
        onPress={() => onPassword(member)} palette={buttonPalette} />
      <Button label={labels.deleteUser} tone="danger-solid" disabled={rowBusy || !member.canDelete}
        onPress={() => onDelete(member)} palette={buttonPalette} />
    </View>
    {rowBusy ? <Text accessibilityLiveRegion="polite" style={[styles.meta, { color: palette.textMuted }]}>{'…'}</Text> : null}
  </View>;
}

export function UsersManagement({ initialUsers = [], labels: suppliedLabels = {},
  palette: suppliedPalette = {}, actions = {} }) {
  const labels = useMemo(() => ({ ...defaultLabels, ...suppliedLabels }), [suppliedLabels]);
  const sessionRequired = Boolean(actions.sessionRequired);
  const palette = useMemo(() => ({ ...defaultPalette, ...suppliedPalette }), [suppliedPalette]);
  const [rows, setRows] = useState(initialUsers);
  const [query, setQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState('all');
  const [roleFilter, setRoleFilter] = useState('all');
  const [draft, setDraft] = useState({ username: '', email: '', password: '' });
  const [busy, setBusy] = useState('');
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');
  const [deleteTarget, setDeleteTarget] = useState(null);
  const [passwordTarget, setPasswordTarget] = useState(null);
  const [passwordValue, setPasswordValue] = useState('');
  const [passwordError, setPasswordError] = useState('');

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return rows.filter(member => {
      if (needle) {
        const haystack = `${member.username} ${member.email || ''}`.toLowerCase();
        if (!haystack.includes(needle)) return false;
      }
      if (statusFilter === 'active' && !member.isActive) return false;
      if (statusFilter === 'inactive' && member.isActive) return false;
      if (roleFilter === 'superuser' && !member.isSuperuser) return false;
      if (roleFilter === 'user' && member.isSuperuser) return false;
      return true;
    });
  }, [rows, query, statusFilter, roleFilter]);

  async function run(key, action, apply) {
    setBusy(key);
    setError('');
    setNotice('');
    try {
      const result = await action();
      apply(result || {});
    } catch (caught) {
      setError(caught && caught.message ? caught.message : labels.error);
    } finally {
      setBusy('');
    }
  }

  function replaceMember(updated) {
    setRows(current => current.map(member => (
      member.id === updated.id ? updated : member
    )));
  }

  function toggle(member, field) {
    run(`${member.id}:${field}`, () => actions.update(member.id, { [field]: !member[field] }), result => {
      if (result.user) replaceMember(result.user);
    });
  }

  function createUser() {
    run('create', () => actions.create(draft), result => {
      if (result.user) setRows(current => [...current, result.user]);
      setDraft({ username: '', email: '', password: '' });
      setNotice(labels.createdStatus);
    });
  }

  function openPassword(member) {
    setPasswordTarget(member);
    setPasswordValue('');
    setPasswordError('');
    setError('');
  }

  function savePassword() {
    if (!passwordTarget) return;
    run(`${passwordTarget.id}:password`, () => actions.setPassword(passwordTarget.id, { password: passwordValue }), () => {
      setPasswordTarget(null);
      setPasswordValue('');
      setPasswordError('');
      setNotice(labels.passwordStatus);
    });
  }

  function openDelete(member) {
    setDeleteTarget(member);
    setError('');
  }

  function confirmDelete() {
    if (!deleteTarget) return;
    const target = deleteTarget;
    run(`${target.id}:delete`, () => actions.remove(target.id), () => {
      setRows(current => current.filter(member => member.id !== target.id));
      setDeleteTarget(null);
      setNotice(labels.deleteStatus);
    });
  }

  function updateDraft(field, value) {
    setDraft(current => ({ ...current, [field]: value }));
  }

  const statusMessage = error ? <Text accessibilityRole="alert" style={[styles.message, { color: palette.danger }]}>{error}</Text>
    : notice ? <Text accessibilityLiveRegion="polite" style={[styles.message, { color: palette.success }]}>{notice}</Text> : null;

  return <View style={styles.page}>
    {statusMessage}
    <Panel title={labels.createTitle} palette={palette}>
      {sessionRequired ? <Text style={[styles.copy, { color: palette.textMuted }]}>{labels.sessionRequired}</Text> : <>
      <Text style={[styles.copy, { color: palette.textMuted }]}>{labels.createCopy}</Text>
      <View style={styles.filters}>
        <View style={styles.field}>
          <TextField id="managed-user-username" label={labels.username} value={draft.username}
            onChangeText={value => updateDraft('username', value)} autoComplete="off" palette={palette} />
        </View>
        <View style={styles.field}>
          <TextField id="managed-user-email" label={labels.email} type="email" value={draft.email}
            onChangeText={value => updateDraft('email', value)} autoComplete="off" palette={palette} />
        </View>
      </View>
      <View style={styles.passwordField}>
        <TextField id="managed-user-initial-password" label={labels.password} type="password"
          help={labels.passwordHelp} value={draft.password}
          onChangeText={value => updateDraft('password', value)} autoComplete="new-password" palette={palette} />
      </View>
      <View style={styles.createAction}>
        <Button label={labels.createAction} busy={busy === 'create'} disabled={busy === 'create'}
          onPress={createUser} palette={buttonPalette} />
      </View>
      </>}
    </Panel>

    <Panel title={labels.overviewTitle} palette={palette}
      badge={<Chip label={String(rows.length)} palette={palette}
        accessibilityLabel={`${labels.accounts}: ${rows.length}`} />}>
      <Text style={[styles.copy, { color: palette.textMuted }]}>{labels.overviewCopy}</Text>
      <View style={styles.filters}>
        <View style={styles.searchField}>
          <TextField id="managed-users-search" label={labels.search} value={query}
            onChangeText={setQuery} palette={palette} />
        </View>
        <View style={styles.filterField}>
          <SelectField label={labels.statusFilter} name="status" value={statusFilter}
            iconChevron={Boolean(palette.pageCards)}
            options={statusOptions(labels)} onChange={event => setStatusFilter(event.target.value)}
            palette={palette} />
        </View>
        <View style={styles.filterField}>
          <SelectField label={labels.roleFilter} name="role" value={roleFilter}
            iconChevron={Boolean(palette.pageCards)}
            options={roleOptions(labels)} onChange={event => setRoleFilter(event.target.value)}
            palette={palette} />
        </View>
      </View>
      {filtered.length ? filtered.map(member => <UserRow key={member.id} member={member}
        labels={labels} palette={palette} busy={busy} sessionRequired={sessionRequired}
        onToggle={toggle} onPassword={openPassword} onDelete={openDelete} />)
        : <Text style={[styles.copy, { color: palette.textMuted }]}>{rows.length ? labels.empty : labels.noUsers}</Text>}
    </Panel>

    <ConfirmDialog open={Boolean(deleteTarget)} title={labels.deleteTitle}
      copy={fill(labels.deleteCopy, { username: deleteTarget ? deleteTarget.username : '' })}
      confirmLabel={labels.confirmDelete} cancelLabel={labels.cancel}
      busy={busy === `${deleteTarget && deleteTarget.id}:delete`}
      error={deleteTarget ? error : ''}
      onConfirm={confirmDelete} onCancel={() => setDeleteTarget(null)} palette={palette} />

    <PasswordDialog open={Boolean(passwordTarget)} title={labels.passwordTitle}
      copy={fill(labels.passwordCopy, { username: passwordTarget ? passwordTarget.username : '' })}
      value={passwordValue} label={labels.newPassword} saveLabel={labels.savePassword}
      cancelLabel={labels.cancel}
      error={passwordError || (passwordTarget ? error : '')}
      busy={busy === `${passwordTarget && passwordTarget.id}:password`}
      onChange={value => { setPasswordValue(value); setPasswordError(''); }}
      onSave={savePassword} onCancel={() => setPasswordTarget(null)} palette={palette} />
  </View>;
}

const styles = StyleSheet.create({
  page: { gap: 24 },
  panel: { padding: 24, gap: 0, minWidth: 0 },
  panelHeading: { flexDirection: 'row', alignItems: 'flex-start', justifyContent: 'space-between', gap: 12, marginBottom: 8 },
  panelTitle: { flexShrink: 1, fontSize: 20, lineHeight: 28, fontWeight: '600' },
  copy: { fontSize: 14, lineHeight: 20 },
  message: { fontSize: 13, lineHeight: 19 },
  filters: { flexDirection: 'row', flexWrap: 'wrap', gap: 12, marginTop: 16 },
  searchField: { flexGrow: 1, flexShrink: 1, minWidth: 220 },
  filterField: { width: 190 },
  field: { flexGrow: 1, flexShrink: 1, minWidth: 220 },
  row: { padding: 16, gap: 8, marginTop: 12 },
  rowTop: { flexDirection: 'row', alignItems: 'flex-start', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' },
  identity: { flexShrink: 1, gap: 2, minWidth: 160 },
  username: { fontSize: 16, lineHeight: 24, fontWeight: '600' },
  meta: { fontSize: 12, lineHeight: 17 },
  metaRows: { gap: 2 },
  badges: { flexDirection: 'row', flexWrap: 'wrap', gap: 6 },
  actions: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  passwordField: { marginTop: 16 },
  createAction: { alignSelf: 'flex-start', marginTop: 16 },
  overlay: { flex: 1, justifyContent: 'center', padding: 16 },
  backdrop: { ...StyleSheet.absoluteFillObject, backgroundColor: 'rgba(0, 0, 0, 0.55)' },
  dialog: { gap: 12, borderWidth: 1, borderRadius: 12, padding: 16 },
  dialogTitle: { fontSize: 16, fontWeight: '600' },
  dialogCopy: { fontSize: 13, lineHeight: 19 },
  dialogActions: { flexDirection: 'row', justifyContent: 'flex-end', gap: 8, flexWrap: 'wrap' },
});
