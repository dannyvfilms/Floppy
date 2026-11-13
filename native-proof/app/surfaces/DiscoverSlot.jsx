import React, { useEffect, useMemo, useRef, useState } from 'react';
import { useWindowDimensions } from 'react-native';
import { actionIcons } from '../../../frontend/ui/actionIcons';
import { Icon } from '../../../frontend/ui/Icon';
import { useAccountDisplay } from '../data/accountDisplay';
import { DiscoverView } from '../../../frontend/pages/DiscoverView';
import { createListTransport } from '../data/listTransport';
import { DiscoverListPicker } from './DiscoverListPicker';
import { defaultLabels } from '../../../frontend/discover/DiscoverScreen';
import { mediaCardPalette, palette } from '../theme';
import { getActiveAuthSession, subscribeAuthSession } from '../data/authSession';
import { listsFromPayload } from '../data/listTransportCore';
import {
  createDiscoverTransport,
  discoverMediaOptionsFromPayload,
  discoverRowsFromPayload,
  hiddenFromPayload,
} from '../data/discoverTransport';

const STATUS_POLL_MS = 4000;
const STATUS_POLL_LIMIT = 30;

export const surface = {
  id: 'DISCOVER',
  title: 'Discover rows, tabs and feedback',
  where: 'Discover',
  status: 'in_progress',
  note: 'The shared DiscoverView owns the page heading/toolbar order, tabs, recommendation rails, hidden grid, feedback and empty/loading/error states. Rows, the media-type chips and the rebuilding flag come from /api/v1/discover/; the hidden grid (with artwork) from /api/v1/discover/hidden/. Refresh queues /api/v1/discover/refresh/ and polls /api/v1/discover/status/ until the rebuild finishes, then reloads. Planning posts the candidate to /api/v1/media/{type}/ and its undo deletes that entry. Hide sends the candidate identity to /api/v1/discover/hidden/ and undo unhides the returned item id; unhide undo hides it again. The screen follows sign-in changes. Browser interaction and iOS/Android runtime passes were not run.',
};

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

export function useDiscoverSurface({ navigate, transport: injectedTransport } = {}) {
  const [session, setSession] = useState(() => getActiveAuthSession());
  useEffect(() => subscribeAuthSession(setSession), []);
  const transport = useMemo(
    () => injectedTransport || createDiscoverTransport(session ? { auth: session } : {}),
    [injectedTransport, session],
  );
  const serverMode = transport.mode === 'server';
  const [selectedMedia, setSelectedMedia] = useState('all');
  const [showMore, setShowMore] = useState(false);
  const [rawRows, setRows] = useState([]);
  const { width } = useWindowDimensions();
  const display = useAccountDisplay();
  // The web card hides its year and match line on a compact phone grid.
  const bare = width <= 768 && display.compact;
  const rows = useMemo(() => (bare
    ? rawRows.map(row => ({ ...row, items: row.items.map(item => ({ ...item, lines: [] })) }))
    : rawRows), [rawRows, bare]);
  const [hidden, setHidden] = useState([]);
  const [loading, setLoading] = useState(serverMode);
  const [building, setBuilding] = useState(false);
  const [error, setError] = useState('');
  const [reloadToken, setReloadToken] = useState(0);
  const [refreshing, setRefreshing] = useState(false);
  const [refreshStatus, setRefreshStatus] = useState({ visible: false, message: '' });
  const [toast, setToast] = useState({ visible: false, message: '', undoToken: '' });
  const [mediaOptions, setMediaOptions] = useState(discoverMediaOptionsFromPayload());
  const [listPicker, setListPicker] = useState(null);
  const undoAction = useRef(null);
  const announceDone = useRef(false);
  const statusTimer = useRef(null);
  const toastTimer = useRef(null);
  const apiMedia = selectedMedia === 'hidden' ? 'all' : selectedMedia;

  useEffect(() => {
    if (!serverMode) {
      setRows([]);
      setHidden([]);
      setLoading(false);
      setError('Sign in to your Floppy server to load Discover.');
      return undefined;
    }
    let active = true;
    setLoading(true);
    setError('');
    Promise.all([
      transport.loadRows({ mediaType: apiMedia, showMore }),
      transport.loadHidden(),
    ]).then(([rowsPayload, hiddenPayload]) => {
      if (!active) return;
      setRows(discoverRowsFromPayload(rowsPayload));
      setHidden(hiddenFromPayload(hiddenPayload));
      setMediaOptions(discoverMediaOptionsFromPayload(rowsPayload));
      setBuilding(!!rowsPayload?.loading);
      setLoading(false);
    }).catch(cause => {
      if (!active) return;
      setRows([]);
      setHidden([]);
      setError(cause?.message || 'Discover could not be loaded from the server.');
      setLoading(false);
    });
    return () => { active = false; };
  }, [transport, serverMode, apiMedia, showMore, reloadToken]);

  // The server rebuilds a tab in the background; poll its status like the web
  // page does, then reload once the rows are ready.
  useEffect(() => {
    if (!serverMode || !building) return undefined;
    let active = true;
    let attempts = 0;
    const timer = setInterval(() => {
      attempts += 1;
      transport.loadStatus({ mediaType: apiMedia, showMore }).then(status => {
        if (!active) return;
        if (!status?.is_refreshing || attempts >= STATUS_POLL_LIMIT) {
          setBuilding(false);
          if (announceDone.current) {
            announceDone.current = false;
            setRefreshStatus({ visible: true, message: labels.refreshDone });
            clearTimeout(statusTimer.current);
            statusTimer.current = setTimeout(dismissRefreshStatus, 5000);
          }
          setReloadToken(current => current + 1);
        }
      }).catch(() => {
        if (active && attempts >= STATUS_POLL_LIMIT) setBuilding(false);
      });
    }, STATUS_POLL_MS);
    return () => { active = false; clearInterval(timer); };
  }, [serverMode, building, transport, apiMedia, showMore]);

  useEffect(() => () => {
    clearTimeout(statusTimer.current);
    clearTimeout(toastTimer.current);
  }, []);

  function dismissRefreshStatus() {
    clearTimeout(statusTimer.current);
    setRefreshStatus({ visible: false, message: '' });
  }

  function dismissToast() {
    clearTimeout(toastTimer.current);
    undoAction.current = null;
    setToast({ visible: false, message: '', undoToken: '' });
  }

  function showToast(message, undo) {
    clearTimeout(toastTimer.current);
    undoAction.current = undo || null;
    setToast({ visible: true, message, undoToken: undo ? undo.kind : '' });
    toastTimer.current = setTimeout(dismissToast, 8000);
  }

  function reload() {
    setReloadToken(current => current + 1);
  }

  function refresh() {
    if (refreshing || !serverMode) return;
    setRefreshing(true);
    setError('');
    transport.refresh({ mediaType: apiMedia, showMore })
      .then(() => {
        announceDone.current = true;
        setBuilding(true);
      })
      .catch(cause => setError(cause?.message || 'Discover could not be refreshed.'))
      .finally(() => setRefreshing(false));
  }

  function removeFromRows(cardItem) {
    setRows(current => current
      .map(row => ({ ...row, items: row.items.filter(item => item.cardKey !== cardItem.cardKey) }))
      .filter(row => row.items.length));
  }

  function runAction(cardItem, action) {
    if (!action) return;
    if (!serverMode) {
      showToast('Sign in to use Discover actions.');
      return;
    }
    const identity = cardItem.identity || {};
    if (action.action === 'lists') {
      openListPicker(cardItem);
      return;
    }
    if (action.action === 'planning') {
      removeFromRows(cardItem);
      transport.plan({
        mediaType: identity.mediaType || cardItem.mediaType,
        source: identity.source,
        mediaId: identity.mediaId,
        title: cardItem.title,
        image: identity.image || cardItem.image?.src,
      }).then(() => {
        showToast(`Added "${cardItem.title}" to Planning.`, {
          kind: 'plan',
          mediaType: identity.mediaType || cardItem.mediaType,
          source: identity.source,
          mediaId: identity.mediaId,
        });
      }).catch(cause => {
        reload();
        showToast(cause?.message || `Could not add "${cardItem.title}" to Planning.`);
      });
      return;
    }
    if (action.action === 'dismiss') {
      if (!cardItem.itemId && !identity.mediaId) {
        showToast('This Discover row does not expose an item identity, so it cannot be hidden.');
        return;
      }
      removeFromRows(cardItem);
      transport.hide({
        itemId: cardItem.itemId,
        identity,
        title: cardItem.title,
        image: identity.image || cardItem.image?.src,
      }).then(result => {
        showToast(`Hidden "${cardItem.title}" from Discover.`, {
          kind: 'hide',
          itemId: result?.item_id ?? cardItem.itemId,
        });
      }).catch(cause => {
        reload();
        showToast(cause?.message || `Could not hide "${cardItem.title}".`);
      });
      return;
    }
    if (action.action === 'unhide') {
      setHidden(current => current.filter(item => item.cardKey !== cardItem.cardKey));
      transport.unhide({ itemId: cardItem.itemId }).then(() => {
        showToast(`Unhid "${cardItem.title}" from Discover.`, {
          kind: 'unhide',
          itemId: cardItem.itemId,
        });
        reload();
      }).catch(cause => {
        reload();
        showToast(cause?.message || `Could not unhide "${cardItem.title}".`);
      });
    }
  }

  // "Add to custom lists": the lists the account can edit, then a PUT for the
  // chosen one (the same route the web's list modal toggles).
  function openListPicker(cardItem) {
    const lists = createListTransport(session ? { auth: session } : {});
    setListPicker({ card: cardItem, title: cardItem.title, lists: [], loading: true, error: '', savingId: null });
    lists.load().then(payload => {
      const rows = listsFromPayload(payload, session?.user?.username).filter(list => list.canEdit && !list.isSmart);
      setListPicker(current => (current ? { ...current, lists: rows, loading: false } : current));
    }).catch(cause => {
      setListPicker(current => (current ? { ...current, loading: false, error: cause?.message || 'Your lists could not be loaded.' } : current));
    });
  }

  function chooseList(list) {
    const target = listPicker?.card;
    if (!target) return;
    setListPicker(current => ({ ...current, savingId: list.id, error: '' }));
    createListTransport(session ? { auth: session } : {}).addItem({ listId: list.id, item: target }).then(() => {
      setListPicker(null);
      showToast(`Added "${target.title}" to ${list.name}.`);
    }).catch(cause => {
      setListPicker(current => (current ? { ...current, savingId: null, error: cause?.message || `Could not add "${target.title}" to ${list.name}.` } : current));
    });
  }

  function undo() {
    const pending = undoAction.current;
    dismissToast();
    if (!pending || !serverMode) return;
    let request;
    if (pending.kind === 'plan') request = transport.unplan(pending);
    else if (pending.kind === 'hide') request = transport.unhide({ itemId: pending.itemId });
    else request = transport.hide({ itemId: pending.itemId });
    request
      .catch(cause => showToast(cause?.message || 'Could not undo that change.'))
      .finally(reload);
  }

  return {
    mediaOptions,
    selectedMediaType: selectedMedia,
    onSelectMedia: setSelectedMedia,
    showMore,
    onToggleShowMore: () => setShowMore(current => !current),
    onRefresh: refresh,
    refreshing,
    cacheRefreshing: building && rows.length > 0,
    refreshStatus,
    toast,
    rows,
    hidden: {
      entries: hidden,
      count: hidden.length,
      countLabel: `${hidden.length} ${hidden.length === 1 ? 'item' : 'items'}`,
    },
    loading: loading || (building && !rows.length),
    labels,
    error,
    onRetry: reload,
    palette: { ...palette, ...mediaCardPalette, arrow: palette.textSecondary, arrowDisabled: palette.surfaceMuted, loading: palette.accent, focus: palette.accent },
    renderActionIcon: action => {
      const spec = action.action === 'planning' ? actionIcons.bookmarkPlus
        : action.action === 'dismiss' ? actionIcons.eyeOff
          : action.action === 'lists' ? actionIcons.listAdd : null;
      return spec ? <Icon spec={spec} color={palette.accentContrast} size={16} /> : null;
    },
    onOpenCard: (href, model) => navigate?.('Detail', { item: model }),
    onAction: runAction,
    onUndo: undo,
    onDismissRefreshStatus: dismissRefreshStatus,
    onDismissToast: dismissToast,
    children: <DiscoverListPicker picker={listPicker} onChoose={chooseList} onClose={() => setListPicker(null)} />,
  };
}

export default function DiscoverSlot({ navigate }) {
  const props = useDiscoverSurface({ navigate });
  return <DiscoverView
    {...props}
    error={props.error}
    onRetry={props.onRetry}
    palette={props.palette} />;
}