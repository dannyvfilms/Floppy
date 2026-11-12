import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { StyleSheet, Text, useWindowDimensions, View } from 'react-native';
import { Button } from '../../../frontend/ui/Button';
import { HomeView } from '../../../frontend/pages/HomeView';
import { Icon } from '../../../frontend/ui/Icon';
import { shelfCardWidth } from '../../../frontend/ui/HomeShelves';
import WindowedRail from '../surfaces/WindowedRail';
import {
  createHomeTransport,
  homeScreenFromPayload,
  mergeHomeRowPage,
} from '../data/homeTransport';
import { enrichServerCard, routeCardHref } from '../data/serverCardCore';
import { getActiveAuthSession, subscribeAuthSession } from '../data/authSession';
import { useMobileGridLayout } from '../data/useMobileGridLayout';
import { palette, radius, spacing } from '../theme';
import { Screen } from '../components/Screen';
import HomeProgress from '../surfaces/HomeProgress';
import MediaCardSlot from '../surfaces/MediaCardSlot';
import PlaybackSlot from '../surfaces/PlaybackSlot';
import { playbackDetailItem } from '../data/playbackTransport';
import { libraryParamsForRowUrl } from '../data/homeRowDestinationCore';

export const surface = {
  id: 'HOME',
  status: 'ported',
  title: 'Home shelves, deferred groups and cover refresh',
  where: 'Home screen shelves, media-type sections, deferred rows and coalesced artwork polling',
  note: 'The native Home screen composes the Now Playing card and the shared HomeShelves rails. Every shelf card renders through the shared media card host (MediaCardSlot), so Track, Lists and rating work in place and the quick progress changer writes through /api/v1/media/{type}/{source}/{id}/progress/. Signed-out users never reach this screen (the app shows the sign-in screen), so it carries no sample content. Loading, empty, error with retry, deferred-skeleton, sort, load-more and cover refresh states come from homeTransport. Browser, iOS and Android runtime passes were not run.',
};

const PAGE_LIMIT = 14;

const emptyModel = () => ({
  groups: [],
  deferredGroups: [],
  showMediaTypeHeaders: false,
  readOnly: true,
  labels: {},
});

// The web page body starts 24px below the header.
const pageTop = { paddingTop: 24 };

export default function HomeScreen({ navigate, onOpenTab }) {
  const { width } = useWindowDimensions();
  // The same breakpoint helper the web mount uses, so a card is never a
  // different size on one surface.
  const mobileGridLayout = useMobileGridLayout();
  const itemWidth = shelfCardWidth(width, mobileGridLayout);
  const [session, setSession] = useState(() => getActiveAuthSession());
  useEffect(() => subscribeAuthSession(setSession), []);
  const transport = useMemo(
    () => createHomeTransport(session ? { auth: session } : {}),
    [session],
  );
  const serverMode = transport.mode === 'server';
  const [model, setModel] = useState(emptyModel);
  const [loading, setLoading] = useState(serverMode);
  const [error, setError] = useState('');
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    if (!serverMode) {
      setModel(emptyModel());
      setLoading(false);
      setError('');
      return undefined;
    }
    let cancelled = false;
    setLoading(true);
    setError('');
    transport.load({ limit: PAGE_LIMIT }).then(payload => {
      if (cancelled) return;
      setModel(homeScreenFromPayload(payload));
      setLoading(false);
    }).catch(cause => {
      if (cancelled) return;
      setError(cause?.message || 'Home could not be loaded from the server.');
      setModel(emptyModel());
      setLoading(false);
    });
    return () => { cancelled = true; };
  }, [attempt, serverMode, transport]);

  const loadRow = useCallback(rowId => transport.loadRow({ rowId, limit: PAGE_LIMIT }), [transport]);

  const loadMore = useCallback(async currentRow => {
    try {
      const page = await transport.loadRow({
        rowId: currentRow.rowId,
        offset: currentRow.loadedCount || 0,
        seed: currentRow.seed,
        limit: PAGE_LIMIT,
      });
      return page ? mergeHomeRowPage(currentRow, page) : null;
    } catch {
      return null;
    }
  }, [transport]);

  const sortRow = useCallback(async currentRow => {
    try {
      return await transport.sortRow({ rowId: currentRow.rowId });
    } catch {
      return null;
    }
  }, [transport]);

  const refreshCovers = useCallback(
    (ids = [], pending = 0) => transport.refreshCovers({ ids, pending }),
    [transport],
  );

  const openCard = useCallback(card => {
    if (!routeCardHref(card?.href, navigate)) navigate?.('Detail', { item: card });
  }, [navigate]);

  // Each shelf card is its own one-card host, so Track, Lists and rating open
  // in place exactly like the Library grid, never a Detail navigation.
  const renderCard = useCallback(item => <View style={{ width: itemWidth }}><MediaCardSlot
    gridLayout="library"
    cardWidth={itemWidth}
    items={[{ key: String(item.id), model: enrichServerCard(item.card) }]}
    onOpenDetail={() => openCard(item.card)}
    onOpenLink={href => { if (!routeCardHref(href, navigate)) openCard(item.card); }} /></View>,
  [navigate, openCard, itemWidth]);

  const renderProgress = useCallback((progress, item) => <HomeProgress
    progress={progress}
    identity={enrichServerCard(item.card)?.identity} />, []);

  return <Screen chrome={false} contentStyle={pageTop}>
    <HomeView
      notice={serverMode ? null : <View style={[styles.signedOut, { borderColor: palette.border }]}>
        <Text style={[styles.signedOutText, { color: palette.textSecondary }]}>Sign in to your Floppy server to see Home.</Text>
        <Button label="Connect server" tone="surface" palette={palette}
          onPress={() => navigate?.('Auth')} />
      </View>}
      playback={serverMode ? <PlaybackSlot onOpenDetail={card => navigate?.('Detail', { item: playbackDetailItem(card) })} /> : null}
      groups={model.groups}
      deferredGroups={model.deferredGroups}
      showMediaTypeHeaders={model.showMediaTypeHeaders}
      labels={model.labels}
      palette={palette}
      readOnly={model.readOnly}
      itemWidth={itemWidth}
      railComponent={WindowedRail}
      renderCard={renderCard}
      renderProgress={renderProgress}
      renderActionIcon={action => action.icon ? <Icon spec={action.icon} color={palette.accentContrast} size={18} /> : null}
      loading={loading}
      error={error}
      onRetry={() => setAttempt(current => current + 1)}
      onOpenCard={(item) => openCard(item?.card)}
      onOpenSettings={onOpenTab ? () => onOpenTab('settings') : undefined}
      canOpenRowTitle={href => !!libraryParamsForRowUrl(href)}
      onOpenRowTitle={(href, _row) => {
        const target = libraryParamsForRowUrl(href);
        if (target) navigate?.('Library', target);
      }}
      onLoadRow={loadRow}
      onLoadMore={loadMore}
      onSortRow={sortRow}
      onRefreshCovers={refreshCovers}
    />
  </Screen>;
}

const styles = StyleSheet.create({
  signedOut: {
    borderWidth: 1,
    borderRadius: radius.md,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    gap: spacing.sm,
    alignItems: 'flex-start',
  },
  signedOutText: { fontSize: 13, lineHeight: 18 },
});
