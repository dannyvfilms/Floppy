import React from 'react';
import { ActivityIndicator, StyleSheet, Text, View, useWindowDimensions } from 'react-native';
import { Button } from '../ui/Button';
import {
  DetailActions,
  DetailHeader,
  DetailSection,
  DetailSynopsis,
} from '../ui/DetailComposition';
import { DetailEpisodeActions, DetailEpisodeHeader } from '../ui/DetailEpisode';
import {
  DetailActionBar,
  DetailBackdrop,
  DetailBlock,
  DetailChipCard,
  DetailCollectionBlock,
  DetailEmpty,
  DetailGameLengths,
  DetailHeroBackdrop,
  DetailListCard,
  DetailRelatedGrid,
  DetailHistoryBlock,
  DetailInfoCard,
  DetailLinkRow,
  DetailLoading,
  DetailNotesBlock,
  DetailPageHero,
  DetailPeopleGrid,
  DetailPeopleRail,
  DetailPosterRail,
  DetailScoreRow,
  DetailSeasonSelector,
  DetailSkeleton,
  DetailStepper,
} from '../ui/DetailPage';

// One detail content composition for web and Expo. The release detail page is
// server-owned: the browser mounts this view in `header` and `synopsis` parts
// over the existing fallback, while the native screen mounts `full` with the
// shared action sections below. Section order, labels, loading/error states and
// the action intents live here; server forms, dialogs and permissions stay in
// their adapters.

export const detailSectionPlan = [
  { id: 'genres', title: 'Genres' },
  { id: 'providers', title: 'Where to watch' },
  { id: 'score', title: 'Your score' },
  { id: 'progress', title: 'Your progress' },
  { id: 'check-in', title: 'Check-in' },
  { id: 'tracking', title: 'Tracking' },
  { id: 'notes', title: 'Your notes' },
  { id: 'artwork', title: 'Artwork and editions' },
  { id: 'children', title: 'Seasons, episodes and issues' },
  { id: 'related', title: 'Related media' },
];

export const detailLabels = {
  loading: 'Loading detail…',
  retry: 'Try again',
  error: 'The detail could not be loaded.',
};

function orderedSections(model) {
  const supplied = new Map((model?.sections || []).map(section => [section.id, section]));
  const merged = detailSectionPlan.map(plan => {
    const section = supplied.get(plan.id);
    supplied.delete(plan.id);
    return section ? { ...plan, ...section } : null;
  }).filter(Boolean);
  return [...merged, ...supplied.values()];
}

export function DetailView({
  model = {},
  labels = {},
  palette = {},
  part = 'full',
  showArtwork = true,
  renderSynopsis,
  sectionBodies = {},
  loading = false,
  error = '',
  onRetry,
  children,
}) {
  const copy = { ...detailLabels, ...(labels || {}) };

  if (part === 'header') {
    return <DetailHeader model={model} labels={labels} palette={palette} showArtwork={showArtwork} />;
  }

  if (part === 'synopsis') {
    return renderSynopsis
      ? renderSynopsis({ model, labels, palette })
      : <DetailSynopsis model={model} labels={labels} palette={palette} />;
  }

  const sections = orderedSections(model);
  const hasSections = sections.some(section => section.body || sectionBodies[section.id]);

  return <View style={styles.root}>
    {error ? <View style={[styles.notice, { borderColor: palette.danger }]}>
      <Text accessibilityLiveRegion="polite" style={[styles.noticeText, { color: palette.danger }]}>{error || copy.error}</Text>
      {onRetry ? <Button label={copy.retry} tone="surface" palette={palette} onPress={onRetry} /> : null}
    </View> : null}
    {loading ? <View accessibilityLiveRegion="polite" style={styles.loading}>
      <ActivityIndicator color={palette.accent} />
      <Text style={[styles.loadingText, { color: palette.textMuted }]}>{copy.loading}</Text>
    </View> : <>
      {part !== 'sections' ? <>
        <DetailHeader model={model} labels={labels} palette={palette} showArtwork={showArtwork} />
        {renderSynopsis
          ? renderSynopsis({ model, labels, palette })
          : <DetailSynopsis model={model} labels={labels} palette={palette} />}
        <DetailActions model={model} labels={labels} palette={palette} />
      </> : null}
      {hasSections ? sections.map(section => {
        const body = sectionBodies[section.id] || section.body;
        if (!body && !section.copy) return null;
        return <DetailSection key={section.id || section.title}
          section={{ ...section, body }} palette={palette} />;
      }) : null}
    </>}
    {children || null}
  </View>;
}

const styles = StyleSheet.create({
  root: { gap: 18, minWidth: 0 },
  pageRoot: { gap: 28, minWidth: 0 },
  notice: { gap: 8, borderWidth: 1, borderRadius: 8, padding: 12, alignItems: 'flex-start' },
  noticeText: { fontSize: 13, lineHeight: 18 },
  loading: { alignItems: 'center', justifyContent: 'center', gap: 10, paddingVertical: 48 },
  loadingText: { fontSize: 13 },
});

export const detailPageLabels = {
  details: 'Details',
  noDetails: 'No details available',
  genres: 'Genres',
  whereToWatch: 'Where to watch',
  collection: 'Collection',
  noCollection: 'No collection data available',
  addCollection: 'Add to collection',
  notes: 'Your Notes',
  editNote: 'Edit notes',
  history: 'Your History',
  showRepeats: 'Show Repeats',
  removePlay: 'Remove play',
  cast: 'Cast',
  crew: 'Crew',
  recommendations: 'Recommendations',
  studios: 'Studios',
  seasons: 'Seasons',
  previous: 'Previous',
  next: 'Next',
  loading: 'Loading',
  retry: 'Try again',
  error: 'The detail could not be loaded.',
};

/**
 * The native phone-width detail page, in the same top-to-bottom order as the
 * server page: hero, actions, rating, synopsis, history, Details, Genres,
 * Where to watch, Collection, notes, children (seasons and episodes), cast,
 * crew and recommendations. A section with no data renders nothing, except
 * the ones the web page keeps visible when empty (synopsis, Collection).
 */
export function DetailPageView({
  model = {},
  labels = {},
  palette = {},
  loading = false,
  error = '',
  onRetry,
  parentLink,
  actions,
  links = [],
  ratingSlot,
  progressSlot,
  stepper,
  seasonSelector,
  collection,
  childrenSlot,
  onOpenParent,
  onEditNote,
  onRemovePlay,
  onOpenRecommendation,
  onOpenPerson,
  onOpenStudio,
  extraCards,
  backdrop,
  scoreGraphs,
  gameLengths,
  onOpenLink,
  ratingWide,
  outlinedGenres = false,
}) {
  const copy = { ...detailPageLabels, ...labels };
  const [seasonMenu, setSeasonMenu] = React.useState(false);
  const { width } = useWindowDimensions();
  if (loading) return <DetailSkeleton palette={palette} />;
  // The web phone hero replaces the poster header once the backdrop exists (below 768px).
  const phoneHero = Boolean(backdrop?.hero) && width < 768;
  const heroMeta = model.sourceKind !== 'manual' && (model.metaYear || model.metaRuntime)
    ? [model.metaYear, model.metaRuntime].filter(Boolean).join(' \u00b7 ') : '';
  return <View style={styles.pageRoot}>
    {error ? <View style={[styles.notice, { borderColor: palette.danger }]}>
      <Text accessibilityLiveRegion="polite" style={[styles.noticeText, { color: palette.danger }]}>{error}</Text>
      {onRetry ? <Button label={copy.retry} tone="surface" palette={palette.button} onPress={onRetry} /> : null}
    </View> : null}
    {phoneHero ? <DetailHeroBackdrop artwork={backdrop} title={seasonSelector && parentLink ? parentLink.title : model.title} meta={heroMeta}
      seasonSwitch={seasonSelector ? {
        label: model.title,
        expanded: seasonMenu,
        onPress: seasonSelector.seasons.length > 1 ? () => setSeasonMenu(value => !value) : null,
      } : null}
      activityLine={model.activityLine && model.activityLine !== model.metaRuntime ? model.activityLine : ''} palette={palette} /> : <>
      <DetailBackdrop artwork={backdrop} palette={palette} onOpenLink={onOpenLink} />
      <DetailPageHero title={model.title} altTitle={model.altTitle} artwork={model.artwork}
        meta={heroMeta} activityLine={heroMeta && model.activityLine === model.metaRuntime ? '' : model.activityLine}
        activityDates={model.activityDates} parent={parentLink} onOpenParent={onOpenParent} palette={palette}
        seasonSwitch={seasonSelector ? {
          expanded: seasonMenu,
          onPress: seasonSelector.seasons.length > 1 ? () => setSeasonMenu(value => !value) : null,
        } : null} />
    </>}
    {actions ? <DetailActionBar primary={actions.primary} edit={actions.edit} quick={actions.quick} palette={palette} /> : null}
    <DetailLinkRow items={links} palette={palette} />
    <DetailScoreRow chips={model.providerScores || []} graphs={scoreGraphs} onOpenLink={onOpenLink} progressSlot={progressSlot} ratingWide={ratingWide} palette={palette}>{ratingSlot}</DetailScoreRow>
    <DetailSynopsis model={model} labels={labels} palette={palette} />
    {seasonSelector && seasonMenu ? <DetailSeasonSelector seasons={seasonSelector.seasons}
      activeNumber={seasonSelector.activeNumber} label={copy.seasons}
      onSelect={seasonSelector.onSelect} palette={palette} /> : null}
    {stepper ? <DetailStepper previous={stepper.previous} next={stepper.next} labels={copy}
      onOpen={stepper.onOpen} palette={palette} /> : null}
    <DetailHistoryBlock title={copy.history} entries={model.repeats || []} toggleLabel={copy.showRepeats} removeLabel={copy.removePlay}
      onRemove={onRemovePlay} palette={palette} />
    <DetailInfoCard title={copy.details} rows={model.details || []} emptyText={copy.noDetails} palette={palette} />
    <DetailChipCard title={copy.genres} items={model.genres || []} palette={palette} outlined={outlinedGenres} />
    <DetailListCard title={copy.studios} items={(model.studioLinks?.length ? model.studioLinks : model.studios || []).slice(0, 12)} palette={palette} onOpen={onOpenStudio} />
    {(model.watchProviders || []).map(group => <DetailChipCard key={group.market}
      title={`${copy.whereToWatch} (${group.market})`} items={group.names} palette={palette} />)}
    <DetailGameLengths data={gameLengths} onOpenLink={onOpenLink} palette={palette} />
    {extraCards}
    {collection ? <DetailBlock title={copy.collection} palette={palette}
      action={collection.onAdd ? { label: copy.addCollection, onPress: collection.onAdd } : null}>
      {collection.status === 'loading' ? <DetailLoading text={copy.loading} palette={palette} /> : null}
      {collection.status === 'error' ? <DetailEmpty text={collection.error} palette={palette} /> : null}
      {collection.status === 'ready' ? <DetailCollectionBlock counts={collection.counts || []}
        entries={collection.entries} empty={copy.noCollection} palette={palette} /> : null}
    </DetailBlock> : null}
    <DetailNotesBlock title={copy.notes} notes={model.notes || []} editLabel={copy.editNote}
      onEdit={onEditNote} palette={palette} />
    {(model.relatedSections || []).map(section => <DetailRelatedGrid key={section.id} title={section.title}
      items={section.items} palette={palette} onOpen={onOpenRecommendation} current={model.mediaId} />)}
    {childrenSlot || null}
    <DetailPeopleRail title={copy.cast} people={model.cast || []} palette={palette} onOpen={onOpenPerson} />
    <DetailPeopleRail title={copy.crew} people={model.crew || []} palette={palette} onOpen={onOpenPerson} />
    <DetailPosterRail title={copy.recommendations} items={model.recommendations || []} palette={palette}
      onOpen={onOpenRecommendation} />
  </View>;
}

export const detailEpisodeLabels = {
  selectEpisode: 'Select episode',
  previousEpisode: 'Previous episode',
  nextEpisode: 'Next episode',
};

/**
 * The episode page, in the server template's phone order: still, show title,
 * season / episode line, episode picker, synopsis, track button with its icon
 * buttons, score chips with the viewer's rating, genres, notes, cast and crew.
 */
export function DetailEpisodePageView({
  model = {},
  episode = {},
  labels = {},
  palette = {},
  loading = false,
  error = '',
  onRetry,
  selector,
  track,
  quick = [],
  ratingSlot,
  onOpenShow,
  onOpenSeason,
  onOpenPerson,
  onEditNote,
  outlinedGenres = false,
}) {
  const copy = { ...detailPageLabels, ...detailEpisodeLabels, ...labels };
  if (loading) return <DetailSkeleton palette={palette} />;
  return <View style={styles.pageRoot}>
    {error ? <View style={[styles.notice, { borderColor: palette.danger }]}>
      <Text accessibilityLiveRegion="polite" style={[styles.noticeText, { color: palette.danger }]}>{error}</Text>
      {onRetry ? <Button label={copy.retry} tone="surface" palette={palette.button} onPress={onRetry} /> : null}
    </View> : null}
    <DetailEpisodeHeader episode={episode} selector={selector} labels={copy} palette={palette}
      onOpenShow={onOpenShow} onOpenSeason={onOpenSeason} />
    <DetailSynopsis model={model} labels={labels} palette={palette} />
    <DetailEpisodeActions track={track} quick={quick} palette={palette} />
    <DetailScoreRow chips={model.providerScores || []} palette={palette} compact>{ratingSlot}</DetailScoreRow>
    <DetailChipCard title={copy.genres} items={episode.genres || []} palette={palette} outlined={outlinedGenres} />
    <DetailNotesBlock title={copy.notes} notes={model.notes || []} editLabel={copy.editNote}
      onEdit={onEditNote} palette={palette} />
    <DetailPeopleGrid title={copy.cast} people={model.cast || []} palette={palette} onOpen={onOpenPerson} />
    <DetailPeopleGrid title={copy.crew} people={model.crew || []} palette={palette} onOpen={onOpenPerson} />
  </View>;
}
