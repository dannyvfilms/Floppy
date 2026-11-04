import React, { useMemo, useState } from 'react';
import { StyleSheet, Text, TextInput, View } from 'react-native';
import { Screen } from '../components/Screen';
import { FilterBar } from '../../../frontend/ui/FilterBar';
import { ListHeader } from '../../../frontend/ui/ListHeader';
import { ListMembershipPopup } from '../../../frontend/ui/ListMembership';
import { ListResults } from '../../../frontend/ui/ListResults';
import { palette, radius, spacing } from '../theme';

export const surface = {
  id: 'LIST-DETAIL',
  status: 'in_progress',
  title: 'List detail results, membership and bulk actions',
  where: 'List detail page for manual, smart and source-backed lists',
  note: 'The results, membership and bulk actions are ported; their platform transport is being connected next.',
};

const MEMBERSHIPS = {
  1: [
    { id: 'you', name: 'Danny', handle: '@danny', role: 'owner' },
    { id: 'sam', name: 'Sam', handle: '@sam', role: 'collaborator' },
    { id: 'riley', name: 'Riley', handle: '@riley', role: 'collaborator' },
  ],
  2: [{ id: 'you', name: 'Danny', handle: '@danny', role: 'owner' }],
  3: [
    { id: 'northstar', name: 'Northstar', handle: '@northstar', role: 'owner' },
    { id: 'you', name: 'Danny', handle: '@danny', role: 'collaborator' },
    { id: 'sam', name: 'Sam', handle: '@sam', role: 'collaborator' },
    { id: 'riley', name: 'Riley', handle: '@riley', role: 'collaborator' },
    { id: 'jordan', name: 'Jordan', handle: '@jordan', role: 'collaborator' },
  ],
};

const SUGGESTIONS = {
  1: ['Avery', 'Morgan'],
  2: ['Sam', 'Riley'],
  3: [],
};

const LINKS = {
  1: { rss: true, radarr: true, sonarr: true, exportCsv: true },
  2: { rss: true, exportCsv: true },
  3: { rss: true, radarr: true, sonarr: true, exportCsv: true },
};

const ALL_ITEMS = {
  dune: {
    id: 'dune', title: 'Dune: Part Two', mediaType: 'movie', mediaTypeLabel: 'Movie',
    status: 'Completed', statusLabel: 'Completed', score: 8.6,
    progressLabel: 'Watched', releaseLabel: 'Mar 1, 2024', releaseDate: '2024-03-01',
    addedLabel: 'Feb 12, 2025', addedDate: '2025-02-12', startDateLabel: 'Mar 2, 2024', endDateLabel: 'Mar 2, 2024',
    rank: 1, image: { src: 'https://picsum.photos/seed/floppy-list-dune/400/600', fallback: '', source: 'primary' },
    rating: { label: '8.6', value: 8.6, scaleMax: 10 },
    cardCornerChips: [{ kind: 'runtime', text: '2h 46m' }],
  },
  quietOrbit: {
    id: 'quiet-orbit', title: 'The Quiet Orbit', mediaType: 'tv', mediaTypeLabel: 'Show',
    status: 'In progress', statusLabel: 'In progress', score: 8.0,
    progressLabel: '6 / 10 episodes', releaseLabel: '2024', releaseDate: '2024-02-08',
    addedLabel: 'Jan 30, 2025', addedDate: '2025-01-30', startDateLabel: 'Feb 2, 2024', endDateLabel: null,
    rank: 2, image: { src: 'https://picsum.photos/seed/floppy-list-orbit/400/600', fallback: '', source: 'primary' },
    rating: { label: '8.0', value: 8, scaleMax: 10 },
    progressBar: { percent: 60, paused: false },
    cardCornerChips: [{ kind: 'next-episode', text: 'Next ep' }],
  },
  signal: {
    id: 'signal', title: 'Signal & Static', mediaType: 'podcast', mediaTypeLabel: 'Podcast',
    status: 'In progress', statusLabel: 'In progress', score: 4.5,
    progressLabel: '3 / 8 episodes', releaseLabel: '2023', releaseDate: '2023-09-14',
    addedLabel: 'Mar 4, 2025', addedDate: '2025-03-04', startDateLabel: 'Sep 14, 2023', endDateLabel: null,
    rank: 3, cardShape: 'square',
    image: { src: 'https://picsum.photos/seed/floppy-list-signal/400/400', fallback: '', source: 'primary' },
    rating: { label: '4.5', value: 4.5, scaleMax: 5 },
    progressBar: { percent: 38, paused: true },
  },
  paper: {
    id: 'paper-lanterns', title: 'Paper Lanterns', mediaType: 'book', mediaTypeLabel: 'Book',
    status: 'Planning', statusLabel: 'Planning', score: 6.5,
    progressLabel: '0 / 320 pages', releaseLabel: '2022', releaseDate: '2022-10-04',
    addedLabel: 'Apr 18, 2025', addedDate: '2025-04-18', startDateLabel: null, endDateLabel: null,
    rank: 4, image: { src: 'https://picsum.photos/seed/floppy-list-paper/400/600', fallback: '', source: 'primary' },
    rating: { label: '6.5', value: 6.5, scaleMax: 10 },
  },
  hades: {
    id: 'hades', title: 'Hades II', mediaType: 'game', mediaTypeLabel: 'Game',
    status: 'In progress', statusLabel: 'In progress', score: 9.1,
    progressLabel: '14h played', releaseLabel: '2024', releaseDate: '2024-05-06',
    addedLabel: 'Jun 2, 2025', addedDate: '2025-06-02', startDateLabel: 'May 7, 2024', endDateLabel: null,
    rank: 5, cardShape: 'square',
    image: { src: 'https://picsum.photos/seed/floppy-list-hades/400/400', fallback: '', source: 'primary' },
    rating: { label: '9.1', value: 9.1, scaleMax: 10 },
    progressBar: { percent: 42, paused: false },
  },
  severance: {
    id: 'severance', title: 'Severance', mediaType: 'tv', mediaTypeLabel: 'Show',
    status: 'Completed', statusLabel: 'Completed', score: 8.9,
    progressLabel: '9 / 9 episodes', releaseLabel: '2022', releaseDate: '2022-02-18',
    addedLabel: 'Dec 8, 2024', addedDate: '2024-12-08', startDateLabel: 'Feb 18, 2022', endDateLabel: 'Apr 8, 2022',
    rank: 6, image: { src: 'https://picsum.photos/seed/floppy-list-severance/400/600', fallback: '', source: 'primary' },
    rating: { label: '8.9', value: 8.9, scaleMax: 10 },
    progressBar: { percent: 100, paused: false },
  },
  bear: {
    id: 'the-bear', title: 'The Bear', mediaType: 'tv', mediaTypeLabel: 'Show',
    status: 'Paused', statusLabel: 'Paused', score: 8.2,
    progressLabel: '4 / 10 episodes', releaseLabel: '2022', releaseDate: '2022-06-23',
    addedLabel: 'Nov 2, 2024', addedDate: '2024-11-02', startDateLabel: 'Jun 23, 2022', endDateLabel: null,
    rank: 7, image: { src: 'https://picsum.photos/seed/floppy-list-bear/400/600', fallback: '', source: 'primary' },
    rating: { label: '8.2', value: 8.2, scaleMax: 10 },
    progressBar: { percent: 40, paused: true },
  },
  studio: {
    id: 'home-studio', title: 'Building a Home Studio', mediaType: 'video', mediaTypeLabel: 'Video',
    status: 'Completed', statusLabel: 'Completed', score: null,
    progressLabel: '12:40 watched', releaseLabel: '2024', releaseDate: '2024-04-12',
    addedLabel: 'May 12, 2025', addedDate: '2025-05-12', startDateLabel: 'Apr 12, 2024', endDateLabel: 'Apr 12, 2024',
    rank: 8, cardShape: 'landscape', video: true,
    image: { src: 'https://picsum.photos/seed/floppy-list-studio/800/450', fallback: '', source: 'primary' },
    cardCornerChips: [{ kind: 'runtime', text: '12:40' }],
  },
  memory: {
    id: 'memory', title: 'A Memory Called Empire', mediaType: 'book', mediaTypeLabel: 'Book',
    status: 'Dropped', statusLabel: 'Dropped', score: 7.0,
    progressLabel: '180 / 512 pages', releaseLabel: '2019', releaseDate: '2019-03-26',
    addedLabel: 'Aug 21, 2024', addedDate: '2024-08-21', startDateLabel: 'Mar 26, 2019', endDateLabel: null,
    rank: 9, image: { src: 'https://picsum.photos/seed/floppy-list-memory/400/600', fallback: '', source: 'primary' },
    rating: { label: '7.0', value: 7, scaleMax: 10 },
    progressBar: { percent: 35, paused: true },
  },
  blueEye: {
    id: 'blue-eye', title: 'Blue Eye Samurai', mediaType: 'anime', mediaTypeLabel: 'Anime',
    status: 'Planning', statusLabel: 'Planning', score: null,
    progressLabel: '0 / 8 episodes', releaseLabel: '2023', releaseDate: '2023-11-03',
    addedLabel: 'Jan 9, 2025', addedDate: '2025-01-09', startDateLabel: null, endDateLabel: null,
    rank: 10, image: { src: 'https://picsum.photos/seed/floppy-list-samurai/400/600', fallback: '', source: 'primary' },
  },
  outerWilds: {
    id: 'outer-wilds', title: 'Outer Wilds', mediaType: 'game', mediaTypeLabel: 'Game',
    status: 'Completed', statusLabel: 'Completed', score: 9.5,
    progressLabel: '22h played', releaseLabel: '2019', releaseDate: '2019-05-28',
    addedLabel: 'Jul 14, 2024', addedDate: '2024-07-14', startDateLabel: 'May 28, 2019', endDateLabel: 'Jun 9, 2019',
    rank: 11, cardShape: 'square',
    image: { src: 'https://picsum.photos/seed/floppy-list-wilds/400/400', fallback: '', source: 'primary' },
    rating: { label: '9.5', value: 9.5, scaleMax: 10 },
    progressBar: { percent: 100, paused: false },
  },
  cinder: {
    id: 'cinder', title: 'Cinder', mediaType: 'movie', mediaTypeLabel: 'Movie',
    status: 'In progress', statusLabel: 'In progress', score: 7.4,
    progressLabel: '1h 12m watched', releaseLabel: '2025', releaseDate: '2025-01-17',
    addedLabel: 'Mar 28, 2025', addedDate: '2025-03-28', startDateLabel: 'Jan 17, 2025', endDateLabel: null,
    rank: 12, image: { src: 'https://picsum.photos/seed/floppy-list-cinder/400/600', fallback: '', source: 'primary' },
    rating: { label: '7.4', value: 7.4, scaleMax: 10 },
    progressBar: { percent: 48, paused: false },
  },
};

const LIST_ITEMS = {
  1: Object.values(ALL_ITEMS),
  2: ['quietOrbit', 'severance', 'paper', 'hades', 'memory', 'blueEye', 'outerWilds', 'cinder'].map(key => ALL_ITEMS[key]),
  3: ['dune', 'severance', 'bear', 'outerWilds', 'signal'].map(key => ALL_ITEMS[key]),
};

const DEFAULT_LIST = {
  id: '1',
  name: 'Weekend Watchlist',
  itemsCount: 12,
  completionPercent: 25,
  visibility: 'public',
  memberCount: 3,
  canEdit: true,
  canRecommend: true,
  role: 'Owner',
  href: '/demo/lists/1',
};

const FILTER_PALETTE = {
  background: palette.background,
  surface: palette.surface,
  surfaceStrong: palette.surfaceStrong,
  surfaceHover: palette.surfaceMuted,
  border: palette.border,
  text: palette.text,
  textSecondary: palette.textSecondary,
  textMuted: palette.textMuted,
  accent: palette.accent,
  accentStrong: palette.accentStrong,
  accentText: '#ffffff',
  danger: palette.danger,
  disabled: palette.textMuted,
  overlay: 'rgba(24, 24, 27, 0.78)',
  radius: radius.md,
};

const LIST_PALETTE = {
  ...palette,
  textSecondary: palette.textSecondary,
  border: palette.border,
  accentStrong: palette.accentStrong,
  accent: palette.accent,
  disabled: palette.textMuted,
  overlay: 'rgba(24, 24, 27, 0.78)',
  backdrop: 'rgba(0, 0, 0, 0.6)',
};

function buildList(source) {
  const base = { ...DEFAULT_LIST, ...(source || {}) };
  const members = source?.members || MEMBERSHIPS[base.id] || MEMBERSHIPS['1'];
  const current = members.find(member => member.id === 'you');
  return {
    ...base,
    visibility: String(base.visibility || 'private').toLowerCase(),
    members,
    memberCount: source?.memberCount || members.length,
    isOwner: source?.isOwner ?? current?.role === 'owner',
    role: source?.role || (current?.role === 'owner' ? 'Owner' : 'Collaborator'),
    links: source?.links || LINKS[base.id] || LINKS['1'],
  };
}

function itemsFor(list) {
  return LIST_ITEMS[list.id] || LIST_ITEMS['1'];
}

function defaultFilters(list) {
  const nested = list.isSmart || (list.source && list.source !== 'local');
  return {
    mediaTypes: [],
    statuses: [],
    sort: nested ? 'date_added' : 'custom',
    direction: nested ? 'desc' : 'asc',
    view: 'grid',
    ranges: {
      rating: { from: '', to: '', within: '', unit: 'days' },
      dateAdded: { from: '', to: '', within: '', unit: 'days' },
    },
  };
}

function ratingRange(value) {
  const from = value?.from ? Number(value.from) : null;
  const to = value?.to ? Number(value.to) : null;
  return { from: Number.isNaN(from) ? null : from, to: Number.isNaN(to) ? null : to };
}

function withinDays(iso, within, unit) {
  if (!iso || !within) {
    return true;
  }
  const amount = Number(within);
  if (!amount) {
    return true;
  }
  const days = { days: 1, weeks: 7, months: 30, years: 365 }[unit] || 1;
  return Date.now() - Date.parse(iso) <= amount * days * 86400000;
}

function sortItems(items, filters) {
  const direction = filters.direction === 'asc' ? 1 : -1;
  return [...items].sort((a, b) => {
    switch (filters.sort) {
      case 'title':
        return direction * a.title.localeCompare(b.title);
      case 'media_type':
        return direction * a.mediaTypeLabel.localeCompare(b.mediaTypeLabel);
      case 'release_date':
        return direction * String(a.releaseDate || '').localeCompare(String(b.releaseDate || ''));
      case 'date_added':
        return direction * String(a.addedDate || '').localeCompare(String(b.addedDate || ''));
      case 'score':
        return direction * ((a.score ?? -1) - (b.score ?? -1));
      case 'progress':
        return direction * String(a.progressLabel || '').localeCompare(String(b.progressLabel || ''));
      case 'custom':
        return (a.rank ?? Number.MAX_SAFE_INTEGER) - (b.rank ?? Number.MAX_SAFE_INTEGER);
      default:
        return 0;
    }
  });
}

function activeFilter(filters) {
  return filters.mediaTypes.length > 0
    || filters.statuses.length > 0
    || Object.values(filters.ranges).some(value => value.from || value.to || value.within);
}

export default function ListDetailScreen({ params, onBack, navigate }) {
  const [list, setList] = useState(() => buildList(params?.list));
  const [filters, setFilters] = useState(() => defaultFilters(buildList(params?.list)));
  const [search, setSearch] = useState('');
  const [selectMode, setSelectMode] = useState(false);
  const [selectedIds, setSelectedIds] = useState([]);
  const [bulkMessage, setBulkMessage] = useState(null);
  const [notice, setNotice] = useState(null);
  const [membersOpen, setMembersOpen] = useState(false);
  const [suggestions, setSuggestions] = useState(() => SUGGESTIONS[list.id] || []);

  const items = useMemo(() => itemsFor(list), [list.id]);
  const options = useMemo(() => {
    const mediaTypes = [];
    const statuses = [];
    items.forEach(item => {
      if (!mediaTypes.some(entry => entry.value === item.mediaType)) {
        mediaTypes.push({ value: item.mediaType, label: item.mediaTypeLabel });
      }
      const value = item.status.toLowerCase();
      if (!statuses.some(entry => entry.value === value)) {
        statuses.push({ value, label: item.statusLabel });
      }
    });
    return {
      mediaTypes,
      statuses,
      sorts: [
        { value: 'custom', label: 'Custom order' },
        { value: 'date_added', label: 'Date added' },
        { value: 'title', label: 'Title' },
        { value: 'release_date', label: 'Release date' },
        { value: 'score', label: 'Rating' },
        { value: 'progress', label: 'Progress' },
        { value: 'media_type', label: 'Media type' },
      ],
      views: [
        { value: 'grid', label: 'Grid' },
        { value: 'table', label: 'Table' },
      ],
      ranges: [
        { key: 'rating', label: 'Rating', type: 'number', placeholder: '0–10' },
        {
          key: 'dateAdded',
          label: 'Date added',
          type: 'date',
          placeholder: 'YYYY-MM-DD',
          relative: true,
          units: [
            { value: 'days', label: 'Days' },
            { value: 'weeks', label: 'Weeks' },
            { value: 'months', label: 'Months' },
            { value: 'years', label: 'Years' },
          ],
        },
      ],
    };
  }, [items]);

  const visibleItems = useMemo(() => {
    const query = search.trim().toLowerCase();
    const rating = ratingRange(filters.ranges.rating);
    const dateRange = filters.ranges.dateAdded || {};
    const filtered = items.filter(item => {
      if (query && !item.title.toLowerCase().includes(query)) {
        return false;
      }
      if (filters.mediaTypes.length && !filters.mediaTypes.includes(item.mediaType)) {
        return false;
      }
      if (filters.statuses.length && !filters.statuses.includes(item.status.toLowerCase())) {
        return false;
      }
      if (rating.from != null && (item.score == null || item.score < rating.from)) {
        return false;
      }
      if (rating.to != null && (item.score == null || item.score > rating.to)) {
        return false;
      }
      if (dateRange.from && String(item.addedDate || '') < dateRange.from) {
        return false;
      }
      if (dateRange.to && String(item.addedDate || '') > dateRange.to) {
        return false;
      }
      if (dateRange.within && !withinDays(item.addedDate, dateRange.within, dateRange.unit)) {
        return false;
      }
      return true;
    });
    return sortItems(filtered, filters);
  }, [items, search, filters]);

  function changeFilters(intent) {
    setFilters(current => {
      if (intent.type === 'clear') {
        return defaultFilters(list);
      }
      if (intent.type === 'toggle') {
        const values = current[intent.key] || [];
        return {
          ...current,
          [intent.key]: values.includes(intent.value)
            ? values.filter(value => value !== intent.value)
            : [...values, intent.value],
        };
      }
      if (intent.type === 'set') {
        return { ...current, [intent.key]: intent.value };
      }
      if (intent.type === 'range') {
        return {
          ...current,
          ranges: { ...current.ranges, [intent.key]: intent.value },
        };
      }
      return current;
    });
    setBulkMessage(null);
  }

  function toggleSelectMode() {
    if (selectMode) {
      setSelectedIds([]);
      setBulkMessage(null);
    }
    setSelectMode(!selectMode);
  }

  function toggleItem(id) {
    setSelectedIds(current => current.includes(id)
      ? current.filter(value => value !== id)
      : [...current, id]);
    setBulkMessage(null);
  }

  function runBulkAction(kind) {
    const labels = {
      status: 'Status update',
      list: 'Add to list',
      collection: 'Add to collection',
      tag: 'Tag change',
      plays: 'Add plays',
    };
    setBulkMessage(`${selectedIds.length} selected · ${labels[kind] || kind} is ready for the server bulk action.`);
  }

  function changeVisibility(visibility) {
    setList(current => ({ ...current, visibility }));
    setNotice(`Visibility set to ${visibility} in this demo. The server save is not connected yet.`);
  }

  function addMember(name) {
    const id = name.toLowerCase();
    setList(current => {
      if (current.members.some(member => member.id === id)) {
        return current;
      }
      const next = [...current.members, { id, name, handle: `@${id}`, role: 'collaborator' }];
      return { ...current, members: next, memberCount: next.length };
    });
    setSuggestions(current => current.filter(value => value !== name));
    setNotice(`${name} added as a collaborator in this demo.`);
  }

  function removeMember(id) {
    setList(current => {
      const next = current.members.filter(member => member.id !== id);
      return { ...current, members: next, memberCount: next.length };
    });
    setNotice('Collaborator removed in this demo.');
  }

  function openLink(row) {
    setMembersOpen(false);
    setNotice(`${row.label} link is ready for the platform browser or download adapter.`);
  }

  function openItem(item) {
    if (navigate) {
      navigate('Detail', { item });
      return;
    }
    setNotice(`${item.title} uses the platform navigation adapter.`);
  }

  function recommendItem() {
    setNotice('Recommendations remain a server flow; the native recommend screen is not ported.');
  }

  const emptyMode = items.length === 0
    ? 'empty'
    : search.trim() ? 'search'
      : activeFilter(filters) ? 'filters'
        : 'empty';

  return <Screen title={list.name} subtitle="List detail" onBack={onBack}>
    <ListHeader
      list={list}
      palette={LIST_PALETTE}
      labels={{ more: 'Members' }}
      onAddItem={() => setNotice('Add New Item remains a server flow; the native add-item screen is not ported.')}
      onExport={() => setNotice('CSV export is ready for the platform download adapter.')}
      onMore={() => setMembersOpen(true)}
      onEdit={() => setMembersOpen(true)} />
    {notice ? <Text style={styles.notice}>{notice}</Text> : null}
    <View style={styles.controls}>
      <TextInput
        style={styles.search}
        placeholder="Search this list or recommend something…"
        placeholderTextColor={palette.textMuted}
        value={search}
        onChangeText={setSearch}
        autoCorrect={false}
        accessibilityLabel="Search this list" />
      <FilterBar
        filters={filters}
        options={options}
        palette={FILTER_PALETTE}
        resultCount={visibleItems.length}
        labels={{
          filters: 'Filters',
          status: 'Status',
          sort: 'Sort',
          view: 'View',
          range: 'Range',
        }}
        onChange={changeFilters} />
    </View>
    <ListResults
      items={visibleItems}
      layout={filters.view}
      sort={filters.sort}
      palette={LIST_PALETTE}
      canEdit={list.canEdit}
      canRecommend={list.canRecommend}
      isSmart={list.isSmart}
      selectMode={selectMode}
      selectedIds={selectedIds}
      onToggleItem={toggleItem}
      onToggleSelectMode={toggleSelectMode}
      onClearSelection={() => {
        setSelectedIds([]);
        setBulkMessage(null);
      }}
      onBulkAction={runBulkAction}
      bulkMessage={bulkMessage}
      onOpenItem={openItem}
      emptyMode={emptyMode}
      hasSearch={!!search.trim()}
      onRecommend={recommendItem}
      onBrowse={() => navigate?.('Search', { query: '' })} />
    <ListMembershipPopup
      open={membersOpen}
      list={list}
      palette={LIST_PALETTE}
      suggestions={suggestions}
      onClose={() => setMembersOpen(false)}
      onChangeVisibility={changeVisibility}
      onAddMember={addMember}
      onRemoveMember={removeMember}
      onOpenLink={openLink} />
  </Screen>;
}

const styles = StyleSheet.create({
  controls: { gap: spacing.md },
  search: {
    backgroundColor: palette.surfaceStrong,
    color: palette.text,
    borderRadius: radius.sm,
    paddingHorizontal: spacing.sm,
    paddingVertical: spacing.sm,
  },
  notice: { color: palette.textMuted, fontSize: 12, lineHeight: 17 },
});
