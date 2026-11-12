import React, { useEffect, useMemo, useState } from 'react';
import { CollectionView } from '../../../frontend/pages/CollectionView';
import { CollectionCopyDialog } from '../../../frontend/ui/CollectionCopies';
import { Modal, ScrollView, StyleSheet, View } from 'react-native';
import { Button } from '../../../frontend/ui/Button';
import { CollectionFieldManager, CollectionFieldValueInputs } from '../../../frontend/ui/CollectionCustomFields';
import { Screen } from '../components/Screen';
import {
  COLLECTION_PAGE_SIZE,
  collectionEntriesFromPayload,
  collectionItemsFromPayload,
  copyFieldsFor,
  copyValuesFromCopy,
  createCollectionTransport,
  customFieldGroupsFromPayload,
  customFilterFromGroups,
  emptyCopyValues,
  hasMoreFromPayload,
  mediaTypeColorsFromPayload,
} from '../data/collectionTransport';
import { managerGroupsFromPayload } from '../data/collectionTransportCore';
import { formatUserDate } from '../data/userDate';
import { palette } from '../theme';

export const surface = {
  id: 'OWNERSHIP',
  status: 'ported',
  title: 'Collection and copies',
  where: 'Collection browser and detail ownership',
  note: 'The collection browser renders server-owned items in grid, grouped rows and table views with the shared search, filter bar, sort and per-view reveal controls. Signed-in loads page through GET /api/v1/collection/ (limit/offset until exhausted), which now carries purchase price and location, rating, TV completeness and custom field values, so the Location, Rating and Completeness filters work. Custom field values are edited with the shared value inputs and saved through PATCH /api/v1/collection/{id}/ (custom_field_values); the field schema loads from GET /api/v1/collection/fields/ and the filter menu offers the first dropdown or checkbox field. Removals map to DELETE; adding a copy goes through the provider-addressed PUT, so show seasons, comic issues, music, podcast and video items decline the add with a clear message. Custom fields are also sort choices (field_<id>), ordered like the web. iOS/Android runtime interaction has not been exercised.',
};

const MEDIA_LABELS = {
  movie: 'Movies',
  tv: 'TV Shows',
  anime: 'Anime',
  book: 'Books',
  comic: 'Comics',
  manga: 'Manga',
  game: 'Games',
  music: 'Music',
  podcast: 'Podcasts',
  video: 'Videos',
};

// The web collection page's sort choices (COLLECTION_SORT_CHOICES).
const SORTS = [
  { value: 'collected_at', label: 'Date Collected' },
  { value: 'title', label: 'Title' },
  { value: 'release_date', label: 'Release Date' },
];

const DEFAULT_FILTERS = {
  type: 'all',
  format: 'all',
  resolution: 'all',
  hdr: 'all',
  location: 'all',
  rating: 'all',
  completeness: 'all',
  customFilter: '',
  customValue: '',
  query: '',
  sort: 'collected_at',
  direction: 'desc',
  view: 'grid',
};

function defaultDirection(sort) {
  return sort === 'collected_at' ? 'desc' : 'asc';
}

function itemLocation(item) {
  return item.purchaseLocation || item.location || '';
}

function itemMatches(item, filters) {
  if (filters.type !== 'all' && item.mediaType !== filters.type) return false;
  if (filters.format !== 'all' && item.format !== filters.format) return false;
  if (filters.resolution !== 'all' && item.resolution !== filters.resolution) return false;
  if (filters.hdr !== 'all' && item.hdr !== filters.hdr) return false;
  if (filters.location !== 'all' && itemLocation(item) !== filters.location) return false;
  // Completeness exists only for TV-family items; unknown stays unknown
  // instead of passing as full.
  if (filters.rating === 'rated' && item.rating == null) return false;
  if (filters.rating === 'not_rated' && item.rating != null) return false;
  if (filters.completeness !== 'all' && !item.completeness) return false;
  if (filters.completeness === 'partial' && !item.completeness?.isPartial) return false;
  if (filters.completeness === 'full' && item.completeness?.isPartial) return false;
  if (filters.customFilter && filters.customValue) {
    const matches = item.copies.some(copy => {
      const value = copy.customValues?.[filters.customFilter];
      return String(value === undefined || value === null ? false : value) === filters.customValue;
    });
    if (!matches) return false;
  }
  const query = (filters.query || '').trim().toLowerCase();
  if (query && !`${item.title} ${item.format || ''} ${itemLocation(item)}`.toLowerCase().includes(query)) {
    return false;
  }
  return true;
}

// The web's custom-field sort: numbers, then checkboxes, then text; entries
// with no value come last whatever the direction.
function customSortKey(raw) {
  if (typeof raw === 'boolean') return [1, Number(raw), ''];
  if (typeof raw === 'number') return [0, raw, ''];
  return [2, 0, String(raw).toLowerCase()];
}

function compareCustom(left, right) {
  for (let index = 0; index < 3; index += 1) {
    if (left[index] < right[index]) return -1;
    if (left[index] > right[index]) return 1;
  }
  return 0;
}

function sortByCustomField(items, fieldId, direction) {
  const blank = value => value == null || value === '';
  const valueOf = item => (item.customValues || {})[fieldId];
  const present = items.filter(item => !blank(valueOf(item)));
  const missing = items.filter(item => blank(valueOf(item)));
  present.sort((left, right) => compareCustom(customSortKey(valueOf(left)), customSortKey(valueOf(right))) * direction);
  return [...present, ...missing];
}

function sortItems(items, filters) {
  const direction = filters.direction === 'asc' ? 1 : -1;
  if (String(filters.sort).startsWith('field_')) {
    return sortByCustomField(items, filters.sort.slice(6), direction);
  }
  const sorted = [...items];
  sorted.sort((left, right) => {
    if (filters.sort === 'title') return left.title.localeCompare(right.title) * direction;
    if (filters.sort === 'release_date') {
      return String(left.releaseDate || '').localeCompare(String(right.releaseDate || '')) * direction;
    }
    return String(left.collectedAt || '').localeCompare(String(right.collectedAt || '')) * direction;
  });
  return sorted;
}

function applyFilterIntent(filters, intent) {
  if (intent.type === 'reset') return { ...DEFAULT_FILTERS, view: filters.view, groupByMediaType: filters.groupByMediaType };
  if (intent.type === 'type') return { ...filters, type: intent.value || 'all' };
  if (intent.type === 'completeness') return { ...filters, completeness: intent.value || 'all' };
  if (intent.type === 'set' && intent.key === 'sort') {
    // The web flips direction to the new sort's default when the key changes.
    const sort = intent.value || 'collected_at';
    return { ...filters, sort, direction: defaultDirection(sort) };
  }
  if (intent.type === 'set') return { ...filters, [intent.key]: intent.value };
  return filters;
}

function buildOptions(items, customFilter, fieldGroups = []) {
  const unique = key => [...new Set(items.map(item => item[key]).filter(Boolean))]
    .sort()
    .map(value => ({ value, label: value }));
  const locations = [...new Set(items.map(itemLocation).filter(Boolean))]
    .sort()
    .map(value => ({ value, label: value }));
  return {
    mediaTypes: Object.keys(MEDIA_LABELS)
      .filter(value => items.some(item => item.mediaType === value))
      .map(value => ({ value, label: MEDIA_LABELS[value] })),
    formats: unique('format'),
    resolutions: unique('resolution'),
    hdrs: unique('hdr'),
    locations,
    sorts: [
      ...SORTS,
      ...fieldGroups.flatMap(group => group.fields.map(field => ({ value: `field_${field.id}`, label: field.label }))),
    ],
    customFilter,
    groupByMediaType: true,
    showCompleteness: items.some(item => ['tv', 'anime', 'season'].includes(item.mediaType)),
  };
}

function toBrowserItem(item, colors) {
  return {
    ...item,
    mediaTypeLabel: MEDIA_LABELS[item.mediaType] || item.mediaType,
    mediaTypeColor: colors[item.mediaType] || palette.accent,
    collectedAtLabel: formatUserDate(item.collectedAt),
    copies: (item.copies || []).map(copy => ({ ...copy, collectedAtLabel: formatUserDate(copy.collectedAt) })),
    purchaseLocation: itemLocation(item),
    copyLabel: item.copyLabel || '',
  };
}

const PAGE_SIZE = 6;
const ROW_BATCH = 2;
const TABLE_COLUMNS = ['title', 'type', 'format', 'resolution', 'collected'];

function filterSignature(filters) {
  const { view, ...rest } = filters;
  return JSON.stringify(rest);
}

function buildGroups(items, limits, colors) {
  const byType = new Map();
  items.forEach(item => {
    if (!byType.has(item.mediaType)) byType.set(item.mediaType, []);
    byType.get(item.mediaType).push(item);
  });
  return [...byType.entries()].map(([type, rows]) => {
    const limit = limits[type] ?? ROW_BATCH;
    const loaded = rows.slice(0, limit);
    return {
      key: type,
      label: MEDIA_LABELS[type] || type,
      items: loaded.map(item => toBrowserItem(item, colors)),
      loadedCount: loaded.length,
      total: rows.length,
      hasMore: loaded.length < rows.length,
    };
  });
}

export default function CollectionScreen({ navigate }) {
  const [transport] = useState(() => createCollectionTransport());
  const signedOut = transport.mode !== 'server';
  const [entries, setEntries] = useState([]);
  const [loading, setLoading] = useState(!signedOut);
  const [paging, setPaging] = useState(false);
  const [loadError, setLoadError] = useState('');
  const [reloadToken, setReloadToken] = useState(0);
  const [filters, setFilters] = useState(DEFAULT_FILTERS);
  const [selectedId, setSelectedId] = useState(null);
  const [editingId, setEditingId] = useState(null);
  const [formValues, setFormValues] = useState({});
  const [initialValues, setInitialValues] = useState({});
  const [formErrors, setFormErrors] = useState({});
  const [saving, setSaving] = useState(false);
  const [saveNote, setSaveNote] = useState('');
  const [notice, setNotice] = useState('');
  const [page, setPage] = useState(1);
  const [rowLimits, setRowLimits] = useState({});
  const [typeColors, setTypeColors] = useState({});
  const [fieldGroups, setFieldGroups] = useState([]);
  const [customValues, setCustomValues] = useState({});
  const [initialCustomValues, setInitialCustomValues] = useState({});
  const [manager, setManager] = useState(null);

  useEffect(() => {
    if (signedOut) {
      setEntries([]);
      setLoading(false);
      setPaging(false);
      setLoadError('');
      return undefined;
    }
    let active = true;
    setLoading(true);
    setPaging(true);
    setLoadError('');
    setEntries([]);
    (async () => {
      try {
        const collected = [];
        let offset = 0;
        let more = true;
        while (more) {
          const payload = await transport.load({ limit: COLLECTION_PAGE_SIZE, offset });
          if (!active) return;
          collected.push(...collectionEntriesFromPayload(payload));
          setTypeColors(mediaTypeColorsFromPayload(payload));
          setEntries(collected);
          setLoading(false);
          more = hasMoreFromPayload(payload);
          offset += COLLECTION_PAGE_SIZE;
        }
      } catch (cause) {
        if (!active) return;
        setEntries([]);
        setLoadError(cause?.message || 'The collection could not be loaded.');
        setLoading(false);
      } finally {
        if (active) setPaging(false);
      }
    })();
    return () => { active = false; };
  }, [transport, reloadToken, signedOut]);

  useEffect(() => {
    if (signedOut) return undefined;
    let active = true;
    transport.loadFields()
      .then(payload => { if (active) setFieldGroups(customFieldGroupsFromPayload(payload)); })
      .catch(() => { if (active) setFieldGroups([]); });
    return () => { active = false; };
  }, [transport, signedOut, reloadToken]);

  function openManager() {
    transport.loadFields().then(payload => {
      const draft = managerGroupsFromPayload(payload);
      setManager({ draft, baseline: draft, fieldTypes: payload.field_types || [], mediaTypes: payload.media_types || [], dirty: false, saving: false, error: '' });
    }).catch(failure => setNotice(failure?.message || 'The custom fields could not be loaded.'));
  }

  function saveManager() {
    for (const group of manager.draft) {
      if (!String(group.name || '').trim()) {
        setManager(current => ({ ...current, error: 'Every group needs a name.' }));
        return;
      }
      for (const field of group.fields) {
        if (!String(field.label || '').trim()) {
          setManager(current => ({ ...current, error: 'Every field needs a label.' }));
          return;
        }
        if (!(field.mediaTypes || []).length) {
          setManager(current => ({ ...current, error: `"${field.label}" needs at least one media type.` }));
          return;
        }
      }
    }
    setManager(current => ({ ...current, saving: true, error: '' }));
    transport.saveFields(manager.draft).then(payload => {
      const draft = managerGroupsFromPayload(payload);
      setManager(current => ({ ...current, draft, baseline: draft, dirty: false, saving: false }));
      setFieldGroups(customFieldGroupsFromPayload(payload));
    }).catch(failure => {
      setManager(current => ({ ...current, saving: false, error: failure?.message || 'The fields could not be saved.' }));
    });
  }

  const items = useMemo(() => collectionItemsFromPayload(entries), [entries]);
  const customFilter = useMemo(() => customFilterFromGroups(fieldGroups), [fieldGroups]);
  const options = useMemo(() => buildOptions(items, customFilter, fieldGroups), [items, customFilter, fieldGroups]);
  const filteredItems = useMemo(
    () => sortItems(items.filter(item => itemMatches(item, filters)), filters),
    [items, filters],
  );
  const totalCount = filteredItems.length;
  const isRows = filters.view === 'rows' || (filters.view === 'grid' && filters.groupByMediaType && filters.type === 'all');
  const visibleItems = useMemo(
    () => (isRows ? [] : filteredItems.slice(0, page * PAGE_SIZE)).map(item => toBrowserItem(item, typeColors)),
    [filteredItems, isRows, page, typeColors],
  );
  const groups = useMemo(
    () => (isRows ? buildGroups(filteredItems, rowLimits, typeColors) : null),
    [filteredItems, isRows, rowLimits, typeColors],
  );
  const hasMore = !isRows && totalCount > visibleItems.length;
  const signature = filterSignature(filters);
  const selectedItem = items.find(item => item.id === selectedId) || null;
  const selectedItemFieldGroups = useMemo(
    () => (selectedItem
      ? fieldGroups
        .map(group => ({ ...group, fields: group.fields.filter(field => field.mediaTypes?.includes(selectedItem.mediaType)) }))
        .filter(group => group.fields.length)
      : []),
    [fieldGroups, selectedItem],
  );
  const selectedFields = useMemo(
    () => copyFieldsFor(selectedItem?.mediaType),
    [selectedItem?.mediaType],
  );

  useEffect(() => {
    setPage(1);
    setRowLimits({});
  }, [signature]);

  function changeFilters(intent) {
    setFilters(current => applyFilterIntent(current, intent));
    setNotice('');
  }

  // The whole collection is already loaded; revealing more rows is local.
  function loadMore() {
    if (hasMore) setPage(current => current + 1);
  }

  function loadMoreGroup(group) {
    if (!group?.hasMore) return;
    setRowLimits(current => ({
      ...current,
      [group.key]: (current[group.key] ?? ROW_BATCH) + ROW_BATCH,
    }));
  }

  function openCopy(item, copy = null) {
    const values = copy ? copyValuesFromCopy(copy) : emptyCopyValues(copyFieldsFor(item.mediaType));
    setSelectedId(item.id);
    setEditingId(copy?.id || null);
    setFormValues(values);
    setInitialValues(values);
    setCustomValues(copy?.customValues || {});
    setInitialCustomValues(copy?.customValues || {});
    setFormErrors({});
    setSaveNote('');
    setNotice('');
  }

  function closeCopy() {
    setSelectedId(null);
    setEditingId(null);
    setFormErrors({});
    setSaveNote('');
  }

  function changeForm(name, value) {
    setFormValues(current => ({ ...current, [name]: value }));
    setFormErrors(current => ({ ...current, [name]: '' }));
  }

  function validateCopy() {
    const errors = {};
    if (formValues.purchasePrice !== '' && Number.isNaN(Number(formValues.purchasePrice))) {
      errors.purchasePrice = 'Enter a number.';
    } else if (formValues.purchasePrice !== '' && Number(formValues.purchasePrice) < 0) {
      errors.purchasePrice = 'Must be at least zero.';
    }
    if (formValues.bitrate !== '' && Number.isNaN(Number(formValues.bitrate))) {
      errors.bitrate = 'Enter a number.';
    }
    if (formValues.collectedAt && !/^\d{4}-\d{2}-\d{2}$/.test(formValues.collectedAt)) {
      errors.collectedAt = 'Use YYYY-MM-DD.';
    }
    return errors;
  }

  async function saveCopy() {
    if (!selectedItem || saving) return;
    const errors = validateCopy();
    if (Object.keys(errors).length) {
      setFormErrors(errors);
      return;
    }
    setSaving(true);
    setFormErrors({});
    setSaveNote('');
    try {
      if (editingId) {
        await transport.updateCopy({
          entryId: editingId,
          values: formValues,
          initial: initialValues,
          customValues,
          initialCustomValues,
        });
        const fresh = emptyCopyValues(selectedFields);
        setEditingId(null);
        setFormValues(fresh);
        setInitialValues(fresh);
        setCustomValues({});
        setInitialCustomValues({});
      } else {
        // Without a provider address (show seasons, comic issues, music,
        // podcast and video items) the transport rejects with an explanation.
        await transport.addCopy({ address: selectedItem.address, values: formValues });
      }
      setSaveNote('Copy saved.');
      setReloadToken(current => current + 1);
    } catch (cause) {
      setFormErrors({ form: cause?.message || 'The copy could not be saved.' });
    } finally {
      setSaving(false);
    }
  }

  async function removeCopy(copy) {
    if (!selectedItem || saving) return;
    setSaving(true);
    setFormErrors({});
    setSaveNote('');
    try {
      await transport.removeCopy({ entryId: copy.id });
      if (editingId === copy.id) {
        const fresh = emptyCopyValues(selectedFields);
        setEditingId(null);
        setFormValues(fresh);
        setInitialValues(fresh);
      }
      setNotice('Copy removed.');
      setReloadToken(current => current + 1);
    } catch (cause) {
      setFormErrors({ form: cause?.message || 'The copy could not be removed.' });
    } finally {
      setSaving(false);
    }
  }

  const browserLabels = signedOut
    ? { retry: 'Sign In', empty: 'Your collection is empty', emptyHint: 'Sign in to load your collection from the server.' }
    : {};

  return <Screen>
    <CollectionView
      subtitle=""
      items={visibleItems}
      groups={groups}
      filters={filters}
      options={options}
      labels={browserLabels}
      busy={paging}
      resultCount={totalCount}
      tableColumns={TABLE_COLUMNS}
      hasMore={hasMore}
      loading={loading}
      error={signedOut ? (transport.reason || 'Sign in to see your collection.') : loadError}
      onRetry={signedOut ? () => navigate?.('Auth') : () => setReloadToken(current => current + 1)}
      palette={palette}
      notice={notice}
      onFilterChange={changeFilters}
      onLoadMore={loadMore}
      onLoadMoreGroup={loadMoreGroup}
      onOpenItem={item => navigate?.('Detail', { item: { identity: item.identity, title: item.title, mediaType: item.mediaType } })}
      onOpenCopy={item => openCopy(items.find(entry => entry.id === item.id) || item)}>
      <CollectionCopyDialog
        visible={!!selectedItem}
        item={selectedItem}
        copies={(selectedItem?.copies || []).map(copy => ({ ...copy, collectedAtLabel: formatUserDate(copy.collectedAt) }))}
        fields={selectedFields}
        values={formValues}
        errors={formErrors}
        palette={palette}
        canMutate={!signedOut}
        editingId={editingId}
        busy={saving}
        saveNote={saveNote}
        onClose={closeCopy}
        onChange={changeForm}
        onSave={saveCopy}
        onEdit={copy => openCopy(selectedItem, copy)}
        onRemove={removeCopy}>
        {editingId && selectedItemFieldGroups.length ? <CollectionFieldValueInputs
          groups={selectedItemFieldGroups}
          values={customValues}
          palette={palette}
          canEdit={!signedOut}
          onChange={(key, value) => setCustomValues(current => ({ ...current, [key]: value }))} /> : null}
        {editingId && !signedOut ? <Button label="Manage custom fields" tone="surface" onPress={openManager} /> : null}
      </CollectionCopyDialog>
      {manager ? <Modal transparent visible animationType="fade" onRequestClose={() => setManager(null)}>
        <View style={managerStyles.overlay}>
          <ScrollView style={[managerStyles.sheet, { backgroundColor: palette.surface }]} contentContainerStyle={managerStyles.body}>
            <CollectionFieldManager
              canManage
              groups={manager.draft}
              mediaTypes={manager.mediaTypes}
              fieldTypes={manager.fieldTypes}
              palette={palette}
              dirty={manager.dirty}
              saving={manager.saving}
              error={manager.error}
              onChange={draft => setManager(current => ({ ...current, draft, dirty: true }))}
              onReset={() => setManager(current => ({ ...current, draft: current.baseline, dirty: false, error: '' }))}
              onSave={saveManager} />
            <Button label="Close" tone="surface" onPress={() => setManager(null)} />
          </ScrollView>
        </View>
      </Modal> : null}
    </CollectionView>
  </Screen>;
}

const managerStyles = StyleSheet.create({
  overlay: { flex: 1, backgroundColor: palette.overlay, justifyContent: 'center', padding: 16 },
  sheet: { borderRadius: 16, maxHeight: '90%' },
  body: { padding: 16, gap: 12 },
});
