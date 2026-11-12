import React, { useEffect, useMemo, useState } from 'react';
import { Linking, Modal, Pressable, StyleSheet, TextInput, Text, View } from 'react-native';
import { Icon, SearchIcon } from '../../../frontend/ui/Icon';
import { Screen } from '../components/Screen';
import { getActiveAuthSession } from '../data/authSession';
import { createListTransport } from '../data/listTransport';
import { LIST_SORT_OPTIONS, LIST_TYPE_OPTIONS, listSummaryFromPayload, listsFromPayload, memberUsernames } from '../data/listTransportCore';
import { ListsPageView } from '../../../frontend/pages/ListsPageView';
import { Button } from '../../../frontend/ui/Button';
import { actionIcons } from '../../../frontend/ui/actionIcons';
import { SelectField } from '../../../frontend/ui/SelectField';
import { settingsNavIcons } from '../settingsNavIcons';
import { ListForm } from '../../../frontend/ui/ListFormView';
import { ListImportDialog } from '../components/ListImportDialog';
import { palette, radius, spacing } from '../theme';

export const surface = {
  id: 'LISTS',
  status: 'ported',
  title: 'Lists hub on real data',
  where: 'Lists screen: heading, actions, search and sort controls, list card grid, create and edit form',
  note: 'The hub renders the shared ListsPageView composition and loads every page of GET /api/v1/lists/ through listTransport with the server search and sort query params the web toolbar posts. Create maps POST /api/v1/lists/ (including smart lists, tags and the public-notes flag) and edit maps PATCH /api/v1/lists/{id}/; collaborators and viewers are added by username through PUT .../collaborators/ and .../viewers/. A new smart list opens its rule editor. Delete maps DELETE with the form confirm step. The list serializer now carries is_smart, tags and include_notes. Trakt (device-code flow), MDBList and CSV imports run through the JSON endpoints under /api/v1/lists/import/ (the CSV text is read on the device), and the hub filters by media type through the media_type query param of the lists endpoint, like the All Types control on the web. Public profile opens the server user page through the platform browser.',
};

const SIGNED_OUT_ERROR = {
  title: 'Sign in to see your lists',
  body: 'Connect your Floppy server to load your lists.',
  retryLabel: 'Sign In',
};

const RESERVED_SLUGS = ['create', 'edit', 'delete'];

function normalizeSlug(value) {
  return String(value || '')
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9_-]+/g, '-')
    .replace(/-{2,}/g, '-')
    .replace(/^-+|-+$/g, '');
}

function serverUrlPrefix() {
  const serverUrl = String(getActiveAuthSession()?.serverUrl || '').replace(/\/$/, '');
  return serverUrl ? `${serverUrl}/lists/` : '';
}

const LIST_MENU_ROWS = [
  { key: 'smart', label: 'Create Smart List' },
  { key: 'trakt', label: 'Import from Trakt' },
  { key: 'mdblist', label: 'Import from MDBList' },
  { key: 'csv', label: 'Import from CSV' },
];

// The web's New List dropdown; the import rows open the import dialog.
function ListActionsMenu({ open, onClose, onSmart, onImport }) {
  if (!open) return null;
  return <Modal transparent visible animationType="fade" onRequestClose={onClose}>
    <Pressable accessibilityRole="button" accessibilityLabel="Close menu" style={styles.menuBackdrop} onPress={onClose}>
      <View style={styles.menu}>
        {LIST_MENU_ROWS.map(row => <Pressable key={row.key} accessibilityRole="menuitem"
          onPress={() => (row.key === 'smart' ? onSmart() : (onClose(), onImport(row.key)))}
          style={({ pressed }) => [styles.menuRow, pressed && styles.menuRowPressed]}>
          <Text style={styles.menuText}>{row.label}</Text>
        </Pressable>)}
      </View>
    </Pressable>
  </Modal>;
}

function openProfile() {
  const session = getActiveAuthSession();
  const username = session?.user?.username;
  const serverUrl = String(session?.serverUrl || '').replace(/\/$/, '');
  if (!username || !serverUrl) {
    return;
  }
  Linking.openURL(`${serverUrl}/user/${encodeURIComponent(username)}/`);
}

export default function ListsScreen({ navigate }) {
  const [transport] = useState(() => createListTransport());
  const [lists, setLists] = useState([]);
  const [loading, setLoading] = useState(transport.mode === 'server');
  const [loadError, setLoadError] = useState('');
  const [reloadToken, setReloadToken] = useState(0);
  const [searchText, setSearchText] = useState('');
  const [search, setSearch] = useState('');
  const [mediaType, setMediaType] = useState('all');
  const [sortValue, setSortValue] = useState('update');
  const [sortDirection, setSortDirection] = useState('desc');
  const [menuOpen, setMenuOpen] = useState(false);
  const [importKind, setImportKind] = useState(null);
  const [notice, setNotice] = useState('');
  const [form, setForm] = useState(null);
  const [formErrors, setFormErrors] = useState({});
  const [saving, setSaving] = useState(false);

  const signedOut = transport.mode !== 'server';

  useEffect(() => {
    const timer = setTimeout(() => setSearch(searchText.trim()), 300);
    return () => clearTimeout(timer);
  }, [searchText]);

  useEffect(() => {
    if (signedOut) {
      setLists([]);
      setLoading(false);
      setLoadError('');
      return undefined;
    }
    let active = true;
    setLoading(true);
    setLoadError('');
    const username = getActiveAuthSession()?.user?.username || '';
    const sortOption = LIST_SORT_OPTIONS.find(option => option.value === sortValue);
    const sort = `${sortValue}_${sortDirection || sortOption?.direction || 'desc'}`;
    transport.load({ search, sort, mediaType })
      .then(payload => {
        if (!active) return;
        setLists(listsFromPayload(payload, username));
        setLoading(false);
      })
      .catch(cause => {
        if (!active) return;
        setLists([]);
        setLoadError(cause?.message || 'Lists could not be loaded from the server.');
        setLoading(false);
      });
    return () => { active = false; };
  }, [transport, signedOut, search, mediaType, sortValue, sortDirection, reloadToken]);

  const urlPrefix = useMemo(() => serverUrlPrefix(), [signedOut, reloadToken]);

  function chooseSort(option) {
    if (!option || option.value === sortValue) return;
    setSortValue(option.value);
    setSortDirection(option.direction);
  }

  function openForm(mode, listId = null, smart = false) {
    setForm({ mode, listId, smart });
    setFormErrors({});
    setNotice('');
  }

  function closeForm() {
    setForm(null);
    setFormErrors({});
  }

  function validate(values) {
    const errors = {};
    const name = String(values.name || '').trim();
    if (!name) {
      errors.name = 'Enter a list name.';
    }
    const slug = normalizeSlug(values.publicSlug);
    if (['public', 'unlisted'].includes(values.visibility) && slug) {
      if (/^\d+$/.test(slug)) {
        errors.publicSlug = 'Custom list URLs cannot be only numbers.';
      } else if (RESERVED_SLUGS.includes(slug)) {
        errors.publicSlug = 'That URL is reserved.';
      }
    }
    return { errors, name, slug };
  }

  async function saveMembers(listId, values, before) {
    const collaborators = memberUsernames(values.members, 'collaborator');
    const viewers = memberUsernames(values.members, 'viewer');
    const same = (left, right) => left.length === right.length && left.every(name => right.includes(name));
    const change = {};
    if (!before || !same(collaborators, memberUsernames(before.members, 'collaborator'))) {
      change.collaborators = collaborators;
    }
    if (!before || !same(viewers, memberUsernames(before.members, 'viewer'))) change.viewers = viewers;
    if (change.collaborators === undefined && change.viewers === undefined) return;
    if (before === null && !collaborators.length && !viewers.length) return;
    await transport.setMembers({ listId, ...change });
  }

  async function submitForm(values) {
    const { errors, name, slug } = validate(values);
    if (Object.keys(errors).length) {
      setFormErrors(errors);
      return;
    }
    if (signedOut) {
      setNotice('Sign in to create or edit lists.');
      return;
    }
    setSaving(true);
    try {
      const fields = {
        name,
        description: values.description || '',
        visibility: values.visibility,
        allowRecommendations: values.allowRecommendations,
        publicSlug: slug,
        tags: values.tags || [],
        includeNotes: values.includeNotes,
        isSmart: Boolean(values.isSmart),
      };
      let savedNote = '';
      let created = null;
      if (form.mode === 'edit') {
        await transport.update({ listId: form.listId, ...fields });
        await saveMembers(form.listId, values, activeList);
        savedNote = `"${name}" was saved.`;
      } else {
        created = await transport.create({ ...fields, publicSlug: slug || undefined });
        await saveMembers(created?.id, values, null);
        savedNote = `"${name}" was created.`;
      }
      setNotice(savedNote);
      setReloadToken(current => current + 1);
      closeForm();
      if (created?.id && values.isSmart) {
        // Same as the web: a new smart list opens straight into its rules.
        const summary = listSummaryFromPayload(created, getActiveAuthSession()?.user?.username || '');
        navigate?.('ListDetail', { list: summary, editRules: true });
      }
    } catch (cause) {
      setFormErrors({ form: cause?.message || 'The list could not be saved.' });
    } finally {
      setSaving(false);
    }
  }

  async function deleteList(list) {
    if (signedOut) {
      setNotice('Sign in to delete lists.');
      return;
    }
    setSaving(true);
    try {
      await transport.remove({ listId: list.id });
      setNotice(`"${list.name}" was deleted.`);
      setReloadToken(current => current + 1);
      closeForm();
    } catch (cause) {
      setNotice(cause?.message || 'The list could not be deleted.');
    } finally {
      setSaving(false);
    }
  }

  const activeList = form?.mode === 'edit'
    ? lists.find(list => list.id === form.listId)
    : null;

  const formList = form?.mode === 'edit' && activeList
    ? {
        ...activeList,
        urlPrefix,
        currentUrl: ['public', 'unlisted'].includes(activeList.visibility)
          ? `${urlPrefix}${activeList.publicSlug || activeList.id}`
          : '',
      }
    : {
        name: '',
        description: '',
        visibility: 'private',
        publicSlug: '',
        includeNotes: false,
        allowRecommendations: false,
        isSmart: Boolean(form?.smart),
        tags: [],
        members: [],
        urlPrefix,
        currentUrl: '',
      };

  const tagSuggestions = useMemo(
    () => [...new Set(lists.flatMap(list => list.tags || []))].sort((left, right) => left.localeCompare(right)),
    [lists],
  );

  const filtered = useMemo(() => {
    const query = search.trim().toLowerCase();
    if (!query) return lists;
    return lists.filter(list => list.name.toLowerCase().includes(query));
  }, [lists, search]);

  const searching = Boolean(search.trim());

  const showProfile = Boolean(getActiveAuthSession()?.serverUrl && getActiveAuthSession()?.user?.username);

  return <Screen>
    <ListsPageView
      title="Lists"
      subtitle="Organize and share your media lists"
      palette={palette}
      actions={<>
        {showProfile ? <Button label="Public Profile" tone="surface" icon={settingsNavIcons.person} onPress={openProfile} /> : null}
        <View style={styles.splitButton}>
          <Button label="New List" tone="primary" icon={actionIcons.plus} onPress={() => openForm('create')} />
          <Pressable accessibilityRole="button" accessibilityLabel="More list actions"
            onPress={() => setMenuOpen(true)} style={styles.splitToggle}>
            <Icon spec={actionIcons.chevronDown} color={palette.onAccentStrong} size={16} />
          </Pressable>
        </View>
      </>}
      search={<View style={styles.toolbar}>
        <View style={styles.searchRow}>
          <SearchIcon color={palette.textMuted} size={20} />
          <TextInput
            style={styles.searchInput}
            accessibilityLabel="Search lists"
            placeholder="Search lists..."
            placeholderTextColor={palette.textMuted}
            value={searchText}
            onChangeText={setSearchText}
            autoCorrect={false} />
        </View>
        <View style={styles.sortRow}>
          <View style={styles.sortCell}>
            <SelectField label="Media type" labelHidden filter iconChevron value={mediaType} palette={palette}
              leadingIcon={<Icon spec={actionIcons.funnel} color={palette.textMuted} size={16} />}
              options={LIST_TYPE_OPTIONS}
              onChange={event => setMediaType(event.target.value)} />
          </View>
          <View style={styles.sortCell}>
            <SelectField label="Sort lists" labelHidden filter iconChevron value={sortValue} palette={palette}
              options={LIST_SORT_OPTIONS.map(option => ({ value: option.value, label: option.label }))}
              onChange={event => chooseSort(LIST_SORT_OPTIONS.find(option => option.value === event.target.value))} />
          </View>
        </View>
      </View>}
      lists={filtered}
      hideCardMetadata
      onOpenList={list => navigate?.('ListDetail', { list })}
      onListAction={(action, list) => {
        if (action.title === 'Settings') {
          openForm('edit', list.id);
        }
      }}
      state={signedOut
        ? 'error'
        : loading ? 'loading' : loadError ? 'error' : 'ready'}
      error={signedOut
        ? SIGNED_OUT_ERROR
        : { title: 'Lists could not load', body: loadError, retryLabel: 'Try again' }}
      onRetry={signedOut ? undefined : () => setReloadToken(current => current + 1)}
      empty={searching
        ? {
            title: 'No lists match',
            body: 'Clear the search or pick another sort to see your lists.',
          }
        : {
            title: 'No Lists Created Yet',
            body: 'Create custom lists to organize your media collection and share with friends.',
            actionLabel: 'Create Your First List',
          }}
      onEmptyAction={searching ? undefined : () => openForm('create')}
      dialogs={<>
        <ListActionsMenu open={menuOpen} onClose={() => setMenuOpen(false)}
          onSmart={() => { setMenuOpen(false); openForm('create', null, true); }}
          onImport={setImportKind} />
        {importKind ? <ListImportDialog kind={importKind} transport={transport}
          onClose={() => setImportKind(null)}
          onDone={() => setReloadToken(current => current + 1)} /> : null}
        {form ? <ListForm
        key={form.listId || (form.smart ? 'create-smart' : 'create')}
        mode={form.mode}
        list={formList}
        tagSuggestions={tagSuggestions}
        collaboratorSuggestions={[]}
        errors={formErrors}
        pending={saving}
        canDelete={form.mode === 'edit' ? !!activeList?.canDelete : false}
        palette={palette}
        onSubmit={submitForm}
        onDelete={deleteList}
        onClose={closeForm} /> : null}
      </>}
      footer={notice ? <Text style={styles.notice}>{notice}</Text> : null}
    />
  </Screen>;
}

const styles = StyleSheet.create({
  splitButton: { flexDirection: 'row', alignItems: 'stretch', gap: 1 },
  splitToggle: {
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: spacing.sm,
    backgroundColor: palette.accentStrong,
    borderTopRightRadius: radius.sm,
    borderBottomRightRadius: radius.sm,
  },
  menuBackdrop: { flex: 1, alignItems: 'flex-end', paddingTop: 120, paddingRight: spacing.lg },
  menu: {
    width: 208,
    paddingVertical: spacing.xs,
    backgroundColor: palette.surfaceStrong,
    borderRadius: radius.sm,
    borderWidth: 1,
    borderColor: palette.border,
  },
  menuRow: { paddingHorizontal: spacing.md, paddingVertical: spacing.sm },
  menuRowPressed: { backgroundColor: palette.surface },
  menuText: { color: palette.textSecondary, fontSize: 14 },
  toolbar: { gap: spacing.sm },
  searchRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    backgroundColor: palette.surfaceStrong,
    borderRadius: radius.sm,
    paddingHorizontal: spacing.sm,
  },
  searchInput: { flex: 1, color: palette.text, paddingVertical: spacing.sm },
  sortRow: { flexDirection: 'row', gap: spacing.sm },
  sortCell: { flex: 1, minWidth: 0 },
  notice: { color: palette.textMuted, fontSize: 12, lineHeight: 17 },
});
