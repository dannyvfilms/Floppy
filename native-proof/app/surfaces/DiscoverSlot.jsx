import React, { useEffect, useRef, useState } from 'react';
import { DiscoverView } from '../../../frontend/pages/DiscoverView';
import { defaultLabels } from '../../../frontend/discover/DiscoverScreen';
import { mediaCardPalette, palette } from '../theme';
import {
  DEFAULT_MEDIA_OPTIONS,
  createDiscoverTransport,
  discoverRowsFromPayload,
  hiddenFromPayload,
  mediaOptionsFromNavigation,
} from '../data/discoverTransport';

export const surface = {
  id: 'DISCOVER',
  title: 'Discover rows, tabs and feedback',
  where: 'Discover',
  status: 'in_progress',
  note: 'The shared DiscoverView owns the page heading/toolbar order, tabs, recommendation rails, hidden grid, feedback and empty/loading/error states. Signed-in loads map /api/v1/discover/ rows and /api/v1/discover/hidden/ through the session facade; refresh queues /api/v1/discover/refresh/ and reloads. Planning posts the candidate to /api/v1/media/{type}/ and its undo deletes that entry. The API does not expose a Floppy item id for untracked row candidates, so Hide cannot call /api/v1/discover/hidden/ for them; only hidden entries can be unhidden. Browser interaction and iOS/Android runtime passes were not run.',
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
  const [transport] = useState(() => injectedTransport || createDiscoverTransport());
  const [selectedMedia, setSelectedMedia] = useState('all');
  const [showMore, setShowMore] = useState(false);
  const [rows, setRows] = useState([]);
  const [hidden, setHidden] = useState([]);
  const [loading, setLoading] = useState(transport.mode === 'server');
  const [error, setError] = useState('');
  const [reloadToken, setReloadToken] = useState(0);
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
    if (transport.mode !== 'server') return undefined;
    let cancelled = false;
    transport.loadNavigation().then(nav => {
      if (cancelled) return;
      setMediaOptions(mediaOptionsFromNavigation(nav));
    }).catch(() => {});
    return () => { cancelled = true; };
  }, [transport]);

  useEffect(() => {
    if (transport.mode !== 'server') {
      setLoading(false);
      return undefined;
    }
    let active = true;
    setLoading(true);
    setError('');
    const mediaType = selectedMedia === 'hidden' ? 'all' : selectedMedia;
    Promise.all([
      transport.loadRows({ mediaType, showMore }),
      transport.loadHidden(),
    ]).then(([rowsPayload, hiddenPayload]) => {
      if (!active) return;
      setRows(discoverRowsFromPayload(rowsPayload));
      setHidden(hiddenFromPayload(hiddenPayload));
      setLoading(false);
    }).catch(cause => {
      if (!active) return;
      setRows([]);
      setHidden([]);
      setError(cause?.message || 'Discover could not be loaded from the server.');
      setLoading(false);
    });
    return () => { active = false; };
  }, [transport, selectedMedia, showMore, reloadToken]);

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

  function reload() {
    setReloadToken(current => current + 1);
  }

  function refresh() {
    if (refreshing) return;
    setRefreshing(true);
    setCacheRefreshing(true);
    setError('');
    if (transport.mode === 'server') {
      const mediaType = selectedMedia === 'hidden' ? 'all' : selectedMedia;
      transport.refresh({ mediaType, showMore })
        .catch(cause => setError(cause?.message || 'Discover could not be refreshed.'))
        .finally(() => {
          reload();
          setRefreshing(false);
          setCacheRefreshing(false);
          setRefreshStatus({ visible: true, message: labels.refreshDone });
          clearTimeout(statusTimer.current);
          statusTimer.current = setTimeout(dismissRefreshStatus, 5000);
        });
      return;
    }
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
      if (transport.mode !== 'server') {
        showToast('Sign in to add Discover items to Planning.');
        return;
      }
      const identity = cardItem.identity || {};
      removeFromRows(cardItem);
      transport.plan({
        mediaType: identity.mediaType || cardItem.mediaType,
        source: identity.source,
        mediaId: identity.mediaId,
        title: cardItem.title,
        image: identity.image || cardItem.image?.src,
      }).then(() => {
        showToast(`Added "${cardItem.title}" to Planning.`, `plan:${encodeURIComponent(identity.mediaType)}:${encodeURIComponent(identity.source)}:${encodeURIComponent(identity.mediaId)}`);
      }).catch(cause => {
        setRows(snapshot.current?.rows || rows);
        snapshot.current = null;
        showToast(cause?.message || `Could not add "${cardItem.title}" to Planning.`);
      });
      return;
    }
    if (action.action === 'dismiss') {
      if (!cardItem.itemId) {
        showToast('This Discover row does not expose an item id, so it cannot be hidden from the API.');
        return;
      }
      if (transport.mode !== 'server') {
        showToast('Sign in to hide Discover items.');
        return;
      }
      removeFromRows(cardItem);
      transport.hide({ itemId: cardItem.itemId }).then(() => {
        showToast(`Hidden "${cardItem.title}" from Discover.`, `hide:${cardItem.itemId}`);
      }).catch(cause => {
        setRows(snapshot.current?.rows || rows);
        snapshot.current = null;
        showToast(cause?.message || `Could not hide "${cardItem.title}".`);
      });
      return;
    }
    if (action.action === 'unhide') {
      if (transport.mode !== 'server') {
        showToast('Sign in to unhide Discover items.');
        return;
      }
      snapshot.current = { rows, hidden };
      setHidden(current => current.filter(item => item.cardKey !== cardItem.cardKey));
      transport.unhide({ itemId: cardItem.itemId }).then(() => {
        showToast(`Unhid "${cardItem.title}" from Discover.`, `unhide:${cardItem.itemId}`);
      }).catch(cause => {
        setHidden(snapshot.current?.hidden || hidden);
        snapshot.current = null;
        showToast(cause?.message || `Could not unhide "${cardItem.title}".`);
      });
    }
  }

  function undo() {
    const token = toast.undoToken;
    if (!snapshot.current && !token) {
      dismissToast();
      return;
    }
    const [kind, ...encoded] = String(token || '').split(':');
    const [mediaType, source, mediaId] = encoded.map(value => decodeURIComponent(value));
    if (transport.mode === 'server') {
      if (kind === 'plan') {
        transport.unplan({ mediaType, source, mediaId })
          .catch(cause => showToast(cause?.message || 'Could not undo that change.'))
          .finally(() => reload());
      } else if (kind === 'hide') {
        transport.unhide({ itemId: mediaType })
          .catch(cause => showToast(cause?.message || 'Could not undo that change.'))
          .finally(() => reload());
      } else if (kind === 'unhide') {
        reload();
      }
    }
    if (snapshot.current) {
      setRows(snapshot.current.rows);
      setHidden(snapshot.current.hidden);
      snapshot.current = null;
    }
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
    onSelectMedia: (value) => {
      setSelectedMedia(value);
      snapshot.current = null;
    },
    showMore,
    onToggleShowMore: () => setShowMore(current => !current),
    onRefresh: refresh,
    refreshing,
    cacheRefreshing,
    refreshStatus,
    toast,
    rows: visibleRows,
    hidden: { entries: hidden, count: hidden.length },
    loading,
    labels,
    error,
    onRetry: reload,
    palette: { ...palette, ...mediaCardPalette, arrow: palette.textSecondary, arrowDisabled: palette.surfaceMuted, loading: palette.accent, focus: palette.accent },
    onOpenCard: (href, model) => navigate?.('Detail', { item: model }),
    onAction: runAction,
    onUndo: undo,
    onDismissRefreshStatus: dismissRefreshStatus,
    onDismissToast: dismissToast,
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