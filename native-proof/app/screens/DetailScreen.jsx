import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ActivityIndicator, Linking, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';
import { Button } from '../../../frontend/ui/Button';
import { Icon } from '../../../frontend/ui/Icon';
import { actionIcons } from '../../../frontend/ui/actionIcons';
import { ProgressCard } from '../../../frontend/ui/ProgressCard.native';
import { ProgressDialog } from '../../../frontend/ui/ProgressDialog';
import { CollectionCopyDialog } from '../../../frontend/ui/CollectionCopies';
import { ListsForm } from '../../../frontend/ui/ListsFormView';
import { MediaCardActionHost } from '../../../frontend/ui/MediaCardActionHost';
import { RatingChip } from '../../../frontend/ui/RatingChip';
import { RatingStarIcon } from '../../../frontend/ui/RatingStarIcon.native';
import { RatingStars } from '../../../frontend/ui/RatingStars';
import { TagAssignmentDialog } from '../../../frontend/ui/TagManagement';
import { TrackDialog } from '../../../frontend/ui/TrackDialog';
import {
  applyListToggle,
  initialTrackValues,
  listsMembership,
  normalizeListsModel,
  normalizeTrackForm,
} from '../../../frontend/ui/mediaCardForms';
import { DetailEpisodePageView, DetailPageView, detailPageLabels } from '../../../frontend/pages/DetailView';
import { DetailEpisodeCards, DetailIssueCards, DetailRelatedGrid } from '../../../frontend/ui/DetailPage';
import { ArtworkPicker, EditionPicker } from '../../../frontend/ui/ArtworkPicker';
import { Screen } from '../components/Screen';
import { pickCoverImage } from '../data/imagePicker';
import MediaCardSlot from '../surfaces/MediaCardSlot';
import { cardActionsFor } from '../data/libraryTransportCore';
import {
  createDetailModelForItem,
  detailPagePalette,
  loadDetailPage,
} from '../surfaces/detailModel';
import { activityLineWithWatched, identityFromItem, identityKey, mergeScoreChips, relatedSections } from '../data/detailTransportCore';
import { setShellPageType } from '../surfaces/shellContext';
import {
  collectionAddressFor,
  copyFieldsFor,
  createCollectionTransport,
  emptyCopyValues,
} from '../data/collectionTransport';
import {
  deleteHistoryEntry,
  loadActivityTimeline,
  loadCoverCandidates,
  loadEditions,
  saveCover,
  saveEdition,
  loadArtwork,
  loadCheckIn,
  loadCollectionEntries,
  loadProgressCard,
  loadScores,
  loadAnimeEpisodes,
  loadIssues,
  loadSeasonEpisodes,
  loadSeerr,
  requestSeerr,
  runCheckIn,
  saveEntryNotes,
  syncMetadata,
  watchEpisode,
} from '../data/detailTransport';
import {
  createTag,
  deleteTrack,
  loadLists,
  loadTags,
  loadTrack,
  loadTrackTabs,
  saveArtwork,
  saveScore,
  saveTrack,
  setDiscoverHidden,
  setTags,
  toggleList,
  unwatchEpisode,
} from '../surfaces/mediaCardTransport';
import { progressDetailPalette, spacing } from '../theme';

const palette = detailPagePalette;
const formPalette = {
  ...palette,
  ...palette.mediaCard,
  radius: 8,
  focusStyle: {},
  dateTime: palette.mediaCard,
};

const EMPTY_TRACK = {
  open: false,
  status: 'ready',
  model: null,
  tabs: [],
  values: {},
  tracked: false,
  busy: false,
  serverError: '',
};

const listLabels = {
  title: 'Lists',
  close: 'Close',
  loading: 'Loading',
  loadFailed: "Couldn't load your lists.",
  retry: 'Try again',
  filterByTag: 'Filter by tag',
  allLists: 'All lists',
  countOne: 'On %s list',
  countMany: 'On %s lists',
  add: 'Add',
  remove: 'Remove',
  addTo: 'Add item to %s',
  removeFrom: 'Remove item from %s',
  emptyTag: 'No lists with this tag.',
  emptyLists: "You haven't created any lists yet.",
  toggleFailed: "Couldn't update this list. Please try again.",
};

// Web: "Add new entry" is offered once a finished entry exists for these types,
// and always for games (app/track_actions.py).
const ADD_ENTRY_ALWAYS = new Set(['game', 'boardgame']);
const ADD_ENTRY_WHEN_COMPLETED = new Set(['movie', 'anime', 'book', 'comic']);

function renderRating({ value, label, scaleMax, palette: ratingColors, onSelect }) {
  return <RatingStars scaleMax={scaleMax} value={value} label={label}
    renderStar={RatingStarIcon} onSelect={onSelect} palette={ratingColors} />;
}

const PROMPT_NOUNS = { movie: 'movie', tv: 'show', season: 'show' };

function DialogMessage({ text }) {
  return <Text style={styles.dialogText}>{text}</Text>;
}

function NotesDialog({ open, note, busy, error, onSave, onClose }) {
  const [draft, setDraft] = useState('');
  useEffect(() => { if (open) setDraft(note?.text || ''); }, [open, note]);
  return <MediaCardActionHost open={open} action={{ title: 'Notes' }} palette={palette} onClose={onClose}>
    <TextInput accessibilityLabel="Notes" multiline value={draft} onChangeText={setDraft}
      placeholderTextColor={palette.textMuted} style={styles.notesInput} textAlignVertical="top" />
    {error ? <Text style={[styles.dialogText, { color: palette.danger }]}>{error}</Text> : null}
    <View style={styles.dialogActions}>
      <Button label="Cancel" tone="surface" palette={palette.button} onPress={onClose} />
      <Button label="Save" tone="primary" disabled={busy} busy={busy} palette={palette.button}
        onPress={() => onSave(draft)} />
    </View>
  </MediaCardActionHost>;
}

function PlaysDialog({ open, identity, entries, onRemove, onClose }) {
  const [timeline, setTimeline] = useState({ status: 'idle', days: [], multiple: false });
  useEffect(() => {
    if (!open || !identity) return undefined;
    let cancelled = false;
    setTimeline({ status: 'loading', days: [], multiple: false });
    loadActivityTimeline(identity)
      .then(next => { if (!cancelled) setTimeline({ status: 'ready', days: next.days, multiple: next.multipleInstances }); })
      .catch(() => { if (!cancelled) setTimeline({ status: 'error', days: [], multiple: false }); });
    return () => { cancelled = true; };
  }, [open, identity]);
  return <MediaCardActionHost open={open} action={{ title: 'Activity History' }} palette={palette} onClose={onClose}>
    <ScrollView style={styles.dialogScroll}>
      {timeline.status === 'loading' ? <ActivityIndicator color={palette.accent} /> : null}
      {timeline.days.map(day => <View key={day.day} style={styles.dayGroup}>
        <Text accessibilityRole="header" style={[styles.dialogText, styles.dayHeading, { color: palette.text }]}>{day.label}</Text>
        {day.entries.map(entry => <View key={entry.id} style={[styles.dayEntry, { backgroundColor: palette.surfaceStrong }]}>
          <Text style={styles.playMeta}>{[entry.instance && timeline.multiple ? `Instance #${entry.instance}` : '', entry.date].filter(Boolean).join(' · ')}</Text>
          {entry.changes.map((change, index) => <Text key={index} style={[styles.dialogText, { color: palette.text }]}>{change}</Text>)}
        </View>)}
      </View>)}
      {timeline.status === 'ready' && !timeline.days.length ? <DialogMessage text="You haven't started tracking it yet." /> : null}
      {timeline.status === 'error' ? <DialogMessage text="Activity history could not be loaded." /> : null}
      {entries.length ? <Text accessibilityRole="header" style={[styles.dialogText, styles.dayHeading, { color: palette.text }]}>Plays</Text> : null}
      {entries.map(entry => <View key={entry.id} style={styles.playRow}>
        <View style={styles.playBody}>
          <Text style={[styles.dialogText, { color: palette.text }]}>{entry.title}</Text>
          <Text style={styles.playMeta}>{[entry.date, entry.detail].filter(Boolean).join(' · ')}</Text>
        </View>
        <Button label="Remove" tone="ghost-danger" palette={palette.button} onPress={() => onRemove(entry)} />
      </View>)}
    </ScrollView>
  </MediaCardActionHost>;
}

function CoverDialog({ open, itemId, palette: dialogPalette, onSaved, onClose }) {
  const [state, setState] = useState({ status: 'loading', current: '', candidates: [] });
  const [selected, setSelected] = useState(null);
  const [url, setUrl] = useState('');
  const [showUrl, setShowUrl] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const load = useCallback(() => {
    setState(current => ({ ...current, status: 'loading' }));
    loadCoverCandidates(itemId)
      .then(next => setState({ status: 'ready', ...next }))
      .catch(() => setState(current => ({ ...current, status: 'error' })));
  }, [itemId]);
  useEffect(() => {
    if (!open) return;
    setSelected(null); setUrl(''); setShowUrl(false); setError('');
    load();
  }, [open, load]);
  const choose = async () => {
    try {
      const picked = await pickCoverImage();
      if (picked) setSelected({ kind: 'file', uri: picked.uri, base64: picked.base64 });
    } catch {
      setError('That image could not be read.');
    }
  };
  const save = async () => {
    setSaving(true); setError('');
    try {
      await saveCover(itemId, selected?.kind === 'file' ? { base64: selected.base64 }
        : { url: selected?.kind === 'candidate' ? selected.image : url.trim() });
      onSaved();
    } catch (cause) {
      setError(cause?.message || 'The cover could not be saved.');
    } finally {
      setSaving(false);
    }
  };
  return <MediaCardActionHost open={open} action={{ title: 'Cover' }} palette={dialogPalette} onClose={onClose}>
    <ArtworkPicker
      current={state.current} candidates={state.candidates} candidatesState={state.status}
      selected={selected} url={url} showUrl={showUrl} supportsDrag={false} saving={saving} error={error}
      palette={{ ...dialogPalette, radius: 8, radiusSmall: 6, button: dialogPalette.button, accentText: dialogPalette.accentContrast }}
      onChooseFile={choose} onToggleUrl={() => setShowUrl(value => !value)}
      onUrlChange={value => { setUrl(value); setSelected(value.trim() ? { kind: 'url', uri: value.trim() } : null); }}
      onPickCandidate={candidate => setSelected({ kind: 'candidate', id: candidate.id, uri: candidate.uri, image: candidate.image, title: candidate.title })}
      onReset={() => { setSelected(null); setUrl(''); }}
      onSave={save} onRetryCandidates={load} />
  </MediaCardActionHost>;
}

function EditionDialog({ open, itemId, palette: dialogPalette, onSaved, onClose }) {
  const [query, setQuery] = useState('');
  const [state, setState] = useState({ status: 'loading', rows: [], selected: '' });
  const load = useCallback(needle => {
    setState(current => ({ ...current, status: 'loading' }));
    loadEditions(itemId, needle)
      .then(next => setState({ status: 'ready', ...next }))
      .catch(() => setState(current => ({ ...current, status: 'error' })));
  }, [itemId]);
  useEffect(() => { if (open) { setQuery(''); load(''); } }, [open, load]);
  const pick = async row => {
    try {
      await saveEdition(itemId, row.id);
      onSaved();
    } catch {
      setState(current => ({ ...current, status: 'error' }));
    }
  };
  return <MediaCardActionHost open={open} action={{ title: 'Edition' }} palette={dialogPalette} onClose={onClose}>
    <EditionPicker
      description="Pick a specific Hardcover edition (e.g. a different language or cover) to use for this title's title and cover. Leave the search blank to see every edition."
      provider="Hardcover" placeholder="Search editions..." query={query} results={state.rows}
      selectedId={state.selected} state={state.status} open
      palette={{ ...dialogPalette, radius: 8, radiusSmall: 6, accentText: dialogPalette.accentContrast }}
      onQueryChange={value => { setQuery(value); load(value.trim()); }}
      onSelect={pick} onRetry={() => load(query.trim())} />
  </MediaCardActionHost>;
}

function SeerrDialog({ open, state, busy, error, onRequest, onClose }) {
  const seasons = state?.seasons || [];
  return <MediaCardActionHost open={open} action={{ title: 'Request in Seerr' }} palette={palette} onClose={onClose}>
    {error ? <Text style={[styles.dialogText, { color: palette.danger }]}>{error}</Text> : null}
    {!state ? <ActivityIndicator color={palette.accent} /> : null}
    {state && seasons.length ? seasons.map(season => <View key={season.number} style={styles.playRow}>
      <Text style={[styles.dialogText, styles.playBody, { color: palette.text }]}>{season.name}</Text>
      {season.requestable
        ? <Button label="Request" disabled={busy} palette={palette.button} onPress={() => onRequest([season.number])} />
        : <Text style={styles.playMeta}>{season.status}</Text>}
    </View>) : null}
    {state && !seasons.length ? <Text style={[styles.dialogText, { color: palette.text }]}>{`Status: ${state.status}`}</Text> : null}
    {state?.requestable ? <Button
      label={seasons.length ? 'Request all missing seasons' : 'Request'} width="full" disabled={busy}
      palette={palette.button} onPress={() => onRequest([])} /> : null}
  </MediaCardActionHost>;
}

function collectionAddressForIdentity(target) {
  // A show or season collects every one of its episodes (PUT .../collect/).
  if (target.mediaType === 'tv' || target.mediaType === 'season') {
    const base = `/api/v1/media/tv/${encodeURIComponent(target.source)}/${encodeURIComponent(target.mediaId)}`;
    return { path: `${base}${target.mediaType === 'season' ? `/${target.seasonNumber}` : ''}/collect/` };
  }
  return collectionAddressFor({
    media_type: target.mediaType,
    source: target.source,
    media_id: target.mediaId,
    season_number: target.seasonNumber,
    episode_number: target.episodeNumber,
  });
}

function DetailPage({ entry, onBack, navigate }) {
  const initialIdentity = useMemo(() => identityFromItem(entry), [entry]);
  const [page, setPage] = useState(() => ({ identity: initialIdentity, model: createDetailModelForItem(entry) }));
  const [loaded, setLoaded] = useState(!entry);
  const [error, setError] = useState('');
  const [attempt, setAttempt] = useState(0);
  const [track, setTrack] = useState(EMPTY_TRACK);
  const [episodes, setEpisodes] = useState({ rows: [], status: 'idle', error: '', order: 'asc' });
  const [issues, setIssues] = useState({ rows: [], total: 0, status: 'idle', error: '', layout: 'grid' });
  const [collection, setCollection] = useState({ status: 'loading', entries: [], counts: [], error: '' });
  const [seerr, setSeerr] = useState({ available: false, state: null });
  const [dialog, setDialog] = useState({ kind: '', busy: false, error: '', data: null });
  const [notice, setNotice] = useState('');
  const [progress, setProgress] = useState({ data: null, open: false });
  const [copy, setCopy] = useState({ open: false, values: {}, errors: {}, busy: false });
  const [checkin, setCheckin] = useState([]);
  const [backdrop, setBackdrop] = useState(null);
  const [scores, setScores] = useState({ chips: [], graphs: {}, gameLengths: null });

  const { identity, model } = page;
  const reload = useCallback(() => setAttempt(value => value + 1), []);
  const isSeason = identity?.mediaType === 'season';
  const isEpisode = identity?.mediaType === 'episode';
  const isAnime = identity?.mediaType === 'anime';

  // The header search follows the page like the web header: a season searches
  // TV Shows, an episode page has no type of its own and keeps the last one.
  const pageType = identity?.mediaType === 'season' ? 'tv'
    : identity?.mediaType === 'episode' ? null : identity?.mediaType;
  useEffect(() => {
    setShellPageType(pageType);
    return () => setShellPageType(null);
  }, [pageType]);

  useEffect(() => {
    if (!entry) return undefined;
    let cancelled = false;
    setError('');
    loadDetailPage(entry).then(next => {
      if (cancelled) return;
      setPage(next);
      setLoaded(true);
    }).catch(cause => {
      if (cancelled) return;
      setError(cause?.message || 'The detail could not be loaded from the server.');
      setLoaded(true);
    });
    return () => { cancelled = true; };
  }, [entry, attempt]);

  useEffect(() => {
    if (!identity || !loaded) return undefined;
    let cancelled = false;
    setCollection(current => ({ ...current, status: current.entries.length ? 'ready' : 'loading' }));
    loadCollectionEntries(identity)
      .then(loaded => { if (!cancelled) setCollection({ status: 'ready', ...loaded, error: '' }); })
      .catch(cause => {
        if (!cancelled) setCollection({ status: 'error', entries: [], counts: [], error: cause?.message || 'Collection could not be loaded.' });
      });
    return () => { cancelled = true; };
  }, [identity, loaded, attempt]);

  useEffect(() => {
    if (!identity || !loaded || !model.canRequest || identity.source !== 'tmdb') return undefined;
    let cancelled = false;
    loadSeerr(identity)
      .then(state => { if (!cancelled) setSeerr({ available: Boolean(state), state }); })
      .catch(() => { if (!cancelled) setSeerr({ available: false, state: null }); });
    return () => { cancelled = true; };
  }, [identity, loaded, model.canRequest, attempt]);

  const loadEpisodes = useCallback(async (more = false) => {
    if (!identity || (!isSeason && !isAnime)) return;
    if (more && episodesRef.current.status === 'loading') return;
    setEpisodes(current => ({ ...current, status: more || !current.rows.length ? 'loading' : 'ready', error: '' }));
    try {
      if (isAnime) {
        const next = await loadAnimeEpisodes(identity, more ? episodesRef.current.loadMore?.querystring : '');
        setEpisodes(current => ({ ...current, rows: more ? [...current.rows, ...next.rows] : next.rows, loadMore: next.loadMore, related: next.related, status: 'ready', error: '' }));
      } else {
        const rows = await loadSeasonEpisodes(identity, identity.seasonNumber);
        setEpisodes(current => ({ ...current, rows, status: 'ready', error: '' }));
      }
    } catch (cause) {
      setEpisodes(current => ({ ...current, status: 'error', error: cause?.message || 'Episodes could not be loaded.' }));
    }
  }, [identity, isSeason, isAnime]);
  const episodesRef = useRef(episodes);
  episodesRef.current = episodes;

  useEffect(() => { if (loaded) loadEpisodes(); }, [loaded, loadEpisodes, attempt]);

  // A comic volume lists its issues, twenty at a time.
  const loadMoreIssues = useCallback(async (reset = false) => {
    if (!identity || identity.mediaType !== 'comic') return;
    setIssues(current => ({ ...current, status: 'loading', error: '', ...(reset ? { rows: [], total: 0 } : {}) }));
    try {
      const page = await loadIssues(identity, reset ? 0 : issuesRef.current.rows.length);
      setIssues(current => ({ ...current, rows: reset ? page.rows : [...current.rows, ...page.rows], total: page.total, status: 'ready' }));
    } catch (cause) {
      setIssues(current => ({ ...current, status: 'error', error: cause?.message || 'Issues could not be loaded.' }));
    }
  }, [identity]);
  const issuesRef = useRef(issues);
  issuesRef.current = issues;
  useEffect(() => { if (loaded) loadMoreIssues(true); }, [loaded, loadMoreIssues, attempt]);

  const open = useCallback(target => navigate?.('Detail', { item: target }), [navigate]);
  const openChild = useCallback(child => open({
    identity: child.identity,
    title: child.title,
    href: child.href,
  }), [open]);

  const runChildAction = useCallback(async (actionKey, child) => {
    if (!child?.identity) return;
    if (actionKey === 'lists') { openLists(child.identity, child.title); return; }
    if (actionKey === 'collection') { openCopyDialog(child.identity, child.title); return; }
    if (actionKey === 'history') { setDialog({ kind: 'history', target: child.identity, busy: false, error: '', data: null }); return; }
    try {
      if (actionKey === 'unwatch') await unwatchEpisode(child.identity);
      else await watchEpisode(child.identity);
      loadEpisodes();
      reload();
    } catch (cause) {
      setEpisodes(current => ({ ...current, error: cause?.message || 'The episode could not be updated.' }));
    }
  }, [loadEpisodes, reload]);

  const rateChild = useCallback(async (child, score) => {
    try {
      await saveScore(child.identity, score);
      loadEpisodes();
    } catch (cause) {
      setEpisodes(current => ({ ...current, error: cause?.message || 'The score could not be saved.' }));
    }
  }, [loadEpisodes]);

  const openTrack = useCallback(async (fresh = false, target = identity) => {
    if (!target) {
      setTrack({ ...EMPTY_TRACK, open: true, status: 'error', serverError: 'This item has no server identity to track.' });
      return;
    }
    setTrack({ ...EMPTY_TRACK, identity: target, open: true, status: 'loading' });
    try {
      const loaded_ = await loadTrack(target, { trackTime: true, fresh });
      const trackModel = normalizeTrackForm(loaded_.model);
      setTrack({
        ...EMPTY_TRACK,
        identity: target,
        open: true,
        status: 'ready',
        model: trackModel,
        tabs: loaded_.tabs,
        tracked: loaded_.tracked,
        values: initialTrackValues(trackModel),
      });
    } catch {
      setTrack({ ...EMPTY_TRACK, identity: target, open: true, status: 'error' });
    }
  }, [identity]);

  const submitTrack = useCallback(async values => {
    if (!track.identity || !track.model) return;
    setTrack(current => ({ ...current, busy: true, serverError: '' }));
    try {
      await saveTrack(track.identity, track.model, values, track.tracked);
      setTrack(EMPTY_TRACK);
      reload();
    } catch (cause) {
      setTrack(current => ({ ...current, busy: false, serverError: cause?.message || 'The change could not be saved.' }));
    }
  }, [reload, track.identity, track.model, track.tracked]);

  const removeTrack = useCallback(async () => {
    if (!track.identity || !track.model) return;
    setTrack(current => ({ ...current, busy: true, serverError: '' }));
    try {
      await deleteTrack(track.identity, track.model);
      setTrack(EMPTY_TRACK);
      reload();
    } catch (cause) {
      setTrack(current => ({ ...current, busy: false, serverError: cause?.message || 'The entry could not be removed.' }));
    }
  }, [reload, track.identity, track.model]);

  const retryTabs = useCallback(async () => {
    if (!track.identity) return;
    try {
      const tabs = await loadTrackTabs(track.identity);
      setTrack(current => ({ ...current, tabs }));
    } catch {
      setTrack(current => ({
        ...current,
        tabs: current.tabs.map(tab => (tab.status === 'error' ? { ...tab, error: 'Tabs could not be reloaded.' } : tab)),
      }));
    }
  }, [track.identity]);

  // Tags: both the Tags dialog and the track dialog's Tags tab write through here.
  const applyTags = useCallback(async (tagList, toggledId, target = identity) => {
    const next = tagList.map(tag => (tag.id === toggledId ? { ...tag, hasTag: !tag.hasTag } : tag));
    await setTags(target, next.filter(tag => tag.hasTag).map(tag => tag.id));
    return next;
  }, [identity]);

  const toggleTrackTag = useCallback(async tag => {
    const tab = track.tabs.find(entry_ => entry_.kind === 'tags');
    const tagList = tab?.tags || [];
    const mark = (pending, errorText) => setTrack(current => ({
      ...current,
      tabs: current.tabs.map(entry_ => (entry_.kind !== 'tags' ? entry_ : {
        ...entry_,
        tags: (entry_.tags || []).map(row => (row.id === tag.id
          ? { ...row, pending, error: errorText, hasTag: errorText || pending ? row.hasTag : !row.hasTag }
          : row)),
      })),
    }));
    mark(true, '');
    try {
      await applyTags(tagList, tag.id, track.identity);
      mark(false, '');
    } catch {
      mark(false, 'Could not update this tag.');
    }
  }, [applyTags, track.tabs, track.identity]);

  const createTrackTag = useCallback(async name => {
    try {
      const created = await createTag(name);
      const tab = track.tabs.find(entry_ => entry_.kind === 'tags');
      const applied = (tab?.tags || []).filter(row => row.hasTag).map(row => row.id);
      await setTags(track.identity, [...applied, String(created.id)]);
      setTrack(current => ({
        ...current,
        tabs: current.tabs.map(entry_ => (entry_.kind !== 'tags' ? entry_ : {
          ...entry_,
          tags: [...(entry_.tags || []), { id: String(created.id), name, hasTag: true, pending: false, error: '' }],
        })),
      }));
      return true;
    } catch {
      return false;
    }
  }, [track.identity, track.tabs]);

  const saveArtworkForItem = useCallback(async imageUrl => {
    if (!track.identity || !imageUrl) return;
    await saveArtwork(track.identity, imageUrl);
    reload();
  }, [track.identity, reload]);

  // Page-level dialogs.
  const closeDialog = useCallback(() => setDialog({ kind: '', busy: false, error: '', data: null }), []);

  const openTags = useCallback(async () => {
    setDialog({ kind: 'tags', busy: true, error: '', data: [] });
    try {
      setDialog({ kind: 'tags', busy: false, error: '', data: await loadTags(identity) });
    } catch (cause) {
      setDialog({ kind: 'tags', busy: false, error: cause?.message || "Couldn't load your tags.", data: [] });
    }
  }, [identity]);

  const toggleDialogTag = useCallback(async tag => {
    setDialog(current => ({ ...current, busy: true, error: '' }));
    try {
      const next = await applyTags(dialog.data, tag.id);
      setDialog({ kind: 'tags', busy: false, error: '', data: next });
    } catch {
      setDialog(current => ({ ...current, busy: false, error: 'Could not update this tag.' }));
    }
  }, [applyTags, dialog.data]);

  const createDialogTag = useCallback(async name => {
    try {
      const created = await createTag(name);
      const applied = (dialog.data || []).filter(row => row.hasTag).map(row => row.id);
      await setTags(identity, [...applied, String(created.id)]);
      setDialog(current => ({
        ...current,
        data: [...(current.data || []), { id: String(created.id), name, hasTag: true, pending: false, error: '' }],
      }));
      return true;
    } catch {
      return false;
    }
  }, [dialog.data, identity]);

  // Lists for the page item, or for an episode row's own identity.
  const openLists = useCallback(async (target = identity, title = model.title) => {
    setDialog({ kind: 'lists', busy: true, error: '', target, data: { status: 'loading', membership: {}, model: null, pending: {}, errors: {} } });
    try {
      const data = normalizeListsModel(await loadLists(target, title));
      setDialog({ kind: 'lists', busy: false, error: '', target, data: { status: 'ready', model: data, membership: listsMembership(data), pending: {}, errors: {} } });
    } catch {
      setDialog({ kind: 'lists', busy: false, error: '', target, data: { status: 'error', membership: {}, model: null, pending: {}, errors: {} } });
    }
  }, [identity, model.title]);

  const toggleListMembership = useCallback(async list => {
    const data = dialog.data;
    if (!data || data.pending[list.id]) return;
    const patch = value => setDialog(current => ({ ...current, data: { ...current.data, ...value(current.data) } }));
    patch(current => ({ pending: { ...current.pending, [list.id]: true }, errors: { ...current.errors, [list.id]: '' } }));
    try {
      const result = await toggleList(dialog.target || identity, list.id, Boolean(data.membership[list.id]));
      patch(current => ({ membership: applyListToggle(current.membership, list.id, result.hasItem), pending: { ...current.pending, [list.id]: false } }));
    } catch (cause) {
      patch(current => ({ pending: { ...current.pending, [list.id]: false }, errors: { ...current.errors, [list.id]: cause?.message || listLabels.toggleFailed } }));
    }
  }, [dialog.data, identity]);

  const openNotes = useCallback(note => {
    const target = note || (model.tracking ? { id: String(model.tracking.id), text: model.tracking.notes } : null);
    if (!target || target.id === 'null') {
      openTrack();
      return;
    }
    setDialog({ kind: 'notes', busy: false, error: '', data: target });
  }, [model.tracking, openTrack]);

  const saveNotes = useCallback(async text => {
    setDialog(current => ({ ...current, busy: true, error: '' }));
    try {
      await saveEntryNotes(identity, dialog.data.id, text);
      closeDialog();
      reload();
    } catch (cause) {
      setDialog(current => ({ ...current, busy: false, error: cause?.message || 'The notes could not be saved.' }));
    }
  }, [closeDialog, dialog.data, identity, reload]);

  const removePlay = useCallback(async entry_ => {
    try {
      await deleteHistoryEntry(identity, entry_.id);
      reload();
    } catch (cause) {
      setNotice(cause?.message || 'The play could not be removed.');
    }
  }, [identity, reload]);

  const openSeerr = useCallback(() => setDialog({ kind: 'seerr', busy: false, error: '', data: seerr.state }), [seerr.state]);
  const sendSeerr = useCallback(async seasons => {
    setDialog(current => ({ ...current, busy: true, error: '' }));
    try {
      const state = await requestSeerr(identity, seasons);
      setSeerr({ available: true, state });
      setDialog({ kind: 'seerr', busy: false, error: '', data: state });
    } catch (cause) {
      setDialog(current => ({ ...current, busy: false, error: cause?.message || 'The request could not be sent.' }));
    }
  }, [identity]);

  const runSync = useCallback(async () => {
    setNotice('Syncing metadata…');
    try {
      await syncMetadata(identity);
      setNotice('Metadata synced successfully.');
      reload();
    } catch (cause) {
      setNotice(cause?.message || 'Metadata could not be synced.');
    }
  }, [identity, reload]);

  const rate = useCallback(async score => {
    try {
      await saveScore(identity, score);
      reload();
    } catch (cause) {
      setNotice(cause?.message || 'The score could not be saved.');
    }
  }, [identity, reload]);

  useEffect(() => {
    if (!identity || !loaded) return undefined;
    let cancelled = false;
    setProgress({ data: null, open: false });
    loadProgressCard(identity)
      .then(data => { if (!cancelled) setProgress({ data, open: false }); })
      .catch(() => {});
    return () => { cancelled = true; };
  }, [identity, loaded, attempt]);

  // Backdrop, logo, trailer and gallery plus the stored score chips and series graphs.
  useEffect(() => {
    if (!identity || !loaded) return undefined;
    let cancelled = false;
    loadArtwork(identity).then(next => { if (!cancelled) setBackdrop(next); });
    loadScores(identity).then(next => { if (!cancelled) setScores(next); });
    return () => { cancelled = true; };
  }, [identity, loaded]);

  // The web split button: Check-in (and its Pause, Finish, Stop) ahead of Edit.
  useEffect(() => {
    if (!identity || !loaded || !model.tracked) { setCheckin([]); return undefined; }
    let cancelled = false;
    loadCheckIn(identity)
      .then(data => { if (!cancelled) setCheckin(data?.actions || []); })
      .catch(() => { if (!cancelled) setCheckin([]); });
    return () => { cancelled = true; };
  }, [identity, loaded, model.tracked, attempt]);

  const collectionAddress = useMemo(() => (identity ? collectionAddressForIdentity(identity) : null), [identity]);

  // The copy dialog serves the page item or an episode row's identity.
  function openCopyDialog(target = identity, title = model.title) {
    setCopy({
      open: true,
      target,
      title,
      values: emptyCopyValues(copyFieldsFor(target.mediaType)),
      errors: {},
      busy: false,
    });
  }

  async function saveCopy() {
    if (copy.busy) return;
    setCopy(current => ({ ...current, busy: true, errors: {} }));
    try {
      await createCollectionTransport().addCopy({
        address: collectionAddressForIdentity(copy.target),
        values: copy.values,
      });
      const loaded = await loadCollectionEntries(identity);
      setCollection({ status: 'ready', ...loaded, error: '' });
      setCopy({ open: false, values: {}, errors: {}, busy: false });
    } catch (cause) {
      setCopy(current => ({
        ...current,
        busy: false,
        errors: { form: cause?.message || 'The copy could not be saved.' },
      }));
    }
  }

  const [ratingOpen, setRatingOpen] = useState(false);
  const score = model.score;
  const ratingSlot = identity && (model.tracked || isEpisode) ? <RatingChip
    value={score}
    scaleMax={10}
    displayValue={score == null ? null : score.toFixed(1)}
    layout="card"
    labels={{ yourScore: 'Your rating', yourRating: 'Your rating', rate: 'Rate', addRating: 'Add rating', editRating: 'Edit rating', close: 'Close', prompt: `Rate this ${PROMPT_NOUNS[identity.mediaType] || 'item'}` }}
    renderStar={RatingStarIcon}
    palette={palette.rating}
    open={ratingOpen}
    onOpenChange={setRatingOpen}
    onSelect={rate} /> : null;

  const status = model.tracking?.status || '';
  const offersNewEntry = model.tracked && identity && (
    ADD_ENTRY_ALWAYS.has(identity.mediaType)
    || (ADD_ENTRY_WHEN_COMPLETED.has(identity.mediaType) && status === 'Completed'));
  const primaryLabel = !model.tracked ? 'Add to tracker'
    : (offersNewEntry ? 'Add new entry' : (status.replace('In progress', 'In Progress') || 'Edit'));
  const runCheckinAction = async action => {
    try {
      const next = await runCheckIn(identity, action.key);
      setCheckin(next?.actions || []);
      if (action.then === 'edit') openTrack(false);
      else reload();
    } catch (cause) {
      setNotice(cause?.message || 'The check-in could not be updated.');
    }
  };
  const trackActions = checkin.map(action => ({
    key: action.key,
    label: action.key === 'edit' ? (status.replace('In progress', 'In Progress') || action.label) : action.label,
    icon: action.icon,
    onPress: () => {
      if (action.key === 'edit') openTrack(false);
      else if (action.key === 'create') openTrack(true);
      else runCheckinAction(action);
    },
  }));
  const trackRest = trackActions.slice(1);
  const historyItem = { key: 'history', label: 'View history', icon: 'history', onPress: () => setDialog({ kind: 'history', busy: false, error: '', data: null }) };
  const readingType = ['book', 'manga', 'comic'].includes(identity?.mediaType);
  const moreItems = identity ? [
    identity.source !== 'manual' ? { key: 'sync', label: 'Sync metadata', icon: 'sync', onPress: runSync } : null,
    model.tracked && model.catalogItemId && !isEpisode ? { key: 'cover', label: 'Change cover', icon: 'image', onPress: () => setDialog({ kind: 'cover', busy: false, error: '', data: null }) } : null,
    model.tracked && model.catalogItemId && identity.source === 'hardcover' && identity.mediaType === 'book'
      ? { key: 'edition', label: 'Edition', icon: 'book', onPress: () => setDialog({ kind: 'edition', busy: false, error: '', data: null }) } : null,
    seerr.available ? { key: 'seerr', label: 'Request in Seerr', icon: 'listAdd', onPress: openSeerr } : null,
  ].filter(Boolean) : [];
  const actions = identity ? {
    primary: trackActions.length ? {
      label: trackActions[0].label,
      icon: trackActions[0].icon,
      onPress: trackActions[0].onPress,
    } : {
      label: primaryLabel,
      icon: model.tracked && !offersNewEntry ? 'edit' : 'plus',
      onPress: () => openTrack(Boolean(offersNewEntry)),
    },
    edit: trackActions.length
      ? (trackRest.length > 1
        ? { label: 'More tracking actions', icon: 'chevronDown', onPress: () => setDialog({ kind: 'trackmenu', busy: false, error: '', data: null }) }
        : trackRest.length === 1
          ? { label: trackRest[0].key === 'edit' ? `Edit entry, ${status}` : trackRest[0].label, icon: trackRest[0].icon, onPress: trackRest[0].onPress }
          : null)
      : offersNewEntry ? { label: `Edit entry, ${status}`, onPress: () => openTrack(false) } : null,
    quick: [
      // The web reading pages have no links button, and keep history and sync as their own buttons.
      model.sourceUrl && !readingType ? {
        key: 'source',
        label: model.sourceName ? `Open on ${model.sourceName}` : 'Open source',
        icon: 'link',
        onPress: () => Linking.openURL(model.sourceUrl),
      } : null,
      { key: 'tags', label: 'Tags', icon: 'tag', onPress: () => openTags() },
      { key: 'notes', label: 'Notes', icon: 'page', onPress: () => openNotes() },
      { key: 'lists', label: 'Add to list', icon: 'listAdd', onPress: () => openLists() },
      // The web keeps history beside the other buttons, and folds it into the
      // "more" menu together with Sync metadata and Seerr when those exist.
      ...(readingType ? [historyItem, moreItems.find(item => item.key === 'sync')] : [
        moreItems.length ? { key: 'more', label: 'More', icon: 'ellipsis', onPress: () => setDialog({ kind: 'more', busy: false, error: '', data: null }) }
          : historyItem,
      ]).filter(Boolean).map(item => ({ ...item, label: item.key === 'sync' ? 'Sync metadata' : item.label })),
    ].filter(Boolean),
  } : null;

  const seasonSelector = isSeason ? {
    seasons: model.seasons || [],
    activeNumber: identity.seasonNumber,
    onSelect: season => open({ identity: season.identity, title: season.title }),
  } : null;

  const siblings = model.siblingEpisodes || [];
  const at = isEpisode ? siblings.findIndex(row => Number(row.number) === Number(identity.episodeNumber)) : -1;
  const stepper = isEpisode && at >= 0 ? {
    previous: siblings[at - 1],
    next: siblings[at + 1],
    onOpen: row => openChild(row),
  } : null;

  const hasSeasonRows = Boolean(model.seasons?.length) && identity?.mediaType === 'tv';
  const childrenModel = isSeason || isAnime ? {
    kind: 'tv',
    seasons: [],
    episodes: isSeason || isAnime ? [...episodes.rows]
      .sort((left, right) => (episodes.order === 'desc' ? -1 : 1) * ((Number(left.number) || 0) - (Number(right.number) || 0)))
      .map(row => ({
        ...row,
        actions: [
          ...(isAnime ? [{ key: 'track', label: 'Track Episode' }] : [
          row.watched
            ? { key: 'unwatch', label: 'Mark unwatched' }
            : { key: 'watch', label: 'Mark watched' }]),
          { key: 'collection', label: 'Collection' },
          ...(row.canList ? [{ key: 'lists', label: 'Add to custom lists' }] : []),
          { key: 'history', label: 'View your activity history' },
        ],
      })) : [],
  } : null;
  // The web show page lists its seasons as titled poster cards, like its related grids.
  const seasonCards = hasSeasonRows && !isSeason ? model.seasons.map(season => ({
    key: season.key,
    row: season,
    title: season.number === 0 ? 'Specials' : `Season ${season.number}`,
    image: season.image || '',
    identity: season.identity,
  })) : [];
  const issuesSlot = identity?.mediaType === 'comic' && (issues.rows.length || issues.status === 'loading') ? <DetailIssueCards
    rows={issues.rows} total={issues.total} loading={issues.status === 'loading'} error={issues.error}
    layout={issues.layout} onLayout={layout => setIssues(current => ({ ...current, layout }))}
    onOpen={issue => openChild(issue)} onTrack={issue => openTrack(false, issue.identity)} onLists={issue => openLists(issue.identity, issue.title)}
    onMore={() => loadMoreIssues(false)} palette={palette} /> : null;
  const childrenSlot = issuesSlot || (seasonCards.length ? <DetailRelatedGrid title="Seasons" items={seasonCards} palette={palette}
    onOpen={season => openChild(season.row)} /> : childrenModel ? <View style={styles.children}>
    {episodes.status === 'loading' && !episodes.rows.length ? <View style={styles.childrenLoading}>
      <ActivityIndicator color={palette.accent} />
      <Text style={styles.dialogText}>Loading episodes…</Text>
    </View> : null}
    {episodes.error ? <View style={styles.errorRow}>
      <Text style={[styles.dialogText, { color: palette.danger }]}>{episodes.error}</Text>
      <Button label="Try again" tone="surface" palette={palette.button} onPress={loadEpisodes} />
    </View> : null}
    <DetailEpisodeCards
      nativeAnime={isAnime}
      loadMore={isAnime ? episodes.loadMore : null}
      onMore={() => loadEpisodes(true)}
      loadingMore={episodes.status === 'loading'}
      title="Episodes"
      count={childrenModel.episodes.length}
      order={episodes.order}
      orderLabel={episodes.order === 'desc' ? 'Newest first' : 'Oldest first'}
      onOrderChange={() => setEpisodes(current => ({ ...current, order: current.order === 'asc' ? 'desc' : 'asc' }))}
      episodes={childrenModel.episodes}
      labels={{ rate: 'Rate' }}
      palette={palette}
      renderRating={renderRating}
      onOpen={openChild}
      onAction={(key, child) => key === 'track' ? openTrack(false, child.identity) : runChildAction(key, child)}
      onRate={rateChild} />
  </View> : null);

  // The episode page (web episode_details): its own header, picker and track button.
  const episodeHeader = isEpisode ? {
    image: model.artwork?.src,
    title: model.title,
    showTitle: model.parent?.title || '',
    seasonTitle: `Season ${identity.seasonNumber}`,
    numberLabel: identity.episodeNumber != null ? `Ep ${identity.episodeNumber}` : '',
    airDate: model.releaseDate,
    watchedText: model.plays ? (model.plays === 1 ? 'Watched once' : `Watched ${model.plays} times`) : '',
    genres: model.parentGenres || [],
  } : null;
  const episodeSelector = isEpisode && siblings.length ? {
    items: siblings.map(row => ({
      key: row.key,
      label: `${row.number}. ${row.title}`,
      current: Number(row.number) === Number(identity.episodeNumber),
      row,
    })),
    previous: stepper?.previous,
    next: stepper?.next,
    onOpen: item => openChild(item.row || item),
  } : null;
  const episodeRating = isEpisode && identity && (model.tracked || score != null) ? <RatingChip
    value={score}
    scaleMax={10}
    displayValue={score == null ? null : score.toFixed(1)}
    labels={{ yourScore: 'Your rating', yourRating: 'Your rating', rate: 'Rate', addRating: 'Add rating', editRating: 'Edit rating', close: 'Close' }}
    renderStar={RatingStarIcon}
    palette={palette.rating}
    open={ratingOpen}
    onOpenChange={setRatingOpen}
    onSelect={rate} /> : null;

  // Cast and crew open the person page, like the web links.
  const openPerson = person => navigate?.('People', {
    identity: { kind: 'person', source: identity?.source, personId: person.personId },
  });

  const parentLink = model.parent?.title ? { title: model.parent.title } : null;
  const dialogTags = dialog.kind === 'tags' ? dialog.data || [] : [];

  return <Screen chrome={false}>
    <Pressable accessibilityRole="button" accessibilityLabel="Back" onPress={onBack} style={styles.back}>
      <Icon spec={actionIcons.chevronLeft} size={24} color={palette.accent} />
    </Pressable>
    {isEpisode ? <DetailEpisodePageView
      outlinedGenres
      model={{ ...model, providerScores: mergeScoreChips(model.providerScores, scores) }}
      episode={episodeHeader}
      palette={palette}
      loading={!loaded}
      error={error}
      onRetry={entry ? reload : undefined}
      selector={episodeSelector}
      track={{
        watched: model.plays > 0,
        label: model.plays > 0 ? 'Watched' : 'Mark Watched',
        onPress: () => openTrack(false),
      }}
      quick={[
        { key: 'notes', label: 'Add or edit notes', icon: 'page', onPress: () => openNotes() },
        { key: 'lists', label: 'Add to custom lists', icon: 'listAdd', onPress: () => openLists() },
        { key: 'history', label: 'View your activity history', icon: 'history', onPress: () => setDialog({ kind: 'history', busy: false, error: '', data: null }) },
      ]}
      ratingSlot={episodeRating}
      onOpenShow={model.parent ? () => open({ identity: model.parent.identity, title: model.parent.title }) : undefined}
      onOpenSeason={() => open({ identity: { ...identity, mediaType: 'season', episodeNumber: undefined }, title: episodeHeader.seasonTitle })}
      onOpenPerson={openPerson}
      onEditNote={openNotes} /> : <DetailPageView
      outlinedGenres
      model={{
        ...(progress.data?.watched_text
          ? { ...model, activityLine: activityLineWithWatched(model.activityLine, progress.data.watched_text) }
          : model),
        providerScores: mergeScoreChips(model.providerScores, scores),
        ...(isAnime && episodes.related ? { relatedSections: relatedSections({ related: episodes.related }, identity?.source) } : {}),
      }}
      backdrop={backdrop}
      scoreGraphs={scores.graphs}
      gameLengths={scores.gameLengths}
      onOpenLink={url => Linking.openURL(url)}
      palette={palette}
      loading={!loaded}
      error={error}
      onRetry={entry ? reload : undefined}
      parentLink={parentLink}
      onOpenParent={() => open({ identity: model.parent.identity, title: model.parent.title })}
      actions={actions}
      ratingSlot={ratingSlot}
      ratingWide={score == null && !model.providerScoreDerived}
      progressSlot={progress.data ? <ProgressCard
        model={progress.data.card}
        labels={progress.data.model?.labels}
        palette={progressDetailPalette}
        onOpen={() => setProgress(current => ({ ...current, open: true }))} /> : null}
      seasonSelector={seasonSelector}
      stepper={stepper}
      collection={identity ? { ...collection, onAdd: collectionAddress ? () => openCopyDialog() : null } : null}
      childrenSlot={childrenSlot}
      onEditNote={openNotes}
      onRemovePlay={identity ? removePlay : undefined}
      onOpenRecommendation={item => open({ identity: item.identity, title: item.title })}
      onOpenStudio={studio => navigate?.('People', { identity: { kind: 'studio', source: studio.source || identity?.source, studioId: studio.id } })}
      onOpenPerson={openPerson} />}
    {notice ? <Text accessibilityLiveRegion="polite" style={styles.notice}>{notice}</Text> : null}
    {!entry ? <Text style={styles.notice}>{detailPageLabels.error}</Text> : null}
    <TrackDialog
      open={track.open}
      model={track.status === 'ready' ? track.model : null}
      values={track.values}
      status={track.status}
      serverError={track.serverError}
      busy={track.busy}
      palette={formPalette}
      tabs={track.tabs}
      onChange={(name, value) => setTrack(current => ({ ...current, values: { ...current.values, [name]: value } }))}
      onSubmit={submitTrack}
      onDelete={track.tracked ? removeTrack : undefined}
      onClose={() => setTrack(EMPTY_TRACK)}
      onRetry={() => openTrack(false, track.identity)}
      onRetryTabs={retryTabs}
      onTagToggle={toggleTrackTag}
      onTagCreate={createTrackTag}
      onArtworkSave={saveArtworkForItem}
      onDiscoverToggle={(itemId, hidden) => setDiscoverHidden(itemId, hidden)} />
    <TagAssignmentDialog
      open={dialog.kind === 'tags'}
      item={{ title: model.title }}
      tags={dialogTags}
      palette={formPalette}
      busy={dialog.busy}
      error={dialog.kind === 'tags' ? dialog.error : ''}
      onToggle={toggleDialogTag}
      onCreate={createDialogTag}
      onClose={closeDialog} />
    <MediaCardActionHost open={dialog.kind === 'lists'} action={{ title: 'Lists' }} palette={formPalette} onClose={closeDialog}>
      {dialog.kind === 'lists' && dialog.data ? <ListsForm
        model={dialog.data.model}
        membership={dialog.data.membership}
        tag=""
        status={dialog.data.status}
        pending={dialog.data.pending}
        errors={dialog.data.errors}
        labels={listLabels}
        palette={formPalette}
        showHeader={false}
        onTagChange={() => {}}
        onRetry={() => openLists(dialog.target || identity)}
        onClose={closeDialog}
        onToggle={toggleListMembership} /> : null}
    </MediaCardActionHost>
    {progress.data ? <ProgressDialog
      visible={progress.open}
      title={model.title}
      model={progress.data.model}
      labels={progress.data.model?.labels}
      palette={progressDetailPalette}
      onClose={() => setProgress(current => ({ ...current, open: false }))}
      onOpenSeason={href => { setProgress(current => ({ ...current, open: false })); open({ href }); }}
      onOpenEpisode={href => { setProgress(current => ({ ...current, open: false })); open({ href }); }} /> : null}
    <CollectionCopyDialog
      visible={copy.open}
      item={copy.open ? { title: copy.title, mediaType: copy.target?.mediaType } : null}
      fields={copyFieldsFor(copy.target?.mediaType)}
      values={copy.values}
      errors={copy.errors}
      palette={palette}
      canMutate
      busy={copy.busy}
      onClose={() => setCopy(current => ({ ...current, open: false }))}
      onChange={(name, value) => setCopy(current => ({
        ...current,
        values: { ...current.values, [name]: value },
        errors: { ...current.errors, [name]: '' },
      }))}
      onSave={saveCopy} />
    <MediaCardActionHost open={dialog.kind === 'more'} action={{ title: model.title }} palette={palette} onClose={closeDialog}>
      {[historyItem, ...moreItems].map(item => <Pressable key={item.key} accessibilityRole="button"
        onPress={() => { closeDialog(); item.onPress(); }} style={styles.moreRow}>
        <Icon spec={actionIcons[item.icon]} size={16} color={palette.textSecondary} />
        <Text style={[styles.dialogText, { color: palette.text }]}>{item.label}</Text>
      </Pressable>)}
    </MediaCardActionHost>
    <MediaCardActionHost open={dialog.kind === 'trackmenu'} action={{ title: model.title }} palette={palette} onClose={closeDialog}>
      {trackRest.map(item => <Pressable key={item.key} accessibilityRole="button"
        onPress={() => { closeDialog(); item.onPress(); }} style={styles.moreRow}>
        <Text style={[styles.dialogText, { color: palette.text }]}>{item.label}</Text>
      </Pressable>)}
    </MediaCardActionHost>
    <CoverDialog open={dialog.kind === 'cover'} itemId={model.catalogItemId} palette={formPalette}
      onSaved={() => { closeDialog(); reload(); }} onClose={closeDialog} />
    <EditionDialog open={dialog.kind === 'edition'} itemId={model.catalogItemId} palette={formPalette}
      onSaved={() => { closeDialog(); reload(); }} onClose={closeDialog} />
    <NotesDialog open={dialog.kind === 'notes'} note={dialog.data} busy={dialog.busy}
      error={dialog.kind === 'notes' ? dialog.error : ''} onSave={saveNotes} onClose={closeDialog} />
    <PlaysDialog open={dialog.kind === 'history'} identity={dialog.target || identity} entries={dialog.target ? [] : model.history || []}
      onRemove={removePlay} onClose={closeDialog} />
    <SeerrDialog open={dialog.kind === 'seerr'} state={dialog.kind === 'seerr' ? dialog.data : null}
      busy={dialog.busy} error={dialog.kind === 'seerr' ? dialog.error : ''}
      onRequest={sendSeerr} onClose={closeDialog} />
  </Screen>;
}

export default function DetailScreen({ params, onBack, navigate }) {
  const entry = useMemo(
    () => params?.item || (params?.href ? { href: params.href } : null),
    [params?.item, params?.href],
  );
  const key = identityKey(identityFromItem(entry)) || String(params?.href || '');
  // One page instance per item so state never leaks between two details.
  return <DetailPage key={key} entry={entry} onBack={onBack} navigate={navigate} />;
}

const styles = StyleSheet.create({
  back: { position: 'absolute', top: 0, left: 0, minHeight: 40, minWidth: 44, justifyContent: 'center', zIndex: 5 },
  children: { gap: spacing.sm },
  moreRow: { flexDirection: 'row', alignItems: 'center', gap: 12, paddingVertical: 12 },
  seasonGrid: { gap: spacing.sm },
  seasonHeading: { color: palette.text, fontSize: 20, fontWeight: '700' },
  childrenLoading: { gap: spacing.sm, alignItems: 'center', paddingVertical: spacing.md },
  errorRow: { gap: spacing.sm },
  dialogText: { color: palette.textSecondary, fontSize: 14, lineHeight: 20 },
  dialogActions: { flexDirection: 'row', justifyContent: 'flex-end', gap: spacing.sm },
  dialogScroll: { maxHeight: 360 },
  notesInput: {
    minHeight: 140,
    borderWidth: 1,
    borderRadius: 8,
    borderColor: palette.border,
    backgroundColor: palette.surfaceStrong,
    color: palette.text,
    padding: spacing.md,
    fontSize: 15,
  },
  dayGroup: { gap: spacing.sm, marginBottom: spacing.md },
  dayHeading: { fontWeight: '700', fontSize: 16 },
  dayEntry: { borderRadius: 8, padding: spacing.sm, gap: 2 },
  playRow: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm, paddingVertical: spacing.sm },
  playBody: { flex: 1, minWidth: 0 },
  playMeta: { color: palette.textMuted, fontSize: 12 },
  notice: { color: palette.textMuted, fontSize: 13 },
});
