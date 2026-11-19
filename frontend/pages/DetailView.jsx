import React from 'react';
import { ActivityIndicator, Image, Pressable, ScrollView, StyleSheet, Text, useWindowDimensions, View } from 'react-native';
import { Button } from '../ui/Button';
import { DetailChildren } from '../ui/DetailChildren';
import { DetailRelated } from '../ui/DetailRelated';
import { RatingStars } from '../ui/RatingStars';
import { DetailSecondary } from '../ui/DetailSecondary';
import { PersonCard } from '../ui/People';
import { Rail } from '../ui/Rail';
import { MediaCard } from '../ui/MediaCard';
import {
  DetailActions,
  DetailChips,
  DetailHero,
  DetailMobileHero,
  DetailHeader,
  DetailSection,
  DetailSynopsis,
} from '../ui/DetailComposition';

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
  { id: 'activity', title: 'Your activity' },
  { id: 'collection', title: 'Collection' },
  { id: 'youtube-watch', title: 'Watched on YouTube' },
  { id: 'history', title: 'Recent history' },
  { id: 'notes', title: 'Your notes' },
];

export const detailLabels = {
  loading: 'Loading detail…',
  retry: 'Try again',
  error: 'The detail could not be loaded.',
};

function PeopleSection({ title, people = [], palette, onOpen, cardWidth, RailComponent = Rail }) {
  if (!people.length) return null;
  // Expo supplies Home's width; web detail casts use their separate media-card adapter.
  return <RailComponent title={title} items={people} itemWidth={cardWidth || 132} itemGap={16}
    windowCards palette={palette}
    renderItem={person => cardWidth ? <MediaCard width={cardWidth} palette={palette.mediaCard || palette}
      model={{ title: person.name, image: { src: person.imageUrl, fallback: person.imageFallback },
        lines: (person.cardLines ? person.cardLines.map(line => line.text) : [person.role]).filter(Boolean)
          .map(text => ({ parts: [{ text }], dormant: true })) }}
      onOpen={onOpen && person.person_id != null ? () => onOpen(person) : undefined} />
      : <PersonCard person={person} palette={palette}
        onOpen={onOpen && person.person_id != null ? () => onOpen(person) : undefined} />} />;
}

function DetailLinks({ groups = [], palette, onOpen }) {
  const rows = groups.flatMap(group => group.entries || []);
  if (!rows.length) return null;
  return <View style={styles.contentSection}>
    <Text accessibilityRole="header" style={[styles.contentTitle, { color: palette.text }]}>Links</Text>
    <View style={styles.linkGrid}>
      {rows.map((entry, index) => <Pressable key={`${entry.url}-${index}`} accessibilityRole="link"
        accessibilityLabel={entry.label} onPress={() => onOpen?.(entry.url)}
        style={[styles.linkChip, { borderColor: palette.border, backgroundColor: palette.surface }]}>
        {entry.logo_src ? <Image source={{ uri: entry.logo_src }} resizeMode="contain" style={styles.linkLogo}
          accessibilityLabel={`${entry.label} logo`} /> : null}
        <Text style={{ color: palette.text }}>{entry.label}</Text>
      </Pressable>)}
    </View>
  </View>;
}

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
  onOpenItem,
  onOpenExternal,
  onOpenVideo,
  onLoadMore,
  onChildAction,
  onRate,
  onRateChild,
  onRateMain,
  hideContent = false,
  actionsSlot,
  scoreSlot,
  sectionsSlot,
  childrenSlot,
  sectionSlots,
  childSlots,
  noticeSlot,
  ratingInScoreRow = false,
  onOpenPerson,
  onOpenMetadata,
  children,
  heroViewport,
  shelfCardWidth,
  railComponent: RailComponent = Rail,
}) {
  const copy = { ...detailLabels, ...(labels || {}) };
  const { width } = useWindowDimensions();

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
  const childContent = model.children ? <DetailChildren model={model.children}
    labels={model.childLabels || labels} palette={palette} variant="detail"
    onOpenSeason={season => onOpenItem?.(season.identity)}
    onOpenChild={item => onOpenItem?.(item.identity)}
    onAction={(key, item) => onChildAction?.(key, item)}
    onRate={(item, score) => onRateChild?.(item, score)}
    onLoadMore={model.children.nextPage ? onLoadMore : undefined}
    loadMoreLabel={model.children.nextLabel} /> : null;
  const childSection = model.children?.kind === 'issue' ? 'issues'
    : model.children?.episodes?.length ? 'episodes' : 'seasons';
  const related = (model.relatedSections || []).filter(section => section.id !== 'recommendations');
  const recommendations = (model.relatedSections || []).find(section => section.id === 'recommendations');
  const secondarySections = {
    ...sectionSlots,
    ...childSlots,
    ...(childContent && !childSlots?.[childSection] ? { [childSection]: childContent } : {}),
    cast: model.people?.cast?.length ? <PeopleSection title="Cast" people={model.people.cast} palette={palette} onOpen={onOpenPerson} cardWidth={shelfCardWidth} RailComponent={RailComponent} /> : null,
    crew: model.people?.crew?.length ? <PeopleSection title="Crew" people={model.people.crew} palette={palette} onOpen={onOpenPerson} cardWidth={shelfCardWidth} RailComponent={RailComponent} /> : null,
    related: related.length || model.steamDlcs?.length ? <DetailRelated
      model={{ sections: related, steamDlcs: model.steamDlcs || [] }} labels={model.relatedLabels || labels}
      palette={palette.mediaCard || palette} onOpen={onOpenItem} onOpenLink={onOpenExternal}
      onOpenExternal={onOpenExternal} onRate={onRate} /> : null,
    recommendations: recommendations?.items?.length ? <RailComponent title={recommendations.label || 'Recommendations'}
      items={recommendations.items} itemWidth={shelfCardWidth || 144} itemGap={16} windowCards palette={palette}
      renderItem={item => <MediaCard model={{ ...(item.model || item), altTitle: null }} width={shelfCardWidth || 144} palette={palette.mediaCard || palette}
        onOpen={() => onOpenItem?.(item.model || item)} onOpenLink={onOpenExternal}
        onRate={score => onRate?.(item.model || item, score)} />} /> : null,
  };
  const immersive = Boolean(heroViewport || width < 768) && Boolean(model?.artwork?.backdrop);

  return <View style={styles.root}>
    {error ? <View style={[styles.notice, { borderColor: palette.danger }]}>
      <Text accessibilityLiveRegion="polite" style={[styles.noticeText, { color: palette.danger }]}>{error || copy.error}</Text>
      {onRetry ? <Button label={copy.retry} tone="surface" palette={palette} onPress={onRetry} /> : null}
    </View> : null}
    {loading ? <View accessibilityLiveRegion="polite" style={styles.loading}>
      <ActivityIndicator color={palette.accent || '#6366f1'} />
      <Text style={[styles.loadingText, { color: palette.textMuted || '#a1a1aa' }]}>{copy.loading}</Text>
    </View> : !hideContent ? <>
      {part !== 'sections' ? <>
        {immersive ? <DetailMobileHero model={model} palette={palette} onOpenItem={onOpenItem} actions={actionsSlot} viewport={heroViewport} /> : <>
          <DetailHero model={model} palette={palette} onOpenVideo={onOpenVideo} />
          <DetailHeader model={model} labels={labels} palette={palette} showArtwork={showArtwork}
            compact={Boolean(heroViewport) && width < 768} viewportWidth={heroViewport?.width || width} />
          {actionsSlot || <DetailActions model={model} labels={labels} palette={palette} />}
        </>}
        {scoreSlot || null}
        {!model.secondary ? <><DetailChips chips={model.scoreChips || []} palette={palette} onOpen={onOpenExternal} />
        <DetailLinks groups={model.linkSections} palette={palette} onOpen={onOpenExternal} /></> : null}
        {renderSynopsis
          ? renderSynopsis({ model, labels, palette })
          : <DetailSynopsis model={model} labels={labels} palette={palette} />}
        {!ratingInScoreRow && model.viewerRating?.editable ? <View style={[styles.contentSection, styles.viewerRating, { backgroundColor: palette.surface, borderColor: palette.border }]}>
          <Text accessibilityRole="header" style={[styles.contentTitle, { color: palette.text }]}>Your rating</Text>
          <RatingStars scaleMax={model.viewerRating.scaleMax || 10} value={model.viewerRating.value}
            label="Your rating" palette={{ lit: '#facc15', unlit: palette.surfaceStrong, muted: palette.textMuted, focusStyle: {} }}
            renderStar={lit => <Text style={{ color: lit ? '#facc15' : palette.surfaceStrong, fontSize: 22 }}>★</Text>}
            onSelect={onRateMain} />
        </View> : null}
      </> : null}
      {model.secondary ? <>
        {noticeSlot}
        <DetailSecondary model={model.secondary} sections={secondarySections} palette={palette}
          onOpenLink={onOpenMetadata || onOpenExternal} promote={Boolean(model.artwork?.backdrop || model.artwork?.gallery?.photos?.length)} />
      </> : <>
      {hasSections ? sections.map(section => {
        const body = sectionBodies[section.id] || section.body;
        if (!body && !section.copy) return null;
        return <DetailSection key={section.id || section.title}
          section={{ ...section, body }} palette={palette} />;
      }) : null}
      {sectionsSlot || null}
      {childrenSlot || null}
      {model.children ? <DetailChildren
        model={model.children}
        labels={model.childLabels || labels}
        palette={palette}
        variant="detail"
        onOpenSeason={season => onOpenItem?.(season.identity)}
        onOpenChild={item => onOpenItem?.(item.identity)}
        onAction={(key, item) => onChildAction?.(key, item)}
        onRate={(item, score) => onRateChild?.(item, score)}
        onLoadMore={model.children.nextPage ? onLoadMore : undefined}
        loadMoreLabel={model.children.nextLabel}
      /> : null}
      {(secondarySections.cast || secondarySections.crew || model.relatedSections?.length || model.steamDlcs?.length) ? <View style={styles.relatedRows}>
      {secondarySections.cast}
      {secondarySections.crew}
      {(shelfCardWidth ? related.length || model.steamDlcs?.length : model.relatedSections?.length) ? <DetailRelated
        model={{ sections: shelfCardWidth ? related : model.relatedSections, steamDlcs: model.steamDlcs || [] }}
        labels={model.relatedLabels || labels}
        palette={palette.mediaCard || palette}
        onOpen={onOpenItem}
        onOpenLink={onOpenExternal}
        onOpenExternal={onOpenExternal}
        onRate={onRate}
        web={false}
      /> : null}
      {shelfCardWidth ? secondarySections.recommendations : null}
      </View> : null}
      </>}
    </> : null}
    {children || null}
  </View>;
}

const styles = StyleSheet.create({
  root: { gap: 18, minWidth: 0 },
  relatedRows: { gap: 12 },
  notice: { gap: 8, borderWidth: 1, borderRadius: 8, padding: 12, alignItems: 'flex-start' },
  noticeText: { fontSize: 13, lineHeight: 18 },
  loading: { alignItems: 'center', justifyContent: 'center', gap: 10, paddingVertical: 48 },
  loadingText: { fontSize: 13 },
  contentSection: { gap: 12, width: '100%' },
  viewerRating: { borderWidth: 1, borderRadius: 10, padding: 12, maxWidth: 360 },
  contentTitle: { fontSize: 20, lineHeight: 26, fontWeight: '700' },
  peopleGrid: { gap: 10 },
  personCard: { width: 104, borderWidth: 1, borderRadius: 8, overflow: 'hidden', paddingBottom: 8 },
  personImage: { width: '100%', aspectRatio: 2 / 3 },
  personPlaceholder: { alignItems: 'center', justifyContent: 'center' },
  personName: { paddingHorizontal: 7, paddingTop: 7, fontSize: 12, fontWeight: '600' },
  personRole: { paddingHorizontal: 7, paddingTop: 2, fontSize: 10, lineHeight: 14 },
  linkGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  linkChip: { minHeight: 36, borderWidth: 1, borderRadius: 18, flexDirection: 'row', alignItems: 'center', gap: 6, paddingHorizontal: 12 },
  linkLogo: { width: 16, height: 16 },
});
