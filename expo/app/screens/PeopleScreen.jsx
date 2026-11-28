import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Linking, StyleSheet, Text, View } from 'react-native';
import { Button } from '../../../frontend/ui/Button';
import { PeopleView } from '../../../frontend/pages/PeopleView';
import { LightboxDialog } from '../../../frontend/ui/People';
import { ListsForm } from '../../../frontend/ui/ListsFormView';
import { applyListToggle, listsMembership, normalizeListsModel } from '../../../frontend/ui/mediaCardForms';
import { AdaptivePresentationSheet } from '../components/AdaptivePresentationSheet';
import { createListTransport } from '../data/listTransport';
import { loadPersonLists, togglePersonList } from '../surfaces/mediaCardTransport';
import { PeopleToolbar } from '../../../frontend/ui/PeopleToolbar';
import { Screen, Section } from '../components/Screen';
import { createPeopleTransport } from '../data/peopleTransport';
import { appendCreditPage, keepLoadedCredits } from '../data/peopleTransportCore';
import { enrichServerCard, routeCardHref } from '../data/serverCardCore';
import { getActiveAuthSession, subscribeAuthSession } from '../data/authSession';
import MediaCardSlot from '../surfaces/MediaCardSlot';
import { palette, radius, spacing } from '../theme';

export const surface = {
  id: 'PEOPLE',
  status: 'in_progress',
  title: 'People, studios and credits',
  where: 'Person and studio pages, watched and filmography credit rails, filter and sort toolbar',
  note: 'Person and studio pages load /api/v1/people/{source}/{id}/ and /api/v1/studios/{source}/{id}/ (the web profile views as JSON, token or session) and render the shared hero, watched, filmography and studio title rails. The filmography toolbar (sort, direction, rated, collected, adult mode, department, year, genre) re-requests the profile with those filters. Credits arrive 60 at a time; Show more under each grid asks for the next page (section + watched_page / credits_page). Loading, empty, error with retry and signed-out states are real; there is no sample content. Route params: { identity: { kind: "person" | "studio", source, personId | studioId } } (flat params are accepted too). Cast, crew, gallery and extras rails render only when a caller passes them in route params. Browser, iOS and Android runtime passes were not run.',
};

// While the server builds play totals (talentPending), ask again this often,
// for about two minutes, keeping the page on screen.
const TALENT_POLL_MS = 3000;
const TALENT_POLL_LIMIT = 40;

function openExternal(url) {
  if (!url) return;
  Linking.openURL(url).catch(() => {});
}

// Callers link with navigate('People', { identity }) (the shape the Detail
// screen builds) or with the same fields flat on the params.
export function identityFrom(params) {
  if (!params) return null;
  const value = params.identity ? { ...params, ...params.identity } : params;
  if (value.kind === 'studio' || value.studioId) {
    if (!value.source || !value.studioId) return null;
    return { kind: 'studio', source: value.source, studioId: String(value.studioId) };
  }
  if (value.kind === 'person' || value.personId) {
    if (!value.source || !value.personId) return null;
    return { kind: 'person', source: value.source, personId: String(value.personId) };
  }
  return null;
}

// The web page body starts 24px below the header and has no Back link.
const pageTop = { paddingTop: 24 };

export default function PeopleScreen({ navigate, onBack, params, transport: injectedTransport }) {
  const [session, setSession] = useState(() => getActiveAuthSession());
  useEffect(() => subscribeAuthSession(setSession), []);
  const transport = useMemo(
    () => injectedTransport || createPeopleTransport(session ? { auth: session } : {}),
    [injectedTransport, session],
  );
  const identity = useMemo(
    () => identityFrom(params),
    // The identity is rebuilt from primitive route fields.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [params?.identity?.kind, params?.identity?.source, params?.identity?.personId,
      params?.identity?.studioId, params?.kind, params?.source, params?.personId, params?.studioId],
  );
  const [profile, setProfile] = useState(params?.profile || null);
  const [mode, setMode] = useState(params?.profile ? 'ready' : 'loading');
  // The provider whose missing credentials caused the error, if the server named one.
  const [errorProvider, setErrorProvider] = useState(null);
  const [error, setError] = useState('');
  const [filters, setFilters] = useState({});
  const [attempt, setAttempt] = useState(0);
  const [talentPoll, setTalentPoll] = useState(0);
  const pollState = useRef({ key: '', count: 0, quiet: false });
  // Which grid is loading its next page ('watched' | 'filmography' | '').
  const [loadingMore, setLoadingMore] = useState('');
  // Bumped by every full load, so a late "Show more" answer for old filters
  // is dropped instead of appended.
  const loadGeneration = useRef(0);
  const [lightbox, setLightbox] = useState({ visible: false, index: 0 });
  // The Add to lists sheet: model, per-list membership, pending and error state.
  const [listsSheet, setListsSheet] = useState(null);

  useEffect(() => {
    if (params?.profile) {
      setProfile(params.profile);
      setMode('ready');
      return undefined;
    }
    if (!identity) {
      setMode('error');
      setError('This link does not identify a person or studio.');
      return undefined;
    }
    let active = true;
    loadGeneration.current += 1;
    setLoadingMore('');
    const quiet = pollState.current.quiet;
    pollState.current.quiet = false;
    // A filter change keeps the page on screen while the new credits load.
    setMode(current => (current === 'ready' ? 'ready' : 'loading'));
    setError('');
    setErrorProvider(null);
    const request = identity.kind === 'studio'
      ? transport.loadStudio(identity)
      : transport.loadPerson({ ...identity, filters });
    Promise.resolve(request).then(data => {
      if (!active) return;
      setProfile(current => (quiet ? keepLoadedCredits(current, data) : data));
      setMode('ready');
    }).catch(requestError => {
      // A background refresh for play totals never replaces a page on screen.
      if (!active || quiet) return;
      setProfile(null);
      setMode('error');
      setError(requestError?.message || 'The server rejected the profile request.');
      setErrorProvider(requestError?.provider || null);
    });
    return () => { active = false; };
  }, [transport, identity, filters, attempt, talentPoll, params?.profile]);

  // The server builds play totals in the background on a first visit and says
  // so with talentPending. Ask again a few seconds apart, for about two minutes.
  // talentPoll re-arms the next try as soon as one fires, so a failed quiet
  // request (profile unchanged) still gets its next bounded attempt.
  const pollKey = identity ? `${identity.kind}:${identity.source}:${identity.personId || identity.studioId}` : '';
  useEffect(() => {
    if (!profile?.talentPending) return undefined;
    const state = pollState.current;
    if (state.key !== pollKey) Object.assign(state, { key: pollKey, count: 0 });
    if (state.count >= TALENT_POLL_LIMIT) return undefined;
    const timer = setTimeout(() => {
      state.count += 1;
      state.quiet = true;
      setTalentPoll(count => count + 1);
    }, TALENT_POLL_MS);
    return () => clearTimeout(timer);
  }, [profile, pollKey, talentPoll]);

  // The next page of one credit grid, added below what is on screen.
  const loadMoreCredits = useCallback(section => {
    const next = section === 'watched' ? profile?.watchedNextPage : profile?.filmographyNextPage;
    if (!next || loadingMore || !identity || identity.kind !== 'person') return;
    const generation = loadGeneration.current;
    setLoadingMore(section);
    Promise.resolve(transport.loadPerson({ ...identity, filters, page: { section, page: next } }))
      .then(data => {
        if (generation !== loadGeneration.current) return;
        setProfile(current => appendCreditPage(current, data, section));
      })
      // The button stays, so the viewer can try again.
      .catch(() => {})
      .finally(() => {
        if (generation === loadGeneration.current) setLoadingMore('');
      });
  }, [profile, loadingMore, identity, transport, filters]);

  const openCredit = useCallback(entry => {
    navigate?.('Detail', {
      item: {
        title: entry.title,
        mediaType: entry.mediaType,
        source: entry.source,
        mediaId: entry.mediaId,
        href: entry.href,
      },
    });
  }, [navigate]);

  const openPerson = useCallback(person => {
    if (person.personId && person.source) {
      navigate?.('People', { identity: { kind: 'person', source: person.source, personId: person.personId } });
      return;
    }
    navigate?.('Detail', { item: { title: person.name } });
  }, [navigate]);

  const openExtra = useCallback(item => {
    navigate?.('Detail', {
      item: {
        title: item.name || item.title,
        mediaType: item.mediaType,
        source: item.source,
        mediaId: item.mediaId,
      },
    });
  }, [navigate]);

  function playGalleryItem(item) {
    openExternal(item.key ? `https://www.youtube.com/watch?v=${item.key}` : item.url);
  }

  const gallery = params?.gallery || profile?.gallery || [];
  const extras = params?.extras || profile?.extras || {};
  const live = mode === 'ready' && profile;
  const common = {
    palette: { ...palette, accentContrast: palette.onAccentStrong, placeholder: palette.surfaceStrong },
    gallery,
    galleryTitle: params?.galleryTitle || profile?.person?.name || profile?.studio?.name || '',
    gameLengths: extras.gameLengths,
    youtubeWatch: extras.youtubeWatch,
    reading: extras.reading,
    onOpenSource: openExternal,
    onOpenCredit: openCredit,
    renderCreditGrid: (entries, width) => <MediaCardSlot
      items={entries.filter(entry => entry.card).map((entry, index) => ({
        key: `${entry.id}-${index}`, model: enrichServerCard(entry.card), row: entry,
      }))}
      cardWidth={width} gridGap={16} onOpenDetail={openCredit}
      onOpenLink={href => routeCardHref(href, navigate)} />,
    onOpenExtra: openExtra,
    onPlayGallery: playGalleryItem,
    onOpenLightbox: (_items, index) => setLightbox({ visible: true, index }),
  };

  const listLabels = {
    title: 'Lists', close: 'Close', loading: 'Loading', loadFailed: "Couldn't load your lists.", retry: 'Try again',
    filterByTag: 'Filter by tag', allLists: 'All lists', countOne: 'On %s list', countMany: 'On %s lists',
    add: 'Add', remove: 'Remove', addTo: 'Add person to %s', removeFrom: 'Remove person from %s',
    emptyTag: 'No lists with this tag.', emptyLists: "You haven't created any lists yet.",
    toggleFailed: "Couldn't update this list. Please try again.", create: 'Create list', createName: 'Name',
    createPlaceholder: 'Favourite actors', createSubmit: 'Create', createFailed: "Couldn't create this list. Please try again.",
    cancel: 'Cancel',
  };

  const openLists = useCallback(async () => {
    if (identity?.kind !== 'person') return;
    const blank = { membership: {}, model: null, pending: {}, errors: {} };
    setListsSheet({ status: 'loading', ...blank });
    try {
      const model = normalizeListsModel(await loadPersonLists(identity, profile?.person?.name));
      setListsSheet({ ...blank, status: 'ready', model, membership: listsMembership(model) });
    } catch {
      setListsSheet({ status: 'error', ...blank });
    }
  }, [identity, profile?.person?.name]);

  const toggleListMembership = useCallback(async list => {
    if (!listsSheet || listsSheet.pending[list.id]) return;
    const patch = value => setListsSheet(current => (current ? { ...current, ...value(current) } : current));
    patch(current => ({ pending: { ...current.pending, [list.id]: true }, errors: { ...current.errors, [list.id]: '' } }));
    try {
      const result = await togglePersonList(identity, list.id, Boolean(listsSheet.membership[list.id]));
      patch(current => ({ membership: applyListToggle(current.membership, list.id, result.hasItem), pending: { ...current.pending, [list.id]: false } }));
    } catch (cause) {
      patch(current => ({ pending: { ...current.pending, [list.id]: false }, errors: { ...current.errors, [list.id]: cause?.message || listLabels.toggleFailed } }));
    }
  }, [identity, listsSheet]);

  function personPage(data) {
    const labels = data.labels || {};
    return <PeopleView
      {...common}
      part="full"
      kind="person"
      person={data.person}
      counts={data.counts}
      labels={labels}
      watched={data.watched || []}
      filmography={data.filmography || []}
      watchedTotal={data.watchedTotal}
      filmographyTotal={data.filmographyTotal}
      loadingMore={loadingMore}
      onLoadMoreWatched={data.watchedNextPage ? () => loadMoreCredits('watched') : undefined}
      onLoadMoreFilmography={data.filmographyNextPage ? () => loadMoreCredits('filmography') : undefined}
      cast={params?.cast || data.cast || []}
      crew={params?.crew || data.crew || []}
      isAuthor={data.isAuthor}
      showBiography={data.showBiography}
      canViewHistory={data.canViewHistory}
      actionPalette={{ radius: radius.sm }}
      actionSize="md"
      toolbar={<PeopleToolbar filters={data.filters} labels={labels.toolbar} palette={palette}
        onChange={patch => setFilters(current => ({ ...current, ...patch }))} />}
      onViewHistory={data.historyUrl
        ? () => navigate?.('History', { filters: data.historyUrl })
        : undefined}
      // Only a stored person can be saved on a list; the server sends the popup spec for those.
      onAddToLists={data.listsModal ? openLists : undefined}
      onOpenPerson={openPerson} />;
  }

  function studioPage(data) {
    const labels = data.labels || {};
    return <PeopleView
      {...common}
      part="full"
      kind="studio"
      studio={data.studio}
      counts={data.counts}
      labels={labels}
      filmography={data.titles || []}
      creditsTitle={data.studio?.mediaLabel || labels.titles || 'Titles'}
      creditsSummary={data.counts?.[0]?.label}
      sourcePlacement="facts"
      showBiography={data.showBiography}
      onOpenWebsite={openExternal} />;
  }

  // Detail passes gallery and medium extras alone when it opens the extras view.
  const extrasOnly = params?.kind === 'extras' && !identity;

  return <Screen chrome={false} contentStyle={pageTop}>
    {mode === 'loading' && !extrasOnly ? <Section title="Loading profile…">
      <Text accessibilityLiveRegion="polite" style={[styles.statusText, { color: palette.textSecondary }]}>
        Loading the person or studio profile from your server.
      </Text>
    </Section> : null}
    {mode === 'error' && !extrasOnly ? <Section title="The profile could not be loaded.">
      <View style={styles.errorStack}>
        <Text accessibilityLiveRegion="polite" style={[styles.statusText, { color: palette.textSecondary }]}>{error}</Text>
        {errorProvider ? <Button label={`Open ${errorProvider.label} settings`} palette={palette}
          onPress={() => navigate?.('ProviderDetail', { slug: errorProvider.slug, label: errorProvider.label, tab: 'connection' })} /> : null}
        {identity ? <Button label="Try again" tone="surface" palette={palette}
          onPress={() => setAttempt(current => current + 1)} /> : null}
      </View>
    </Section> : null}
    {live && profile.kind === 'person' ? personPage(profile) : null}
    {live && profile.kind === 'studio' ? studioPage(profile) : null}
    {extrasOnly ? <PeopleView {...common} part="extras" labels={params?.labels} /> : null}
    <AdaptivePresentationSheet isPresented={!!listsSheet} onDismiss={() => setListsSheet(null)}
      onClose={() => setListsSheet(null)} title="Lists" titleColor={palette.text} containerColor={palette.sidebar}>
      {listsSheet ? <ListsForm
        model={listsSheet.model}
        membership={listsSheet.membership}
        tag=""
        status={listsSheet.status}
        pending={listsSheet.pending}
        errors={listsSheet.errors}
        labels={listLabels}
        palette={{ ...palette, ...palette.mediaCard, radius: 8, focusStyle: {} }}
        showHeader={false}
        embedded
        onTagChange={() => {}}
        onRetry={openLists}
        onCreate={async name => {
          await createListTransport({ auth: session }).create({ name });
          await openLists();
        }}
        onClose={() => setListsSheet(null)}
        onToggle={toggleListMembership} /> : null}
    </AdaptivePresentationSheet>
    <LightboxDialog visible={lightbox.visible} items={gallery} index={lightbox.index}
      palette={palette}
      onClose={() => setLightbox({ visible: false, index: lightbox.index })}
      onIndexChange={index => setLightbox({ visible: true, index })}
      onPlay={playGalleryItem} />
  </Screen>;
}

const styles = StyleSheet.create({
  statusText: { fontSize: 14, lineHeight: 20 },
  errorStack: { gap: spacing.sm, alignItems: 'flex-start' },
});
