import React, { useEffect, useMemo, useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { Button } from '../../../frontend/ui/Button';
import { CollectionView } from '../../../frontend/pages/CollectionView';
import {
  CollectionCopyDialog,
} from '../../../frontend/ui/CollectionCopies';
import {
  CollectionFieldManager,
  CollectionFieldValueInputs,
} from '../../../frontend/ui/CollectionCustomFields';
import { Screen } from '../components/Screen';
import { collectionItemsFromPayload, createCollectionTransport } from '../data/collectionTransport';
import { palette, spacing } from '../theme';

export const surface = {
  id: 'OWNERSHIP',
  status: 'ported',
  title: 'Collection and copies',
  where: 'Collection browser and detail ownership',
  note: 'The collection browser renders server-owned items in grid, grouped rows and table views with the shared search, filter bar, sort, completeness and per-view paging controls. Signed-in loads map /api/v1/collection/ and group copies by item; the API does not expose custom-field definitions, purchase location or per-item score, so those columns stay empty and the custom-field manager is hidden. Mutations stay in local state; Django remains authoritative for ownership, validation, season expansion and persistence, and iOS/Android runtime interaction has not been exercised.',
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

const MEDIA_COLORS = {
  movie: '#6366f1',
  tv: '#0ea5e9',
  anime: '#f43f5e',
  book: '#d946ef',
  comic: '#f59e0b',
  manga: '#fb7185',
  game: '#10b981',
  music: '#ec4899',
  podcast: '#8b5cf6',
  video: '#f97316',
};

const VIDEO_FIELDS = [
  { name: 'format', label: 'Format', type: 'select', options: ['4K Blu-ray', 'Blu-ray', 'DVD', 'Digital', 'Streaming', 'VHS'].map(value => ({ value, label: value })) },
  { name: 'resolution', label: 'Resolution', type: 'select', options: ['480p', '720p', '1080p', '4K', '8K'].map(value => ({ value, label: value })) },
  { name: 'hdr', label: 'HDR', type: 'select', options: ['HDR10', 'HDR10+', 'Dolby Vision', 'HLG'].map(value => ({ value, label: value })) },
  { name: 'audioCodec', label: 'Audio codec', type: 'select', options: ['Dolby Atmos', 'Dolby TrueHD', 'DTS-HD MA', 'DTS', 'AAC', 'FLAC'].map(value => ({ value, label: value })) },
  { name: 'audioChannels', label: 'Audio channels', type: 'select', options: ['Mono', 'Stereo', '5.1', '7.1', '7.1.2', '7.1.4'].map(value => ({ value, label: value })) },
  { name: 'bitrate', label: 'Bitrate', type: 'number', help: 'Kilobits per second' },
  { name: 'is3d', label: '3D', type: 'checkbox' },
  { name: 'purchasePrice', label: 'Purchase price', type: 'number' },
  { name: 'purchaseLocation', label: 'Location', type: 'text' },
  { name: 'collectedAt', label: 'Collected at', type: 'text', help: 'YYYY-MM-DD' },
];

const BOOK_FIELDS = [
  { name: 'format', label: 'Format', type: 'select', options: ['Hardcover', 'Paperback', 'Trade Paperback', 'Digital', 'Audiobook'].map(value => ({ value, label: value })) },
  { name: 'purchasePrice', label: 'Purchase price', type: 'number' },
  { name: 'purchaseLocation', label: 'Location', type: 'text' },
  { name: 'collectedAt', label: 'Collected at', type: 'text', help: 'YYYY-MM-DD' },
];

const GAME_FIELDS = [
  { name: 'format', label: 'Format', type: 'select', options: ['Physical', 'Digital', 'ROM', 'Subscription', 'Cloud'].map(value => ({ value, label: value })) },
  { name: 'resolution', label: 'Platform', type: 'select', options: ['PC (Windows)', 'Mac', 'Steam Deck', 'PlayStation 5', 'Xbox Series X|S', 'Nintendo Switch', 'Mobile (iOS)'].map(value => ({ value, label: value })) },
  { name: 'hdr', label: 'Edition', type: 'select', options: ['Standard', 'Deluxe', 'Gold', 'Ultimate', "Collector's", 'Game of the Year', 'Complete', 'Definitive'].map(value => ({ value, label: value })) },
  { name: 'purchasePrice', label: 'Purchase price', type: 'number' },
  { name: 'purchaseLocation', label: 'Location', type: 'text' },
  { name: 'collectedAt', label: 'Collected at', type: 'text', help: 'YYYY-MM-DD' },
];

const MUSIC_FIELDS = [
  { name: 'format', label: 'Format', type: 'select', options: ['Vinyl', 'CD', 'Digital', 'Cassette', 'SACD', 'Streaming'].map(value => ({ value, label: value })) },
  { name: 'audioCodec', label: 'Audio codec', type: 'select', options: ['FLAC', 'MP3', 'AAC', 'ALAC', 'WAV', 'OGG', 'Opus'].map(value => ({ value, label: value })) },
  { name: 'audioChannels', label: 'Audio channels', type: 'select', options: ['Mono', 'Stereo', '5.1', '7.1'].map(value => ({ value, label: value })) },
  { name: 'bitrate', label: 'Bitrate', type: 'number' },
  { name: 'purchasePrice', label: 'Purchase price', type: 'number' },
  { name: 'purchaseLocation', label: 'Location', type: 'text' },
  { name: 'collectedAt', label: 'Collected at', type: 'text', help: 'YYYY-MM-DD' },
];

const MEDIUM_FIELDS = {
  video: VIDEO_FIELDS,
  books: BOOK_FIELDS,
  games: GAME_FIELDS,
  music: MUSIC_FIELDS,
};

function mediumFor(mediaType) {
  if (mediaType === 'book' || mediaType === 'comic' || mediaType === 'manga') return 'books';
  if (mediaType === 'game' || mediaType === 'boardgame') return 'games';
  if (mediaType === 'music' || mediaType === 'podcast') return 'music';
  return 'video';
}

const FIELD_TYPE_CHOICES = [
  { value: 'text', label: 'Text' },
  { value: 'number', label: 'Number' },
  { value: 'date', label: 'Date' },
  { value: 'select', label: 'Select' },
  { value: 'checkbox', label: 'Checkbox' },
];

const MEDIA_TYPE_CHOICES = ['movie', 'tv', 'anime', 'book', 'manga', 'comic', 'game', 'boardgame', 'music', 'podcast', 'video']
  .map(value => ({ value, label: MEDIA_LABELS[value] || value }));

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

function valuesFromForm(fields, item) {
  const copy = item?.copies?.[0] || {};
  const values = {};
  fields.forEach(field => {
    const fallback = field.name === 'format' ? copy.mediaType || item?.format
      : field.name === 'resolution' ? copy.resolution || item?.resolution
        : field.name === 'hdr' ? copy.hdr || item?.hdr
          : field.name === 'purchaseLocation' ? copy.purchaseLocation || (item && item.location)
            : copy[field.name] ?? item?.[field.name] ?? '';
    values[field.name] = fallback == null ? '' : String(fallback);
  });
  return values;
}

function copyLabelFor(values, groups) {
  const fields = groups.flatMap(group => group.fields || []);
  const volume = fields.find(field => field.label.trim().toLowerCase() === 'volume');
  if (volume && values[String(volume.id)] != null && values[String(volume.id)] !== '') {
    return `Vol. ${values[String(volume.id)]}`;
  }
  const issue = fields.find(field => ['issue', 'issue nr'].includes(field.label.trim().toLowerCase()));
  if (issue && values[String(issue.id)] != null && values[String(issue.id)] !== '') {
    return `#${values[String(issue.id)]}`;
  }
  return 'Copy';
}

function groupForItem(item, groups) {
  if (!item) return [];
  return groups
    .map(group => ({
      ...group,
      fields: group.fields.filter(field => (field.mediaTypes || []).includes(item.mediaType)),
    }))
    .filter(group => group.fields.length);
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
  if (filters.rating === 'rated' && item.rating == null) return false;
  if (filters.rating === 'not_rated' && item.rating != null) return false;
  if (filters.completeness === 'partial' && !item.completeness?.isPartial) return false;
  if (filters.completeness === 'full' && (!item.completeness || item.completeness.isPartial)) return false;
  if (filters.customFilter && filters.customValue) {
    const value = item.customValues?.[filters.customFilter];
    if (String(value) !== String(filters.customValue)) return false;
  }
  const query = (filters.query || '').trim().toLowerCase();
  if (query && !`${item.title} ${item.format || ''} ${itemLocation(item)}`.toLowerCase().includes(query)) {
    return false;
  }
  return true;
}

function sortItems(items, filters) {
  const direction = filters.direction === 'asc' ? 1 : -1;
  const sorted = [...items];
  sorted.sort((left, right) => {
    if (filters.sort === 'title') return left.title.localeCompare(right.title) * direction;
    if (filters.sort === 'release') {
      return String(left.releaseDate || left.collectedAt).localeCompare(String(right.releaseDate || right.collectedAt)) * direction;
    }
    if (filters.sort === 'rating') return ((left.rating || 0) - (right.rating || 0)) * direction;
    if (filters.sort === 'last_watched') {
      return String(left.lastWatched || '').localeCompare(String(right.lastWatched || '')) * direction;
    }
    return String(left.collectedAt).localeCompare(String(right.collectedAt)) * direction;
  });
  return sorted;
}

function applyFilterIntent(filters, intent) {
  if (intent.type === 'reset') return { ...DEFAULT_FILTERS, view: filters.view };
  if (intent.type === 'type') return { ...filters, type: intent.value || 'all' };
  if (intent.type === 'completeness') return { ...filters, completeness: intent.value || 'all' };
  if (intent.type === 'set') return { ...filters, [intent.key]: intent.value };
  return filters;
}

function buildOptions(items) {
  const unique = key => [...new Set(items.map(item => item[key]).filter(Boolean))]
    .sort()
    .map(value => ({ value, label: value }));
  const formats = unique('format');
  const locations = [...new Set(items.map(itemLocation).filter(Boolean))]
    .sort()
    .map(value => ({ value, label: value }));
  return {
    mediaTypes: Object.keys(MEDIA_LABELS)
      .filter(value => items.some(item => item.mediaType === value))
      .map(value => ({ value, label: MEDIA_LABELS[value] })),
    formats,
    resolutions: unique('resolution'),
    hdrs: unique('hdr'),
    locations,
    sorts: [
      { value: 'collected_at', label: 'Date collected' },
      { value: 'title', label: 'Title' },
      { value: 'release', label: 'Release date' },
      { value: 'rating', label: 'Rating' },
      { value: 'last_watched', label: 'Last watched' },
    ],
    customFilter: {
      id: '2',
      label: 'Condition',
      choices: ['Mint', 'Good', 'Worn'].map(value => ({ value, label: value })),
    },
  };
}

function toBrowserItem(item) {
  return {
    ...item,
    mediaTypeLabel: MEDIA_LABELS[item.mediaType] || item.mediaType,
    mediaTypeColor: MEDIA_COLORS[item.mediaType] || palette.accent,
    purchaseLocation: itemLocation(item),
    copyLabel: item.copyLabel || '',
  };
}

const PAGE_SIZE = 6;
const ROW_BATCH = 2;
const TABLE_COLUMNS = ['title', 'type', 'format', 'location', 'collected'];

function filterSignature(filters) {
  const { view, ...rest } = filters;
  return JSON.stringify(rest);
}

function buildGroups(items, limits, loadingKey) {
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
      items: loaded.map(toBrowserItem),
      loadedCount: loaded.length,
      total: rows.length,
      hasMore: loaded.length < rows.length,
      loadingMore: loadingKey === type,
    };
  });
}

export default function CollectionScreen({ navigate, onBack }) {
  const [transport] = useState(() => createCollectionTransport());
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(transport.mode === 'server');
  const [loadError, setLoadError] = useState('');
  const [reloadToken, setReloadToken] = useState(0);
  const [filters, setFilters] = useState(DEFAULT_FILTERS);
  const [owner, setOwner] = useState(true);
  const [selectedId, setSelectedId] = useState(null);
  const [editingId, setEditingId] = useState(null);
  const [formValues, setFormValues] = useState({});
  const [formErrors, setFormErrors] = useState({});
  const [scope, setScope] = useState('item');
  const [selectedSeason, setSelectedSeason] = useState('1');
  const [saveNote, setSaveNote] = useState('');
  const [customGroups, setCustomGroups] = useState([]);
  const [customDraft, setCustomDraft] = useState([]);
  const [customErrors, setCustomErrors] = useState({});
  const [manageFields, setManageFields] = useState(false);
  const [page, setPage] = useState(1);
  const [rowLimits, setRowLimits] = useState({});
  const [loadingMore, setLoadingMore] = useState(false);
  const [loadingRow, setLoadingRow] = useState('');
  const [collectionNotice, setCollectionNotice] = useState('');

  useEffect(() => {
    if (transport.mode !== 'server') {
      setLoading(false);
      return undefined;
    }
    let active = true;
    setLoading(true);
    setLoadError('');
    transport.load()
      .then(payload => {
        if (!active) return;
        setItems(collectionItemsFromPayload(payload));
        setLoading(false);
      })
      .catch(cause => {
        if (!active) return;
        setItems([]);
        setLoadError(cause?.message || 'Your collection could not be loaded from the server.');
        setLoading(false);
      });
    return () => { active = false; };
  }, [transport, reloadToken]);

  const options = useMemo(() => {
    const next = buildOptions(items);
    if (!customGroups.length) next.customFilter = null;
    return next;
  }, [items, customGroups]);
  const filteredItems = useMemo(
    () => sortItems(items.filter(item => itemMatches(item, filters)), filters),
    [items, filters],
  );
  const totalCount = filteredItems.length;
  const isRows = filters.view === 'rows';
  const visibleItems = useMemo(
    () => (isRows ? filteredItems : filteredItems.slice(0, page * PAGE_SIZE)).map(toBrowserItem),
    [filteredItems, isRows, page],
  );
  const groups = useMemo(
    () => (isRows ? buildGroups(filteredItems, rowLimits, loadingRow) : null),
    [filteredItems, isRows, rowLimits, loadingRow],
  );
  const hasMore = !isRows && totalCount > page * PAGE_SIZE;
  const signature = filterSignature(filters);
  const selectedItem = items.find(item => item.id === selectedId) || null;
  const selectedFields = selectedItem ? MEDIUM_FIELDS[mediumFor(selectedItem.mediaType)] || VIDEO_FIELDS : VIDEO_FIELDS;
  const selectedCustomGroups = groupForItem(selectedItem, customGroups);
  const selectedValues = selectedItem?.customValues || {};

  useEffect(() => {
    setPage(1);
    setRowLimits({});
    setLoadingMore(false);
    setLoadingRow('');
  }, [signature]);

  function changeFilters(intent) {
    setFilters(current => applyFilterIntent(current, intent));
    setCollectionNotice('');
  }

  function loadMore() {
    if (loadingMore || !hasMore) return;
    setLoadingMore(true);
    setCollectionNotice('Loading the next collection page…');
    setTimeout(() => {
      setPage(current => current + 1);
      setLoadingMore(false);
      setCollectionNotice('');
    }, 250);
  }

  function loadMoreGroup(group) {
    if (!group?.hasMore || loadingRow) return;
    const key = group.key;
    setLoadingRow(key);
    setCollectionNotice(`Loading more ${String(group.label || key).toLowerCase()}…`);
    setTimeout(() => {
      setRowLimits(current => ({ ...current, [key]: (current[key] ?? ROW_BATCH) + ROW_BATCH }));
      setLoadingRow('');
      setCollectionNotice('');
    }, 250);
  }

  function openCopy(item, copy = null) {
    setSelectedId(item.id);
    setEditingId(copy?.id || null);
    setFormValues(copy ? {
      format: copy.mediaType || '',
      resolution: copy.resolution || '',
      hdr: copy.hdr || '',
      audioCodec: copy.audioCodec || '',
      audioChannels: copy.audioChannels || '',
      bitrate: copy.bitrate == null ? '' : String(copy.bitrate),
      is3d: !!copy.is3d,
      purchasePrice: copy.purchasePrice || '',
      purchaseLocation: copy.purchaseLocation || '',
      collectedAt: copy.collectedAt || '',
    } : valuesFromForm(selectedFields, item));
    setFormErrors({});
    setScope('item');
    setSelectedSeason(String(item.seasons?.[0]?.number || '1'));
    setSaveNote('');
    setManageFields(false);
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

  function saveCopy() {
    if (!selectedItem || !owner) return;
    const errors = validateCopy();
    if (Object.keys(errors).length) {
      setFormErrors(errors);
      return;
    }
    const label = copyLabelFor(selectedValues, customGroups);
    const copy = {
      id: editingId || `${selectedItem.id}-copy-${Date.now()}`,
      label: label === 'Copy' ? formValues.format || 'Copy' : label,
      mediaType: formValues.format || '',
      resolution: formValues.resolution || '',
      hdr: formValues.hdr || '',
      audioCodec: formValues.audioCodec || '',
      audioChannels: formValues.audioChannels || '',
      bitrate: formValues.bitrate || '',
      is3d: !!formValues.is3d,
      purchasePrice: formValues.purchasePrice || '',
      purchaseLocation: formValues.purchaseLocation || '',
      collectedAt: formValues.collectedAt || '',
    };
    setItems(current => current.map(item => {
      if (item.id !== selectedItem.id) return item;
      const copies = editingId
        ? item.copies.map(existing => existing.id === editingId ? { ...existing, ...copy } : existing)
        : [...item.copies, copy];
      return {
        ...item,
        copies,
        format: copy.mediaType || item.format,
        resolution: copy.resolution || item.resolution,
        hdr: copy.hdr || item.hdr,
        location: copy.purchaseLocation || item.location,
        collectedAt: copy.collectedAt || item.collectedAt,
      };
    }));
    const cascadeCount = scope === 'episodes'
      ? selectedItem.seasons?.reduce((total, season) => total + Number(String(season.label).match(/(\d+) episodes/)?.[1] || 0), 0)
      : scope === 'season'
        ? Number(String(selectedItem.seasons?.find(season => String(season.number) === String(selectedSeason))?.label).match(/(\d+) episodes/)?.[1] || 0)
        : 0;
    setSaveNote(cascadeCount
      ? `Copy saved. ${cascadeCount} episode copies are created by the season cascade.`
      : 'Copy saved.');
    setEditingId(null);
    if (!editingId) {
      const nextCopies = [...selectedItem.copies, copy];
      setFormValues(valuesFromForm(selectedFields, { ...selectedItem, copies: nextCopies }));
    }
  }

  function removeCopy(copy) {
    if (!selectedItem || !owner) return;
    const nextCopies = selectedItem.copies.filter(existing => existing.id !== copy.id);
    setItems(current => current.map(item => item.id === selectedItem.id
      ? { ...item, copies: nextCopies }
      : item));
    if (editingId === copy.id) {
      setEditingId(null);
      setFormValues(valuesFromForm(selectedFields, { ...selectedItem, copies: nextCopies }));
    }
    setSaveNote(nextCopies.length ? 'Copy removed.' : 'Copy removed. This item now has no owned copies.');
  }

  function changeCustomValue(key, value) {
    if (!selectedItem || !owner) return;
    setItems(current => current.map(item => item.id === selectedItem.id
      ? { ...item, customValues: { ...(item.customValues || {}), [key]: value } }
      : item));
  }

  function validateFieldGroups(groups) {
    const errors = {};
    groups.forEach(group => {
      if (!String(group.name || '').trim()) errors.group = 'Every group needs a name.';
      group.fields.forEach(field => {
        if (!String(field.label || '').trim()) errors.field = 'Every field needs a label.';
        if (!(field.mediaTypes || []).length) {
          errors.field = `${field.label || 'A field'} needs at least one media type.`;
        }
        if ((field.fieldType || field.field_type) === 'select' && !String(field.optionsText || (field.options || []).join('\n')).trim()) {
          errors.options = `${field.label || 'A select field'} needs at least one option.`;
        }
      });
    });
    return errors;
  }

  function saveFieldGroups() {
    if (!owner) return;
    const errors = validateFieldGroups(customDraft);
    if (Object.keys(errors).length) {
      setCustomErrors(errors);
      return;
    }
    const normalized = customDraft.map(group => ({
      ...group,
      fields: group.fields.map(field => ({
        ...field,
        mediaTypes: field.mediaTypes || field.media_types || [],
        options: (field.fieldType || field.field_type) === 'select'
          ? String(field.optionsText || (field.options || []).join('\n')).split('\n').map(option => option.trim()).filter(Boolean)
          : [],
      })),
    }));
    setCustomGroups(normalized);
    setCustomDraft(normalized);
    setCustomErrors({});
    setManageFields(false);
    setSaveNote('Custom fields saved. Django still validates ownership and field ids on the server.');
  }

  const readOnlyLabel = owner ? 'Read-only preview' : 'Return to owner view';

  return <Screen onBack={onBack}>
    <View style={styles.demoBar}>
      <View style={styles.demoCopy}>
        <Text style={styles.demoTitle}>Owner collection</Text>
        <Text style={styles.demoText}>
          {owner
            ? 'Tap any cover or table row to open its copies, media fields and custom values. Server ownership and validation remain authoritative.'
            : 'Mutation controls are hidden for a read-only viewer. Copies and custom values stay visible.'}
        </Text>
      </View>
      <Button label={readOnlyLabel} tone="surface" palette={palette}
        onPress={() => {
          setOwner(current => !current);
          setManageFields(false);
        }} />
    </View>

    <CollectionView
      title=""
      subtitle=""
      items={visibleItems}
      groups={groups}
      filters={filters}
      options={options}
      resultCount={totalCount}
      tableColumns={TABLE_COLUMNS}
      hasMore={hasMore}
      loadingMore={loadingMore}
      loading={loading}
      error={loadError}
      onRetry={() => setReloadToken(current => current + 1)}
      palette={palette}
      notice={collectionNotice}
      onFilterChange={changeFilters}
      onLoadMore={loadMore}
      onLoadMoreGroup={loadMoreGroup}
      onOpenCopy={item => openCopy(items.find(entry => entry.id === item.id) || item)}>
    <CollectionCopyDialog
      visible={!!selectedItem}
      item={selectedItem}
      copies={selectedItem?.copies || []}
      fields={selectedFields}
      values={formValues}
      errors={formErrors}
      palette={palette}
      canMutate={owner}
      scope={scope}
      seasons={selectedItem?.seasons || []}
      selectedSeason={selectedSeason}
      editingId={editingId}
      saveNote={saveNote}
      onClose={closeCopy}
      onChange={changeForm}
      onScopeChange={setScope}
      onSeasonChange={setSelectedSeason}
      onSave={saveCopy}
      onEdit={copy => openCopy(selectedItem, copy)}
      onRemove={removeCopy}
    >
      <CollectionFieldValueInputs
        groups={selectedCustomGroups}
        values={selectedValues}
        errors={{}}
        palette={palette}
        canEdit={owner}
        onChange={changeCustomValue}
      />
      {owner ? <Button
        label={manageFields ? 'Done managing fields' : 'Manage custom fields'}
        tone="surface"
        palette={palette}
        onPress={() => {
          setManageFields(current => !current);
          setCustomDraft(customGroups);
        }} /> : null}
      {owner && manageFields ? <CollectionFieldManager
        groups={customDraft}
        fieldTypes={FIELD_TYPE_CHOICES}
        mediaTypes={MEDIA_TYPE_CHOICES}
        palette={palette}
        canManage={owner}
        dirty={JSON.stringify(customDraft) !== JSON.stringify(customGroups)}
        error={customErrors.group || customErrors.field || customErrors.options || ''}
        onChange={setCustomDraft}
        onSave={saveFieldGroups}
        onReset={() => {
          setCustomDraft(customGroups);
          setCustomErrors({});
        }} /> : null}
    </CollectionCopyDialog>
    </CollectionView>
  </Screen>;
}

const styles = StyleSheet.create({
  demoBar: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: spacing.md },
  demoCopy: { flex: 1, gap: 2 },
  demoTitle: { color: palette.text, fontSize: 14, fontWeight: '700' },
  demoText: { color: palette.textMuted, fontSize: 12, lineHeight: 17 },
  notice: { color: palette.textMuted, fontSize: 12, lineHeight: 17 },
});
