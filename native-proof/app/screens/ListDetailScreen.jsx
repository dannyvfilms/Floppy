import React, { useEffect, useMemo, useState } from 'react';
import { Linking, Modal, Pressable, StyleSheet, Text, TextInput, View, useWindowDimensions } from 'react-native';
import { Screen } from '../components/Screen';
import { getActiveAuthSession } from '../data/authSession';
import { getSidebarListPins, subscribeSidebarListPins, toggleSidebarListPin } from '../data/sidebarListPins';
import { createListTransport } from '../data/listTransport';
import { saveTextFile } from '../data/fileFlows';
import {
  LIST_PAGE_SIZE,
  activityFromPayload,
  applyTierPlacements,
  compareListDateAdded,
  hasMorePages,
  listItemsFromPayload,
  listSummaryFromPayload,
  listsFromPayload,
  memberUsernames,
  recommendationsFromPayload,
  searchPaginationFromPayload,
  searchResultsFromPayload,
  smartOptionsFromPayload,
  smartRulesFromPayload,
  tiersFromPayload,
} from '../data/listTransportCore';
import { libraryMediaTypeOptions } from '../data/libraryTransportCore';
import { ListDetailPageView } from '../../../frontend/pages/ListDetailPageView';
import { Button } from '../../../frontend/ui/Button';
import { Icon, SearchIcon } from '../../../frontend/ui/Icon';
import { actionIcons } from '../../../frontend/ui/actionIcons';
import { FilterBar } from '../../../frontend/ui/FilterBar';
import { ViewToggle } from '../../../frontend/ui/ViewToggle';
import { ListHeader } from '../../../frontend/ui/ListHeader';
import { ListForm } from '../../../frontend/ui/ListFormView';
import { ListMembershipPopup } from '../../../frontend/ui/ListMembership';
import { ListBulkBar, ListResults } from '../../../frontend/ui/ListResults';
import { SmartRuleBuilder, SmartRuleSummary } from '../../../frontend/ui/SmartRules';
import { ListItemPreview, ListItemSearch } from '../../../frontend/ui/ListSearchView';
import { ConfirmDialog } from '../../../frontend/settings/ConfirmDialog';
import { ListRecommendations } from '../../../frontend/ui/ListRecommendationsView';
import { TierBoard } from '../../../frontend/ui/TierBoard';
import { palette, radius, spacing } from '../theme';

export const surface = {
  id: 'LIST-DETAIL',
  status: 'ported',
  title: 'List detail on real data',
  where: 'List detail screen: header, actions, controls, results, tiers, membership, activity and recommendations',
  note: 'The detail page renders the shared ListDetailPageView composition. Signed-in loads page through GET /api/v1/lists/{id}/ (200 items a request, with server search, media type and the title, rating and release sorts) until the list ends, then read the saved tiers from GET .../tiers/. Smart lists (is_smart) show the rules summary and, for editors, the smart-rule editor on GET/PUT .../smart-rules/ with the option lists from .../smart-rules/options/, plus Sync now on POST .../smart-sync/; they hide the tier board and manual ordering. The tier board saves definitions, moves, fill and undo through /api/v1/lists/{id}/tiers/. Add New Item and Recommend Item search GET /api/v1/search/{type}/ and submit through PUT /api/v1/media/.../lists/{id}/ and POST /api/v1/lists/{id}/recommendations/, with approvals and denies on the same recommendation routes. Bulk status, collection, add to list and apply tag use /api/v1/library/bulk/*; custom order moves call POST .../items/reorder/. Members are added by username (PUT .../collaborators/ and .../viewers/); the edit form also saves tags, public notes and the smart flag. Export as CSV reads GET .../export/ and saves the text through the platform file flow. Add Plays to History from selection, the column menu, pin to sidebar and tier PNG export are not available here. iOS/Android runtime verification is separate from the Expo compile check.',
};

// Status words the bulk endpoint accepts (app Status values).
const BULK_STATUSES = ['Completed', 'In progress', 'Paused', 'Planning', 'Dropped']
  .map(value => ({ value, label: value }));

// The list API sorts these fields on the server; the rest sort on the loaded
// items, which is complete once every page has arrived.
const SERVER_SORTS = { title: 'title', score: 'score', release_date: 'release_datetime' };

const ACTIVITY_TYPE_LABELS = {
  item_added: 'Item Added',
  item_removed: 'Item Removed',
  recommendation_approved: 'Recommendation Approved',
  recommendation_denied: 'Recommendation Denied',
  list_created: 'List Created',
  list_edited: 'List Edited',
  collaborator_added: 'Collaborator Added',
  collaborator_removed: 'Collaborator Removed',
};

const SEARCH_MEDIA_TYPES = libraryMediaTypeOptions()
  .filter(option => !['season', 'episode', 'comicissue'].includes(option.value));

// The web's pie chart button: the list's media type mix.
function MediaTypeBreakdown({ rows }) {
  const [open, setOpen] = useState(false);
  if (!rows?.length) return null;
  return <>
    <Pressable accessibilityRole="button" accessibilityLabel="Media type breakdown"
      onPress={() => setOpen(true)} style={styles.breakdownButton}>
      <Icon spec={actionIcons.pieChart} color={palette.text} size={16} />
    </Pressable>
    <Modal transparent visible={open} animationType="fade" onRequestClose={() => setOpen(false)}>
      <Pressable accessibilityRole="button" accessibilityLabel="Close" style={styles.breakdownBackdrop}
        onPress={() => setOpen(false)}>
        <View style={styles.breakdownPanel}>
          <Text style={styles.breakdownTitle}>MEDIA TYPES</Text>
          <View style={styles.breakdownBar}>
            {rows.map(row => <View key={row.value}
              style={{ flexBasis: `${row.percent}%`, flexGrow: 0, flexShrink: 0, backgroundColor: row.color || palette.accent }} />)}
          </View>
          {rows.map(row => <View key={row.value} style={styles.breakdownRow}>
            <View style={[styles.breakdownDot, { backgroundColor: row.color || palette.accent }]} />
            <Text style={styles.breakdownLabel}>{row.label}</Text>
            <Text style={styles.breakdownCount}>{row.count}</Text>
            <Text style={styles.breakdownPercent}>{row.percent}%</Text>
          </View>)}
        </View>
      </Pressable>
    </Modal>
  </>;
}

function filterPalette() {
  return { ...palette, accentText: palette.onAccentStrong, disabled: palette.textMuted, radius: radius.md };
}

function listPalette() {
  return { ...palette, disabled: palette.textMuted, backdrop: palette.overlay };
}

const SEARCH_IDLE = { query: '', mediaType: 'movie', page: 1, results: [], totalPages: 1, status: 'idle', error: '' };

function defaultFilters(list) {
  return {
    mediaTypes: [],
    statuses: [],
    sort: 'date_added',
    direction: 'desc',
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

function sortItems(rows, filters) {
  const direction = filters.direction === 'asc' ? 1 : -1;
  return [...rows].sort((a, b) => {
    switch (filters.sort) {
      case 'title':
        return direction * String(a.title).localeCompare(String(b.title));
      case 'media_type':
        return direction * String(a.mediaTypeLabel).localeCompare(String(b.mediaTypeLabel));
      case 'release_date':
        return direction * String(a.releaseDate || '').localeCompare(String(b.releaseDate || ''));
      case 'date_added':
        return compareListDateAdded(a, b, filters.direction);
      case 'score':
        return direction * ((a.score ?? -1) - (b.score ?? -1));
      case 'progress':
        return direction * String(a.progressLabel || '').localeCompare(String(b.progressLabel || ''));
      case 'status':
        return direction * String(a.status || '').localeCompare(String(b.status || ''));
      case 'start_date':
        return direction * String(a.startDate || '').localeCompare(String(b.startDate || ''));
      case 'end_date':
        return direction * String(a.endDate || '').localeCompare(String(b.endDate || ''));
      case 'custom':
        return (a.rank ?? Number.MAX_SAFE_INTEGER) - (b.rank ?? Number.MAX_SAFE_INTEGER);
      default:
        return 0;
    }
  });
}

function filtersActive(filters) {
  return filters.mediaTypes.length > 0
    || filters.statuses.length > 0
    || Object.values(filters.ranges).some(value => value.from || value.to || value.within);
}

function applyLocalMove(rows, id, action) {
  const index = rows.findIndex(row => row.id === id);
  if (index < 0) return rows;
  const target = action === 'first' ? 0
    : action === 'back' ? Math.max(0, index - 1)
      : action === 'next' ? Math.min(rows.length - 1, index + 1)
        : rows.length - 1;
  if (target === index) return rows;
  const next = [...rows];
  const [moved] = next.splice(index, 1);
  next.splice(target, 0, moved);
  return next.map((row, order) => ({ ...row, rank: order + 1, tierRank: order + 1 }));
}

function shareLinksFor(list) {
  const session = getActiveAuthSession();
  const serverUrl = String(session?.serverUrl || '').replace(/\/$/, '');
  if (!serverUrl || !list.id) return null;
  const byLink = list.publicSlug && ['public', 'unlisted'].includes(list.visibility);
  const reference = byLink ? list.publicSlug : list.id;
  return {
    rss: `${serverUrl}/list/${encodeURIComponent(reference)}/rss`,
    radarr: `${serverUrl}/list/${encodeURIComponent(reference)}/json?arr=radarr`,
    sonarr: `${serverUrl}/list/${encodeURIComponent(reference)}/json?arr=sonarr`,
    exportCsv: `${serverUrl}/list/${encodeURIComponent(reference)}/export`,
  };
}

function resultCardModel(result) {
  return {
    title: result.title,
    image: { src: result.image, fallback: '', source: 'primary' },
    shape: result.mediaType === 'game' ? 'square' : result.mediaType === 'video' ? 'landscape' : 'poster',
    video: result.mediaType === 'video',
    href: null,
    statusChip: null,
    cornerChips: [],
    lines: [{ join: 'plain', parts: result.year ? [{ text: result.year, muted: true }] : [] }],
    rating: null,
  };
}

function resultPreviewModel(result) {
  return {
    title: result.title,
    mediaTypeLabel: result.mediaTypeLabel,
    year: result.year,
    score: null,
    scoreCount: null,
    genres: result.platforms,
    synopsis: '',
    image: { src: result.image },
    details: result.platforms?.length ? { format: result.platforms.join(', ') } : {},
  };
}

function sameMedia(identity, result) {
  if (!identity) return false;
  return identity.mediaType === result.mediaType
    && identity.source === result.source
    && String(identity.mediaId) === String(result.mediaId);
}

function DialogFrame({ title, subtitle, onClose, children }) {
  return <Modal visible transparent animationType="fade" onRequestClose={onClose}>
    <View style={[styles.dialogOverlay, { backgroundColor: palette.overlay }]}>
      <Pressable accessible={false} style={StyleSheet.absoluteFill} onPress={onClose} />
      <View style={[styles.dialogPanel, { backgroundColor: palette.surface, borderColor: palette.border }]}>
        <View style={styles.dialogHeader}>
          <View style={styles.dialogHeading}>
            <Text role="heading" aria-level={2} style={[styles.dialogTitle, { color: palette.text }]}>{title}</Text>
            {subtitle ? <Text style={[styles.dialogSubtitle, { color: palette.textMuted }]}>{subtitle}</Text> : null}
          </View>
          <Button label="Close" tone="surface" onPress={onClose} palette={palette} />
        </View>
        {children}
      </View>
    </View>
  </Modal>;
}

export default function ListDetailScreen({ params, onBack, navigate }) {
  const { width } = useWindowDimensions();
  const transport = useMemo(
    () => createListTransport(params?.listTransport),
    [params?.listTransport],
  );
  const [list, setList] = useState(() => ({
    ...(params?.list || {}),
    id: params?.list?.id ? String(params.list.id) : '',
    members: params?.list?.members || [],
  }));
  const [pinState, setPinState] = useState(getSidebarListPins);
  useEffect(() => subscribeSidebarListPins(setPinState), []);
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(transport.mode === 'server');
  const [loadError, setLoadError] = useState('');
  const [reloadToken, setReloadToken] = useState(0);
  const [search, setSearch] = useState('');
  const [filters, setFilters] = useState(() => defaultFilters(params?.list || {}));
  const [selectMode, setSelectMode] = useState(false);
  const [selectedIds, setSelectedIds] = useState([]);
  const [bulkMessage, setBulkMessage] = useState('');
  const [notice, setNotice] = useState('');
  const [membersOpen, setMembersOpen] = useState(false);
  const [editOpen, setEditOpen] = useState(false);
  const [formErrors, setFormErrors] = useState({});
  const [savingForm, setSavingForm] = useState(false);
  const [activity, setActivity] = useState({ open: false, loading: false, error: '', entries: [] });
  const [recommendations, setRecommendations] = useState({ open: false, loading: false, error: '', entries: [] });
  const [addFlow, setAddFlow] = useState(null);
  const [preview, setPreview] = useState(null);
  const [confirmRemove, setConfirmRemove] = useState({ open: false, ids: [], busy: false, error: '' });
  const [tiers, setTiers] = useState([]);
  const [loadingMore, setLoadingMore] = useState(false);
  const [knownTypes, setKnownTypes] = useState([]);
  const [serverSearch, setServerSearch] = useState('');
  const [smartRules, setSmartRules] = useState(null);
  const [smartOptions, setSmartOptions] = useState(null);
  const [rulesEditing, setRulesEditing] = useState(Boolean(params?.editRules));
  const [draftRules, setDraftRules] = useState(null);
  const [ruleState, setRuleState] = useState('idle');
  const [bulkTargets, setBulkTargets] = useState({ lists: [], tags: [] });
  const LIST_PALETTE = listPalette();
  const FILTER_PALETTE = filterPalette();
  const [tierNotice, setTierNotice] = useState('');
  const [tierUndo, setTierUndo] = useState([]);
  const isSmart = !!list.isSmart;
  const signedOut = transport.mode !== 'server';
  const canEdit = !!list.canEdit;
  const canReorder = canEdit && !isSmart;

  useEffect(() => {
    const timer = setTimeout(() => setServerSearch(search.trim()), 300);
    return () => clearTimeout(timer);
  }, [search]);

  const serverType = filters.mediaTypes.length === 1 ? filters.mediaTypes[0] : '';
  const serverSortField = SERVER_SORTS[filters.sort] || '';
  const serverSort = serverSortField ? `${serverSortField}_${filters.direction === 'asc' ? 'asc' : 'desc'}` : '';

  useEffect(() => {
    if (signedOut) {
      setItems([]);
      setLoading(false);
      setLoadError('');
      return undefined;
    }
    const listId = params?.list?.id || list.id;
    if (!listId) {
      setLoading(false);
      setLoadError('No list was selected.');
      return undefined;
    }
    let active = true;
    setLoading(true);
    setLoadError('');
    const username = getActiveAuthSession()?.user?.username || '';
    (async () => {
      try {
        let offset = 0;
        let collected = [];
        let smart = false;
        for (;;) {
          const payload = await transport.loadDetail({
            listId, offset, sort: serverSort, search: serverSearch, mediaType: serverType,
          });
          if (!active) return;
          if (offset === 0) {
            const summary = listSummaryFromPayload(payload, username);
            smart = Boolean(summary?.isSmart);
            setList(current => (summary ? { ...current, ...summary } : current));
          }
          collected = [...collected, ...listItemsFromPayload(payload, offset)];
          setItems(collected);
          setLoading(false);
          if (!hasMorePages(payload, offset, LIST_PAGE_SIZE)) break;
          setLoadingMore(true);
          offset += LIST_PAGE_SIZE;
        }
        setKnownTypes(current => {
          const seen = new Map(current.map(entry => [entry.value, entry]));
          collected.forEach(item => {
            if (item.mediaType && !seen.has(item.mediaType)) {
              seen.set(item.mediaType, { value: item.mediaType, label: item.mediaTypeLabel });
            }
          });
          return [...seen.values()];
        });
        if (!smart) {
          const tierPayload = await transport.loadTiers({ listId });
          if (!active) return;
          setTiers(tiersFromPayload(tierPayload));
          setItems(current => applyTierPlacements(current, tierPayload));
        }
      } catch (cause) {
        if (!active) return;
        setItems([]);
        setLoadError(cause?.message || 'This list could not be loaded from the server.');
        setLoading(false);
      } finally {
        if (active) setLoadingMore(false);
      }
    })();
    return () => { active = false; };
  }, [transport, signedOut, params?.list?.id, list.id, reloadToken, serverSearch, serverType, serverSort]);

  // Smart rules and their option lists load for editors of a smart list.
  useEffect(() => {
    if (signedOut || !list.id || !list.isSmart || !list.canEdit) return undefined;
    let active = true;
    Promise.all([
      transport.loadSmartRules({ listId: list.id }),
      transport.loadSmartOptions({ listId: list.id }),
    ])
      .then(([rulesPayload, optionsPayload]) => {
        if (!active) return;
        const rules = smartRulesFromPayload(rulesPayload);
        setSmartRules(rules);
        setDraftRules(rules);
        setSmartOptions(smartOptionsFromPayload(optionsPayload));
      })
      .catch(cause => {
        if (active) setNotice(cause?.message || 'The smart rules could not be loaded.');
      });
    return () => { active = false; };
  }, [transport, signedOut, list.id, list.isSmart, list.canEdit, reloadToken]);

  const options = useMemo(() => {
    const mediaTypes = [...knownTypes];
    const statuses = [];
    items.forEach(item => {
      if (item.mediaType && !mediaTypes.some(entry => entry.value === item.mediaType)) {
        mediaTypes.push({ value: item.mediaType, label: item.mediaTypeLabel });
      }
      const value = String(item.status || '').toLowerCase();
      if (value && !statuses.some(entry => entry.value === value)) {
        statuses.push({ value, label: item.statusLabel || item.status });
      }
    });
    return {
      mediaTypes,
      statuses,
      sorts: [
        // The web lists its sort choices alphabetically by label.
        { value: 'custom', label: 'Custom' },
        { value: 'date_added', label: 'Date Added' },
        { value: 'end_date', label: 'End Date' },
        { value: 'media_type', label: 'Media Type' },
        { value: 'progress', label: 'Progress' },
        { value: 'score', label: 'Rating' },
        { value: 'release_date', label: 'Release Date' },
        { value: 'start_date', label: 'Start Date' },
        { value: 'status', label: 'Status' },
        { value: 'title', label: 'Title' },
      ],
      views: [
        { value: 'grid', label: 'Grid' },
        { value: 'table', label: 'Table' },
        ...(isSmart ? [] : [{ value: 'tiers', label: 'Tiers' }]),
      ],
      ranges: [
        { key: 'rating', label: 'Rating', type: 'number', placeholder: '0-10' },
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
  }, [items, isSmart, knownTypes]);

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
      if (filters.statuses.length && !filters.statuses.includes(String(item.status || '').toLowerCase())) {
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
    const sorted = sortItems(filtered, filters);
    if (!canReorder || filters.sort !== 'custom') {
      return sorted;
    }
    return sorted.map(item => ({
      ...item,
      cardActions: {
        title: list.name,
        href: null,
        ordering: null,
        modals: {},
        csrfToken: '',
        clickable: true,
        items: [
          { kind: 'first', title: 'Move to top', glyph: '⤒' },
          { kind: 'back', title: 'Move up', glyph: '↑' },
          { kind: 'next', title: 'Move down', glyph: '↓' },
          { kind: 'last', title: 'Move to bottom', glyph: '⤓' },
        ],
      },
    }));
  }, [items, search, filters, canReorder, list.name]);

  const tierColumns = useMemo(() => tiers.map(tier => ({
    tier,
    items: visibleItems
      .filter(item => item.tier === tier.id)
      .sort((a, b) => (a.tierRank || 0) - (b.tierRank || 0)),
  })), [tiers, visibleItems]);

  const tierUnranked = useMemo(() => visibleItems
    .filter(item => !tiers.some(tier => tier.id === item.tier))
    .sort((a, b) => (a.tierRank || 0) - (b.tierRank || 0)), [tiers, visibleItems]);

  const shareLinks = useMemo(() => shareLinksFor(list), [list.id, list.publicSlug, list.visibility]);

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
    setBulkMessage('');
  }

  function toggleSelectMode() {
    if (selectMode) {
      setSelectedIds([]);
      setBulkMessage('');
    }
    setSelectMode(!selectMode);
  }

  function toggleItem(id) {
    setSelectedIds(current => current.includes(id)
      ? current.filter(value => value !== id)
      : [...current, id]);
    setBulkMessage('');
  }

  async function removeItems(ids) {
    const targets = items.filter(item => ids.includes(item.id));
    if (!targets.length) {
      return;
    }
    const previousItems = items;
    setConfirmRemove(current => ({ ...current, busy: true, error: '' }));
    setItems(current => current.filter(item => !ids.includes(item.id)));
    setSelectedIds([]);
    setBulkMessage('');
    try {
      await Promise.all(targets.map(item => transport.removeItem({ listId: list.id, item })));
      setConfirmRemove({ open: false, ids: [], busy: false, error: '' });
      setNotice(`Removed ${targets.length} item${targets.length === 1 ? '' : 's'} from ${list.name}.`);
      setReloadToken(current => current + 1);
    } catch (cause) {
      setItems(previousItems);
      setConfirmRemove(current => ({
        ...current,
        busy: false,
        error: cause?.message || 'The items could not be removed.',
      }));
    }
  }

  async function runBulkAction(kind, value) {
    const ids = selectedIds;
    if (!ids.length) {
      return;
    }
    const numericIds = ids
      .map(id => items.find(item => item.id === id)?.itemId)
      .filter(itemId => itemId != null);
    if (kind === 'remove') {
      setConfirmRemove({ open: true, ids, busy: false, error: '' });
      return;
    }
    const outcome = response => response?.message
      || `${ids.length} item${ids.length === 1 ? '' : 's'} updated.`;
    try {
      if (kind === 'status') {
        if (!value) {
          setBulkMessage('Choose a status for the selected items.');
          return;
        }
        const previousItems = items;
        setItems(current => current.map(item => (
          ids.includes(item.id) ? { ...item, status: value, statusLabel: value } : item
        )));
        setBulkMessage('');
        try {
          setNotice(outcome(await transport.bulkStatus({ itemIds: numericIds, status: value })));
        } catch (cause) {
          setItems(previousItems);
          throw cause;
        }
        return;
      }
      if (kind === 'collection') {
        setBulkMessage(outcome(await transport.bulkCollection({ itemIds: numericIds })));
        return;
      }
      if (kind === 'list') {
        setBulkMessage(outcome(await transport.bulkList({ itemIds: numericIds, listId: value })));
        return;
      }
      if (kind === 'tag') {
        setBulkMessage(outcome(await transport.bulkTag({ itemIds: numericIds, tagId: value })));
        return;
      }
      setBulkMessage('Add Plays to History is available from the Library toolbar.');
    } catch (cause) {
      setBulkMessage(cause?.message || 'The bulk action failed.');
    }
  }

  // The list and tag pickers of the bulk bar load when selecting starts.
  useEffect(() => {
    if (!selectMode || signedOut) return undefined;
    let active = true;
    Promise.all([transport.load(), transport.loadTags()])
      .then(([listsPayload, tagsPayload]) => {
        if (!active) return;
        const tags = Array.isArray(tagsPayload?.results) ? tagsPayload.results : [];
        setBulkTargets({
          lists: listsFromPayload(listsPayload, getActiveAuthSession()?.user?.username || '')
            .filter(entry => entry.canEdit && !entry.isSmart && entry.id !== String(list.id))
            .map(entry => ({ value: entry.id, label: entry.name })),
          tags: tags.map(tag => ({ value: String(tag.id), label: tag.name })),
        });
      })
      .catch(() => { if (active) setBulkTargets({ lists: [], tags: [] }); });
    return () => { active = false; };
  }, [transport, selectMode, signedOut, list.id]);

  async function changeVisibility(visibility) {
    const previous = list.visibility;
    setList(current => ({ ...current, visibility }));
    try {
      await transport.updateVisibility({ listId: list.id, visibility });
      setNotice(`Visibility set to ${visibility}.`);
    } catch (cause) {
      setList(current => ({ ...current, visibility: previous }));
      setNotice(cause?.message || 'Visibility could not be saved.');
    }
  }

  async function writeMembers(nextMembers, previousMembers, success, failure) {
    setList(current => ({ ...current, members: nextMembers, memberCount: nextMembers.length }));
    try {
      await transport.setMembers({
        listId: list.id,
        collaborators: memberUsernames(nextMembers, 'collaborator'),
        viewers: memberUsernames(nextMembers, 'viewer'),
      });
      setNotice(success);
    } catch (cause) {
      setList(current => ({ ...current, members: previousMembers, memberCount: previousMembers.length }));
      setNotice(cause?.message || failure);
    }
  }

  async function addMember(suggestion) {
    const name = String((typeof suggestion === 'string' ? suggestion : suggestion?.name) || '').trim();
    if (!name || list.members.some(member => member.name.toLowerCase() === name.toLowerCase())) {
      return;
    }
    const member = { id: name.toLowerCase(), name, handle: `@${name}`, role: 'collaborator' };
    await writeMembers(
      [...list.members, member],
      list.members,
      `${name} added as a collaborator.`,
      'The collaborator could not be added.',
    );
    setReloadToken(current => current + 1);
  }

  async function removeMember(id) {
    const member = list.members.find(entry => String(entry.id) === String(id));
    await writeMembers(
      list.members.filter(entry => String(entry.id) !== String(id)),
      list.members,
      `${member?.name || 'Member'} removed.`,
      'The collaborator could not be removed.',
    );
  }

  async function rateItem(item, score) {
    const previousItems = items;
    setItems(current => current.map(entry => (
      entry.id === item.id
        ? {
            ...entry,
            score,
            rating: score == null ? null : {
              ...(entry.rating || { scaleMax: 10 }),
              value: score,
              label: String(score),
            },
          }
        : entry
    )));
    try {
      await transport.rateItem({ item: { identity: item.identity }, score });
    } catch (cause) {
      setItems(previousItems);
      setNotice(cause?.message || 'The rating could not be saved.');
    }
  }

  async function openActivity() {
    setActivity({ open: true, loading: true, error: '', entries: [] });
    try {
      const payload = await transport.loadActivity({ listId: list.id });
      setActivity({ open: true, loading: false, error: '', entries: activityFromPayload(payload) });
    } catch (cause) {
      setActivity({
        open: true,
        loading: false,
        error: cause?.message || 'Activity could not be loaded.',
        entries: [],
      });
    }
  }

  async function openRecommendations({ submitFlow = false } = {}) {
    setRecommendations(current => ({ ...current, loading: true, error: '' }));
    try {
      const payload = await transport.loadRecommendations({ listId: list.id });
      const entries = recommendationsFromPayload(payload);
      setRecommendations({ open: !submitFlow, loading: false, error: '', entries });
    } catch (cause) {
      setRecommendations({
        open: !submitFlow,
        loading: false,
        error: cause?.message || 'Recommendations could not be loaded.',
        entries: [],
      });
    }
  }

  async function decideRecommendation(rec, decision) {
    try {
      await transport.decideRecommendation({
        listId: list.id,
        recommendationId: rec.id,
        decision,
      });
      setRecommendations(current => ({
        ...current,
        entries: current.entries.filter(entry => entry.id !== rec.id),
      }));
      setNotice(decision === 'approve'
        ? `"${rec.title}" was approved and added to the list.`
        : `"${rec.title}" was denied.`);
      setReloadToken(current => current + 1);
    } catch (cause) {
      setNotice(cause?.message || 'The decision could not be saved.');
    }
  }

  function openAddFlow(mode) {
    setAddFlow({ mode, ...SEARCH_IDLE });
    setPreview(null);
  }

  function closeAddFlow() {
    setAddFlow(null);
    setPreview(null);
  }

  function updateAddFlow(patch) {
    setAddFlow(current => ({ ...current, ...patch, page: patch.page ?? 1 }));
  }

  function changeAddQuery(query) {
    updateAddFlow({ query, results: [], status: query.trim().length < 2 ? 'short' : 'loading', error: '' });
  }

  useEffect(() => {
    if (!addFlow || addFlow.query.trim().length < 2) {
      return undefined;
    }
    let active = true;
    const timer = setTimeout(() => {
      transport.searchMedia({
        mediaType: addFlow.mediaType,
        search: addFlow.query.trim(),
        limit: 20,
        offset: (addFlow.page - 1) * 20,
      })
        .then(payload => {
          if (!active) return;
          const pagination = searchPaginationFromPayload(payload);
          const mapped = searchResultsFromPayload(payload).map(row => ({
            ...row,
            media: resultCardModel(row),
            preview: resultPreviewModel(row),
          }));
          setAddFlow(current => ({
            ...current,
            results: mapped,
            totalPages: pagination.totalPages,
            status: 'ready',
            error: '',
          }));
        })
        .catch(cause => {
          if (!active) return;
          setAddFlow(current => ({
            ...current,
            results: [],
            status: 'error',
            error: cause?.message || 'The search could not load.',
          }));
        });
    }, 300);
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [transport, addFlow?.query, addFlow?.mediaType, addFlow?.page]);

  function selectSearchResult(result) {
    const mode = addFlow?.mode || 'add';
    setPreview({
      mode,
      result,
      alreadyInList: items.some(item => sameMedia(item.identity, result)),
      alreadyRecommended: mode === 'recommend'
        && recommendations.entries.some(rec => rec.title === result.title),
    });
  }

  async function confirmPreview() {
    if (!preview || !addFlow) {
      return;
    }
    const { mode, result } = preview;
    try {
      if (mode === 'add') {
        await transport.addItem({ listId: list.id, item: result });
        setNotice(`"${result.title}" was added to the list.`);
        setReloadToken(current => current + 1);
      } else {
        await transport.recommend({ listId: list.id, item: result });
        setNotice(`Your recommendation for "${result.title}" was submitted.`);
        setRecommendations(current => ({ ...current, loading: current.entries.length > 0 }));
      }
      closeAddFlow();
    } catch (cause) {
      setNotice(cause?.message || 'The change could not be saved.');
    }
  }

  async function submitEditForm(values) {
    const name = String(values.name || '').trim();
    if (!name) {
      setFormErrors({ name: 'Enter a list name.' });
      return;
    }
    setSavingForm(true);
    try {
      const byLink = ['public', 'unlisted'].includes(values.visibility);
      await transport.update({
        listId: list.id,
        name,
        description: values.description || '',
        visibility: values.visibility,
        allowRecommendations: values.allowRecommendations,
        tags: values.tags || [],
        includeNotes: values.includeNotes,
        isSmart: Boolean(values.isSmart),
        ...(byLink
          ? { publicSlug: String(values.publicSlug || '').trim().toLowerCase() }
          : {}),
      });
      const same = (left, right) => left.length === right.length && left.every(entry => right.includes(entry));
      const change = {};
      const collaborators = memberUsernames(values.members, 'collaborator');
      const viewers = memberUsernames(values.members, 'viewer');
      if (!same(collaborators, memberUsernames(list.members, 'collaborator'))) change.collaborators = collaborators;
      if (!same(viewers, memberUsernames(list.members, 'viewer'))) change.viewers = viewers;
      if (change.collaborators || change.viewers) {
        await transport.setMembers({ listId: list.id, ...change });
      }
      setNotice(`"${name}" was saved.`);
      setEditOpen(false);
      setReloadToken(current => current + 1);
    } catch (cause) {
      setFormErrors({ form: cause?.message || 'The list could not be saved.' });
    } finally {
      setSavingForm(false);
    }
  }

  async function reorderItem(item, action) {
    if (!canReorder) {
      return;
    }
    const previousItems = items;
    setItems(current => applyLocalMove(current, item.id, action));
    try {
      await transport.reorderItem({ listId: list.id, itemId: item.itemId, action });
    } catch (cause) {
      setItems(previousItems);
      setNotice(cause?.message || 'The order could not be saved.');
    }
  }

  async function deleteList() {
    try {
      await transport.remove({ listId: list.id });
      setEditOpen(false);
      setNotice(`"${list.name}" was deleted.`);
      if (onBack) {
        onBack();
      }
    } catch (cause) {
      setFormErrors({ form: cause?.message || 'The list could not be deleted.' });
    }
  }

  async function reorderTierItem({ itemId, tierId, direction }) {
    if (!canEdit) {
      return;
    }
    const group = items
      .filter(item => item.tier === tierId)
      .sort((a, b) => (a.tierRank || 0) - (b.tierRank || 0));
    const index = group.findIndex(item => item.itemId === itemId);
    const target = group[index + (direction === 'back' ? -1 : 1)];
    if (!target) {
      return;
    }
    const orderedIds = group.map(item => item.itemId);
    const from = orderedIds.indexOf(itemId);
    const to = orderedIds.indexOf(target.itemId);
    orderedIds.splice(to, 0, ...orderedIds.splice(from, 1));
    await moveTierItem({ itemId, tierId, itemIds: orderedIds });
  }

  async function saveTiers(nextTiers) {
    const validIds = new Set(nextTiers.map(tier => tier.id));
    setTierNotice('Saving tier definitions...');
    try {
      await transport.saveTiers({
        listId: list.id,
        tiers: nextTiers.map(tier => ({ id: tier.id, name: tier.name, color: tier.color })),
      });
      setTiers(nextTiers.map(tier => ({ ...tier })));
      setItems(current => current.map(item => (
        validIds.has(item.tier) ? item : { ...item, tier: '', tierRank: 0 }
      )));
      setTierUndo([]);
      setTierNotice('Tier definitions saved.');
    } catch (cause) {
      setTierNotice(cause?.message || 'The tier definitions could not be saved.');
    }
  }

  async function moveTierItem({ itemId, tierId, itemIds }) {
    const order = new Map((itemIds || []).map((id, index) => [id, index]));
    const previousItems = items;
    setItems(current => current.map(item => {
      if (item.itemId === itemId) {
        return { ...item, tier: tierId, tierRank: order.has(item.itemId) ? order.get(item.itemId) + 1 : item.tierRank };
      }
      if (order.has(item.itemId)) {
        return { ...item, tierRank: order.get(item.itemId) + 1 };
      }
      return item;
    }));
    setTierUndo([]);
    setTierNotice('');
    try {
      await transport.moveTierItem({ listId: list.id, itemId, tierId, itemIds: itemIds || [] });
    } catch (cause) {
      setItems(previousItems);
      setTierNotice(cause?.message || 'The tier move could not be saved.');
    }
  }

  async function fillTiersFromRatings() {
    setTierNotice('Filling from ratings...');
    try {
      const payload = await transport.fillFromRatings({ listId: list.id });
      const placements = Array.isArray(payload?.placements) ? payload.placements : [];
      if (!placements.length) {
        setTierNotice('None of the unranked items have a rating.');
        return;
      }
      const tierByItem = new Map(placements.map(entry => [entry.item_id, entry.tier]));
      setItems(current => {
        const counts = {};
        return current.map(item => {
          const tier = tierByItem.get(item.itemId);
          if (!tier) return item;
          counts[tier] = (counts[tier] || 0) + 1;
          return { ...item, tier, tierRank: counts[tier] };
        });
      });
      setTierUndo(placements);
      setTierNotice(`Placed ${placements.length} item${placements.length === 1 ? '' : 's'} from ratings.`);
    } catch (cause) {
      setTierNotice(cause?.message || 'The fill could not be applied.');
    }
  }

  async function undoTierFill() {
    if (!tierUndo.length) {
      return;
    }
    const placements = tierUndo;
    setTierUndo([]);
    setTierNotice('');
    try {
      await transport.undoTierFill({ listId: list.id, placements });
      const cleared = new Set(placements.map(entry => entry.item_id));
      setItems(current => current.map(item => (
        cleared.has(item.itemId) ? { ...item, tier: '', tierRank: 0 } : item
      )));
      setTierNotice('Fill undone.');
    } catch (cause) {
      setTierUndo(placements);
      setTierNotice(cause?.message || 'The undo could not be applied.');
    }
  }

  async function saveRules(rules) {
    setRuleState('saving');
    try {
      const payload = await transport.saveSmartRules({ listId: list.id, rules });
      const next = smartRulesFromPayload(payload) || rules;
      setSmartRules(next);
      setDraftRules(next);
      setRuleState('saved');
      setRulesEditing(false);
      setNotice(`Smart rules saved. ${payload?.items_count ?? 0} items match.`);
      setReloadToken(current => current + 1);
    } catch (cause) {
      setRuleState('error');
      setNotice(cause?.message || 'The smart rules could not be saved.');
    }
  }

  async function syncSmart() {
    try {
      const payload = await transport.syncSmartList({ listId: list.id });
      setNotice(`List synced. ${payload?.items_count ?? 0} items match.`);
      setReloadToken(current => current + 1);
    } catch (cause) {
      setNotice(cause?.message || 'The list could not be synced.');
    }
  }

  function openShareLink(row) {
    const url = shareLinks?.[row.key];
    if (!url) {
      setNotice('Share links need the server address from your session.');
      return;
    }
    setMembersOpen(false);
    Linking.openURL(url).catch(() => setNotice('The link could not be opened.'));
  }

  function openTierExport() {
    const serverUrl = String(getActiveAuthSession()?.serverUrl || '').replace(/\/$/, '');
    if (!serverUrl || !list.id) {
      setTierNotice('The tier image needs the server address from your session.');
      return;
    }
    Linking.openURL(`${serverUrl}/list/${encodeURIComponent(list.id)}/tiers/export.png`)
      .catch(() => setTierNotice('The tier image could not be opened.'));
  }

  function openItem(item) {
    if (navigate) {
      navigate('Detail', { item });
      return;
    }
    setNotice('Item details use the platform navigation adapter.');
  }

  const emptyMode = items.length === 0
    ? 'empty'
    : search.trim() ? 'search'
      : filtersActive(filters) ? 'filters'
        : 'empty';

  const signedOutNotice = signedOut
    ? transport.reason || 'Sign in to your Floppy server to see this list.'
    : '';

  const activityTypeLabel = entry => ACTIVITY_TYPE_LABELS[entry.type] || entry.type;

  async function exportCsv() {
    try {
      const file = await transport.exportList({ listId: list.id });
      await saveTextFile({ name: file.filename, text: file.content, mimeType: 'text/csv' });
      setNotice(`Exported ${file.filename}.`);
    } catch (cause) {
      setNotice(cause?.message || 'The list could not be exported.');
    }
  }

  function openEditForm() {
    setFormErrors({});
    setEditOpen(true);
  }

  async function togglePin() {
    const reference = ['public', 'unlisted'].includes(list.visibility) && list.publicSlug
      ? list.publicSlug : list.id;
    try {
      await toggleSidebarListPin({ id: list.id, name: list.name, url: `/list/${encodeURIComponent(reference)}` });
    } catch (cause) {
      setNotice(cause?.message || 'The sidebar pin could not be updated.');
    }
  }

  const headerActions = list.canRecommend && !isSmart
    ? <Button label="Recommend Item" tone="surface" onPress={() => {
      openAddFlow('recommend');
      openRecommendations({ submitFlow: true });
    }} />
    : null;

  const editList = {
    ...list,
    urlPrefix: String(getActiveAuthSession()?.serverUrl || '').replace(/\/$/, '') ? `${String(getActiveAuthSession()?.serverUrl || '').replace(/\/$/, '')}/lists/` : '',
    currentUrl: ['public', 'unlisted'].includes(list.visibility)
      ? `${String(getActiveAuthSession()?.serverUrl || '').replace(/\/$/, '')}/lists/${list.publicSlug || list.id}`
      : '',
  };

  return <Screen chrome={false}>
    <ListDetailPageView
      header={<View style={styles.header}>
        <ListHeader
          list={list}
          palette={LIST_PALETTE}
          labels={{ more: 'Members' }}
          onAddItem={() => openAddFlow('add')}
          onExport={exportCsv}
          onMore={() => setMembersOpen(true)}
          onEdit={openEditForm}
          trailing={<>
            {canEdit && width >= 640 ? <Pressable accessibilityRole="button" accessibilityState={{ selected: selectMode }}
              onPress={toggleSelectMode} style={styles.selectButton}>
              <Icon spec={actionIcons.tag} color={palette.textSecondary} size={16} />
              <Text style={styles.selectButtonText}>{selectMode ? 'Cancel Select' : 'Select Items'}</Text>
            </Pressable> : null}
            <MediaTypeBreakdown rows={list.mediaTypeBreakdown} />
          </>}
          menu={canEdit ? [
            ...(pinState.scope ? [{ key: 'pin', label: pinState.pins.some(item => String(item.id) === String(list.id)) ? 'Unpin from sidebar' : 'Pin to sidebar', onPress: togglePin }] : []),
            ...(!isSmart ? [{ key: 'add', label: 'Add New Item', onPress: () => openAddFlow('add') }] : []),
            { key: 'edit', label: 'Edit List', onPress: openEditForm },
            { key: 'activity', label: 'View Activity History', onPress: openActivity },
            ...(list.canRecommend ? [{ key: 'recommendations', label: 'View Recommendations', onPress: () => openRecommendations({}) }] : []),
            { key: 'export', label: 'Export as CSV', onPress: exportCsv },
          ] : null} />
        {headerActions ? <View style={styles.headerActions}>{headerActions}</View> : null}
      </View>}
      notice={loading || loadError || notice || signedOutNotice || loadingMore
        ? <View style={styles.noticeRow}>
          <Text style={styles.notice}>
            {loading
              ? 'Loading list…'
              : loadError || signedOutNotice || notice
                || `Loading more items… ${items.length} of ${list.itemsCount || items.length}`}
          </Text>
          {loadError ? <Button label="Try again" tone="surface" onPress={() => setReloadToken(current => current + 1)} /> : null}
        </View>
        : null}
      smart={isSmart && canEdit && smartRules ? <View style={styles.smart}>
        <SmartRuleSummary
          rules={smartRules}
          options={smartOptions || {}}
          editMode={rulesEditing}
          saveState={ruleState}
          palette={LIST_PALETTE} />
        <View style={styles.headerActions}>
          <Button
            label={rulesEditing ? 'Cancel' : 'Edit Smart Rules'}
            tone="surface"
            onPress={() => {
              setDraftRules(smartRules);
              setRuleState('idle');
              setRulesEditing(current => !current);
            }} />
          <Button label="Sync now" tone="surface" onPress={syncSmart} />
        </View>
        {rulesEditing ? <SmartRuleBuilder
          rules={draftRules || smartRules}
          options={smartOptions || {}}
          editMode
          canEdit
          saveState={ruleState}
          palette={LIST_PALETTE}
          onChange={setDraftRules}
          onSave={saveRules}
          onCancel={() => {
            setRulesEditing(false);
            setDraftRules(smartRules);
          }} /> : null}
      </View> : null}
      controls={<View style={styles.controls}>
        <View style={styles.searchRow}>
          <SearchIcon color={palette.textMuted} size={20} />
          <TextInput
            style={[styles.search, styles.searchGrow]}
            placeholder="Search this list or recommend something..."
            placeholderTextColor={palette.textMuted}
            value={search}
            onChangeText={setSearch}
            autoCorrect={false}
            accessibilityLabel="Search this list" />
        </View>
        <FilterBar
          variant="toolbar"
          filters={filters}
          options={options}
          palette={FILTER_PALETTE}
          labels={{
            filters: 'Filters',
            status: 'Status',
            allStatuses: 'Status',
            statuses: 'Statuses',
            sort: 'Sort',
            range: 'Range',
          }}
          trailing={<ViewToggle
            options={options.views.map(view => ({
              ...view,
              icon: view.value === 'grid' ? 'grid' : view.value === 'table' ? 'table' : 'list',
            }))}
            value={filters.view}
            palette={FILTER_PALETTE}
            onChange={value => changeFilters({ type: 'set', key: 'view', value })} />}
          onChange={changeFilters} />
      </View>}
      content={filters.view === 'tiers' && !isSmart ? <>
        {selectMode ? <ListBulkBar count={selectedIds.length} palette={LIST_PALETTE}
          statuses={BULK_STATUSES} lists={bulkTargets.lists} tags={bulkTargets.tags}
          onClear={() => { setSelectedIds([]); setBulkMessage(''); }} onAction={runBulkAction}
          onRemove={() => removeItems(selectedIds)} /> : null}
        {bulkMessage ? <Text style={styles.notice}>{bulkMessage}</Text> : null}
        <TierBoard
        tiers={tiers}
        columns={tierColumns}
        unranked={tierUnranked}
        canEdit={canEdit}
        canFill={canEdit}
        maxTiers={12}
        notice={tierNotice}
        undoAvailable={tierUndo.length > 0}
        palette={LIST_PALETTE}
        onSaveTiers={saveTiers}
        onMoveItem={moveTierItem}
        onReorderItem={reorderTierItem}
        onFillFromRatings={fillTiersFromRatings}
        onUndoFill={undoTierFill}
        onExport={openTierExport}
        onOpenItem={openItem} /></> : <ListResults
        items={visibleItems}
        layout={filters.view}
        sort={filters.sort}
        palette={LIST_PALETTE}
        canEdit={canEdit}
        showSelectToggle={false}
        canRecommend={!!list.canRecommend}
        isSmart={isSmart}
        selectMode={selectMode}
        selectedIds={selectedIds}
        onToggleItem={toggleItem}
        onToggleSelectMode={toggleSelectMode}
        onClearSelection={() => {
          setSelectedIds([]);
          setBulkMessage('');
        }}
        onBulkAction={runBulkAction}
        bulkStatuses={BULK_STATUSES}
        bulkLists={bulkTargets.lists}
        bulkTags={bulkTargets.tags}
        onRemoveItems={removeItems}
        bulkMessage={bulkMessage}
        onOpenItem={openItem}
        onRate={rateItem}
        onAction={reorderItem}
        emptyMode={emptyMode}
        hasSearch={!!search.trim()}
        onRecommend={() => openAddFlow('recommend')}
        onBrowse={() => navigate?.('Search', { query: '' })} />}
      dialogs={<>
        <ListMembershipPopup
          open={membersOpen}
          list={{ ...list, links: shareLinks }}
          palette={LIST_PALETTE}
          suggestions={[]}
          allowUsernameEntry
          onClose={() => setMembersOpen(false)}
          onChangeVisibility={changeVisibility}
          onAddMember={addMember}
          onRemoveMember={removeMember}
          onOpenLink={openShareLink} />

        {editOpen ? <ListForm
          key={list.id || 'edit'}
          mode="edit"
          list={editList}
          tagSuggestions={[]}
          collaboratorSuggestions={[]}
          errors={formErrors}
          pending={savingForm}
          canDelete={!!list.canDelete}
          palette={palette}
          onSubmit={submitEditForm}
          onDelete={deleteList}
          onClose={() => setEditOpen(false)} /> : null}

        {addFlow && !preview ? <ListItemSearch
          mode={addFlow.mode}
          listName={list.name}
          query={addFlow.query}
          mediaType={addFlow.mediaType}
          mediaTypes={SEARCH_MEDIA_TYPES}
          results={addFlow.results}
          status={addFlow.status}
          error={addFlow.error}
          page={addFlow.page}
          totalPages={addFlow.totalPages}
          palette={palette}
          onQueryChange={changeAddQuery}
          onMediaTypeChange={value => updateAddFlow({ mediaType: value, status: 'idle', results: [] })}
          onPage={page => updateAddFlow({ page })}
          onSelectResult={selectSearchResult}
          onClose={closeAddFlow} /> : null}

        {preview ? <ListItemPreview
          open
          mode={preview.mode}
          media={resultPreviewModel(preview.result)}
          alreadyInList={preview.alreadyInList}
          alreadyRecommended={preview.alreadyRecommended}
          palette={palette}
          onConfirm={confirmPreview}
          onClose={() => setPreview(null)} /> : null}

        {activity.open ? <DialogFrame
          title="Activity History"
          subtitle={`View recent activity for "${list.name}"`}
          onClose={() => setActivity(current => ({ ...current, open: false }))}>
          {activity.loading ? <Text style={[styles.dialogBody, { color: palette.textMuted }]}>Loading activity…</Text> : null}
          {activity.error ? <Text style={[styles.dialogBody, { color: palette.danger }]}>{activity.error}</Text> : null}
          {!activity.loading && !activity.error && activity.entries.length === 0 ? <View style={styles.dialogEmpty}>
            <Text style={[styles.dialogEmptyTitle, { color: palette.text }]}>No activity yet</Text>
            <Text style={[styles.dialogBody, { color: palette.textMuted }]}>
              Activity history will appear here as items are added or removed from the list.
            </Text>
          </View> : null}
          {activity.entries.map(entry => <View key={entry.id} style={[styles.activityRow, { borderColor: palette.border }]}>
            <Text style={[styles.activityText, { color: palette.text }]}>{entry.description}</Text>
            <Text style={[styles.activityMeta, { color: palette.textMuted }]}>
              {entry.timestampLabel} · {entry.agoLabel} ago
            </Text>
          </View>)}
        </DialogFrame> : null}

        {recommendations.open ? <ListRecommendations
          listName={list.name}
          recommendations={recommendations.entries}
          canEdit={canEdit}
          status={recommendations.loading ? 'loading' : recommendations.error ? 'error' : 'ready'}
          error={recommendations.error}
          palette={palette}
          onApprove={rec => decideRecommendation(rec, 'approve')}
          onDeny={rec => decideRecommendation(rec, 'deny')}
          onView={rec => {
            setRecommendations(current => ({ ...current, open: false }));
            if (rec?.identity?.source && rec?.identity?.mediaId) {
              navigate?.('Detail', { item: { identity: rec.identity, title: rec.title } });
            }
          }}
          onClose={() => setRecommendations(current => ({ ...current, open: false }))} /> : null}

        <ConfirmDialog
          visible={confirmRemove.open}
          title="Remove from List"
          message={confirmRemove.ids.length
            ? `Remove ${confirmRemove.ids.length} item${confirmRemove.ids.length === 1 ? '' : 's'} from "${list.name}"?`
            : ''}
          confirmLabel="Remove"
          cancelLabel="Keep"
          busy={confirmRemove.busy}
          error={confirmRemove.error}
          palette={palette}
          onCancel={() => setConfirmRemove({ open: false, ids: [], busy: false, error: '' })}
          onConfirm={() => removeItems(confirmRemove.ids)} />
      </>}
    />
  </Screen>;
}

const styles = StyleSheet.create({
  header: { gap: spacing.sm },
  smart: { gap: spacing.sm },
  noticeRow: { gap: spacing.sm, alignItems: 'flex-start' },
  headerActions: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm },
  selectButton: { height: 40, flexDirection: 'row', alignItems: 'center', gap: 8, paddingHorizontal: 12, borderWidth: 1, borderColor: palette.border, borderRadius: radius.sm, backgroundColor: palette.surfaceStrong },
  selectButtonText: { color: palette.textSecondary, fontSize: 14 },
  controls: { gap: spacing.md },
  searchRow: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm, backgroundColor: palette.surfaceStrong, borderRadius: radius.sm, paddingLeft: spacing.sm },
  searchGrow: { flex: 1, minWidth: 0 },
  breakdownButton: {
    width: 40,
    height: 40,
    alignItems: 'center',
    justifyContent: 'center',
    borderWidth: 1,
    borderColor: palette.border,
    borderRadius: radius.sm,
    backgroundColor: palette.surface,
  },
  breakdownBackdrop: { flex: 1, justifyContent: 'center', alignItems: 'center', padding: spacing.lg },
  breakdownPanel: {
    width: 256,
    padding: spacing.md,
    gap: spacing.xs,
    borderWidth: 1,
    borderColor: palette.border,
    borderRadius: radius.md,
    backgroundColor: palette.background,
  },
  breakdownTitle: { color: palette.textMuted, fontSize: 11, fontWeight: '600', letterSpacing: 0.6, marginBottom: spacing.xs },
  breakdownBar: { flexDirection: 'row', height: 12, borderRadius: radius.pill, overflow: 'hidden', backgroundColor: palette.surfaceStrong, marginBottom: spacing.sm },
  breakdownRow: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm, paddingVertical: 2 },
  breakdownDot: { width: 12, height: 12, borderRadius: 6 },
  breakdownLabel: { flex: 1, color: palette.textSecondary, fontSize: 14 },
  breakdownCount: { color: palette.textMuted, fontSize: 14 },
  breakdownPercent: { color: palette.textMuted, fontSize: 12, width: 34, textAlign: 'right' },
  search: {
    backgroundColor: palette.surfaceStrong,
    color: palette.text,
    borderRadius: radius.sm,
    paddingHorizontal: spacing.sm,
    paddingVertical: spacing.sm,
  },
  notice: { color: palette.textMuted, fontSize: 12, lineHeight: 17 },
  dialogOverlay: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: spacing.lg },
  dialogPanel: { width: '100%', maxWidth: 560, maxHeight: '88%', borderWidth: 1, borderRadius: radius.md, padding: spacing.md, gap: spacing.sm },
  dialogHeader: { flexDirection: 'row', alignItems: 'flex-start', justifyContent: 'space-between', gap: spacing.sm },
  dialogHeading: { flex: 1, minWidth: 0, gap: 2 },
  dialogTitle: { fontSize: 20, fontWeight: '700' },
  dialogSubtitle: { fontSize: 12, lineHeight: 17 },
  dialogBody: { fontSize: 13, lineHeight: 18 },
  dialogEmpty: { alignItems: 'center', gap: 6, paddingVertical: 24 },
  dialogEmptyTitle: { fontSize: 16, fontWeight: '600' },
  activityRow: { borderTopWidth: 1, paddingTop: spacing.sm, gap: 2 },
  activityText: { fontSize: 13, lineHeight: 18 },
  activityMeta: { fontSize: 12, lineHeight: 16 },
});
