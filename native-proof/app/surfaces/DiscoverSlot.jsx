import React, { useEffect, useRef, useState } from 'react';
import { DiscoverView } from '../../../frontend/pages/DiscoverView';
import { defaultLabels } from '../../../frontend/discover/DiscoverScreen';
import { mediaCardPalette, palette } from '../theme';
import { getActiveAuthSession } from '../data/authSession';

export const surface = {
  id: 'DISCOVER',
  title: 'Discover rows, tabs and feedback',
  where: 'Discover',
  status: 'ported',
  note: 'The shared DiscoverView owns the page heading/toolbar order, tabs, recommendation rails, hidden grid, feedback and empty/loading states; this slot keeps the demo candidates, local planning/hide/Undo state and navigation intents. The web page still mounts the same shared row/feedback/state sections inside its Alpine-owned chrome because the row islands keep the pre-mount grid measurement; a page-level web adapter needs JSON row props. iOS, Android, browser interaction and screen-reader passes were not run; the Expo export is a compile check.',
};

const DISCOVER_MEDIA_TYPES = new Set(['movie', 'tv', 'anime', 'manga', 'game', 'book', 'comic', 'boardgame', 'music', 'podcast']);

const DEFAULT_MEDIA_OPTIONS = [
  { value: 'all', label: 'All Media' },
  { value: 'movie', label: 'Movies' },
  { value: 'tv', label: 'TV Shows' },
  { value: 'anime', label: 'Anime' },
  { value: 'book', label: 'Books' },
  { value: 'game', label: 'Games' },
  { value: 'hidden', label: 'Hidden' },
];

const labels = {
  ...defaultLabels,
  mediaType: 'Media type',
  showMore: 'Show More Rows',
  showFewer: 'Show Fewer Rows',
  hiddenTitle: 'Hidden From Discover',
  hiddenBody: 'Most recently changed first, so forgotten hides are easy to find again.',
  hiddenEmptyTitle: 'Nothing hidden right now',
  hiddenEmptyBody: 'Items you hide from Discover will show up here.',
  emptyTitle: 'No Discover rows available',
  emptyBody: 'Try another media type or start tracking more items.',
  loadingTitle: 'Building Discover rows',
  loadingBody: 'Recommendations are refreshing in the background and will appear automatically.',
  refreshBackground: 'Refreshing recommendations in background...',
  refreshDone: 'Recommendations refreshed.',
  undo: 'Undo',
  dismiss: 'Dismiss',
  rate: 'Rate',
  close: 'Close',
  open: 'Open',
  altTitle: 'Show alternative title',
  nextEpisode: 'Jump to next episode',
  noStatus: 'No Status',
};

function card({ id, title, meta, mediaType = 'movie', score, rowKey }) {
  return {
    mediaType,
    shape: mediaType === 'music' || mediaType === 'podcast' ? 'square' : 'poster',
    image: { src: null, fallback: '' },
    title,
    altTitle: null,
    statusChip: null,
    cornerChips: [],
    titleLinks: [],
    progressBar: null,
    lines: [{ parts: [{ text: meta }] }],
    actions: {
      href: '',
      clickable: true,
      items: [
        { kind: 'post', action: 'planning', tone: 'emerald', title: 'Add to Planning', glyph: '＋' },
        { kind: 'post', action: 'dismiss', tone: 'rose', title: 'Hide from Discover', glyph: '⦸' },
      ],
    },
    cardKey: id,
    rowKey,
    rating: score ? { label: String(score), value: score, scaleMax: 10, rateLabel: 'Rate' } : null,
    ratingEditable: false,
    csrfToken: '',
  };
}

function hiddenCard({ id, title, meta, mediaType = 'movie' }) {
  return {
    ...card({ id: `hidden-${id}`, title, meta, mediaType }),
    lines: [{ parts: [{ text: meta }] }],
    actions: {
      href: '',
      clickable: true,
      items: [
        { kind: 'post', action: 'unhide', tone: 'indigo', title: 'Unhide from Discover', glyph: '↺' },
      ],
    },
  };
}

const initialRows = [
  {
    key: 'top_picks_for_you',
    title: 'Top Picks For You',
    why: 'Tailored picks from what you finish and rewatch.',
    matchSignal: 'Strong genre and era alignment',
    items: [
      card({ id: 'arrival', title: 'Arrival', meta: '2016 · 88% Taste match', score: 8.8, rowKey: 'top_picks_for_you' }),
      card({ id: 'severance', title: 'Severance', meta: 'S2 · 84% Taste match', mediaType: 'tv', score: 8.4, rowKey: 'top_picks_for_you' }),
      card({ id: 'piranesi', title: 'Piranesi', meta: '2020 · 91% Taste match', mediaType: 'book', score: 9.1, rowKey: 'top_picks_for_you' }),
      card({ id: 'hades', title: 'Hades', meta: '2020 · 86% Taste match', mediaType: 'game', score: 8.6, rowKey: 'top_picks_for_you' }),
    ],
  },
  {
    key: 'clear_out_next',
    title: 'Clear Out Next',
    why: 'Short commitments already waiting in your watchlist.',
    matchSignal: 'Ready now',
    items: [
      card({ id: 'past-lives', title: 'Past Lives', meta: '2023 · 79% Next up match', score: 7.9, rowKey: 'clear_out_next' }),
      card({ id: 'blue-eye', title: 'Blue Eye Samurai', meta: 'S1 · 81% Next up match', mediaType: 'anime', score: 8.1, rowKey: 'clear_out_next' }),
      card({ id: 'andor', title: 'Andor', meta: 'S2 · 77% Next up match', mediaType: 'tv', score: 7.7, rowKey: 'clear_out_next' }),
    ],
  },
  {
    key: 'comfort_rewatches',
    title: 'Comfort Rewatches',
    why: 'Familiar favourites you return to without regret.',
    matchSignal: 'Rewatch strength high',
    items: [
      card({ id: 'the-bear', title: 'The Bear', meta: 'S3 · 92% Rewatch confidence', mediaType: 'tv', score: 9.2, rowKey: 'comfort_rewatches' }),
      card({ id: 'dune-two', title: 'Dune: Part Two', meta: '2024 · 90% Rewatch confidence', score: 9.0, rowKey: 'comfort_rewatches' }),
      card({ id: 'children-of-men', title: 'Children of Men', meta: '2006 · 85% Rewatch confidence', score: 8.5, rowKey: 'comfort_rewatches' }),
    ],
  },
  {
    key: 'coming_soon',
    title: 'Coming Soon',
    why: 'Upcoming releases that match your taste.',
    matchSignal: null,
    items: [
      card({ id: 'the-last-of-us-s3', title: 'The Last of Us', meta: '2027 · Anticipation', mediaType: 'tv', rowKey: 'coming_soon' }),
      card({ id: 'blade-runner-2099', title: 'Blade Runner 2099', meta: '2026 · Anticipation', mediaType: 'tv', rowKey: 'coming_soon' }),
      card({ id: 'project-hail-mary', title: 'Project Hail Mary', meta: '2026 · Anticipation', rowKey: 'coming_soon' }),
    ],
  },
];

const initialHidden = [
  hiddenCard({ id: 'morbius', title: 'Morbius', meta: 'Hidden 2 days ago' }),
  hiddenCard({ id: 'rebel-moon', title: 'Rebel Moon', meta: 'Hidden 5 days ago' }),
];

export function useDiscoverSurface({ navigate } = {}) {
  const [selectedMedia, setSelectedMedia] = useState('all');
  const [showMore, setShowMore] = useState(false);
  const [rows, setRows] = useState(initialRows);
  const [hidden, setHidden] = useState(initialHidden);
  const [refreshing, setRefreshing] = useState(false);
  const [cacheRefreshing, setCacheRefreshing] = useState(false);
  const [refreshStatus, setRefreshStatus] = useState({ visible: false, message: '' });
  const [toast, setToast] = useState({ visible: false, message: '', undoToken: '' });
  const [mediaOptions, setMediaOptions] = useState(DEFAULT_MEDIA_OPTIONS);
  const snapshot = useRef(null);
  const refreshTimer = useRef(null);
  const statusTimer = useRef(null);
  const toastTimer = useRef(null);

  useEffect(() => {
    const auth = getActiveAuthSession();
    if (!auth || typeof auth.request !== 'function') return undefined;
    let cancelled = false;
    auth.request('/api/v1/user/navigation/').then(nav => {
      if (cancelled) return;
      const types = (nav.primary || [])
        .filter(item => item.href?.startsWith('/medialist/'))
        .map(item => ({ value: item.href.split('/').pop(), label: item.label }))
        .filter(item => DISCOVER_MEDIA_TYPES.has(item.value));
      if (types.length) {
        setMediaOptions([{ value: 'all', label: 'All Media' }, ...types, { value: 'hidden', label: 'Hidden' }]);
      }
    }).catch(() => {});
    return () => { cancelled = true; };
  }, []);

  useEffect(() => () => {
    clearTimeout(refreshTimer.current);
    clearTimeout(statusTimer.current);
    clearTimeout(toastTimer.current);
  }, []);

  function dismissRefreshStatus() {
    clearTimeout(statusTimer.current);
    setRefreshStatus({ visible: false, message: '' });
  }

  function dismissToast() {
    clearTimeout(toastTimer.current);
    setToast({ visible: false, message: '', undoToken: '' });
  }

  function showToast(message, undoToken) {
    clearTimeout(toastTimer.current);
    setToast({ visible: true, message, undoToken: undoToken || '' });
    toastTimer.current = setTimeout(dismissToast, 8000);
  }

  function refresh() {
    if (refreshing) return;
    setRefreshing(true);
    setCacheRefreshing(true);
    clearTimeout(refreshTimer.current);
    refreshTimer.current = setTimeout(() => {
      setRefreshing(false);
      setCacheRefreshing(false);
      setRefreshStatus({ visible: true, message: labels.refreshDone });
      clearTimeout(statusTimer.current);
      statusTimer.current = setTimeout(dismissRefreshStatus, 5000);
    }, 900);
  }

  function removeFromRows(cardItem) {
    snapshot.current = { rows, hidden };
    setRows(current => current
      .map(row => ({ ...row, items: row.items.filter(item => item.cardKey !== cardItem.cardKey) }))
      .filter(row => row.items.length));
  }

  function runAction(cardItem, action) {
    if (!action) return;
    if (action.action === 'planning') {
      removeFromRows(cardItem);
      showToast(`Added "${cardItem.title}" to Planning.`, 'demo-undo');
      return;
    }
    if (action.action === 'dismiss') {
      removeFromRows(cardItem);
      setHidden(current => [
        hiddenCard({ id: cardItem.cardKey, title: cardItem.title, meta: 'Hidden just now', mediaType: cardItem.mediaType }),
        ...current,
      ]);
      showToast(`Hidden "${cardItem.title}" from Discover.`, 'demo-undo');
      return;
    }
    if (action.action === 'unhide') {
      const restored = hidden.find(item => item.cardKey === cardItem.cardKey);
      snapshot.current = { rows, hidden };
      setHidden(current => current.filter(item => item.cardKey !== cardItem.cardKey));
      showToast(`Unhid "${cardItem.title}" from Discover.`, restored ? 'demo-undo' : '');
    }
  }

  function undo() {
    if (!snapshot.current) {
      dismissToast();
      return;
    }
    setRows(snapshot.current.rows);
    setHidden(snapshot.current.hidden);
    snapshot.current = null;
    dismissToast();
  }

  const isHidden = selectedMedia === 'hidden';
  const filteredRows = rows
    .map(row => selectedMedia === 'all'
      ? row
      : { ...row, items: row.items.filter(item => item.mediaType === selectedMedia) })
    .filter(row => row.items.length);
  const visibleRows = showMore ? filteredRows : filteredRows.slice(0, 2);

  return {
    mediaOptions,
    selectedMediaType: selectedMedia,
    onSelectMedia: setSelectedMedia,
    showMore,
    onToggleShowMore: () => setShowMore(current => !current),
    onRefresh: refresh,
    refreshing,
    cacheRefreshing,
    refreshStatus,
    toast,
    rows: visibleRows,
    hidden: { entries: hidden, count: hidden.length },
    loading: false,
    labels,
    palette: { ...palette, ...mediaCardPalette, arrow: palette.textSecondary, arrowDisabled: palette.surfaceMuted, loading: palette.accent, focus: palette.accent },
    onOpenCard: () => navigate?.('Detail'),
    onAction: runAction,
    onUndo: undo,
    onDismissRefreshStatus: dismissRefreshStatus,
    onDismissToast: dismissToast,
  };
}

export default function DiscoverSlot({ navigate }) {
  const props = useDiscoverSurface({ navigate });
  return <DiscoverView {...props} palette={props.palette} />;
}
