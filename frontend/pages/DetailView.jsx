import React from 'react';
import { ActivityIndicator, Image, Pressable, ScrollView, StyleSheet, Text, useWindowDimensions, View } from 'react-native';
import { Button } from '../ui/Button';
import { DetailChildren } from '../ui/DetailChildren';
import { DetailRelated } from '../ui/DetailRelated';
import { RatingStars } from '../ui/RatingStars';
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

function PeopleSection({ title, people = [], palette, onOpen }) {
  if (!people.length) return null;
  return <View style={styles.contentSection}>
    <Text accessibilityRole="header" style={[styles.contentTitle, { color: palette.text }]}>{title}</Text>
    <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.peopleGrid} accessibilityLabel={title}>
      {people.map((person, index) => {
        const card = <>
          {person.image ? <Image source={{ uri: person.image }} resizeMode="cover" style={styles.personImage}
            accessibilityLabel={person.name} /> : <View style={[styles.personImage, styles.personPlaceholder, { backgroundColor: palette.surfaceStrong }]} />}
          <Text numberOfLines={2} style={[styles.personName, { color: palette.text }]}>{person.name}</Text>
          {person.role ? <Text numberOfLines={2} style={[styles.personRole, { color: palette.textMuted }]}>{person.role}</Text> : null}
        </>;
        const cardStyle = [styles.personCard, { backgroundColor: palette.surface, borderColor: palette.border }];
        // The web cast and crew cards link to the person page.
        return onOpen && person.person_id != null
          ? <Pressable key={`${person.name}-${index}`} accessibilityRole="link" accessibilityLabel={person.name}
            onPress={() => onOpen(person)} style={cardStyle}>{card}</Pressable>
          : <View key={`${person.name}-${index}`} style={cardStyle}>{card}</View>;
      })}
    </ScrollView>
  </View>;
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
  onOpenPerson,
  children,
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
  const immersive = width < 768 && Boolean(model?.artwork?.backdrop);

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
        {immersive ? <DetailMobileHero model={model} palette={palette} onOpenItem={onOpenItem} actions={actionsSlot} /> : <>
          <DetailHero model={model} palette={palette} onOpenVideo={onOpenVideo} />
          <DetailHeader model={model} labels={labels} palette={palette} showArtwork={showArtwork} />
          {actionsSlot || <DetailActions model={model} labels={labels} palette={palette} />}
        </>}
        {scoreSlot || null}
        <DetailChips chips={model.scoreChips || []} palette={palette} onOpen={onOpenExternal} />
        <DetailLinks groups={model.linkSections} palette={palette} onOpen={onOpenExternal} />
        {renderSynopsis
          ? renderSynopsis({ model, labels, palette })
          : <DetailSynopsis model={model} labels={labels} palette={palette} />}
        {model.viewerRating?.editable ? <View style={[styles.contentSection, styles.viewerRating, { backgroundColor: palette.surface, borderColor: palette.border }]}>
          <Text accessibilityRole="header" style={[styles.contentTitle, { color: palette.text }]}>Your rating</Text>
          <RatingStars scaleMax={model.viewerRating.scaleMax || 10} value={model.viewerRating.value}
            label="Your rating" palette={{ lit: '#facc15', unlit: palette.surfaceStrong, muted: palette.textMuted, focusStyle: {} }}
            renderStar={lit => <Text style={{ color: lit ? '#facc15' : palette.surfaceStrong, fontSize: 22 }}>★</Text>}
            onSelect={onRateMain} />
        </View> : null}
      </> : null}
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
      {model.people?.cast?.length ? <PeopleSection title="Cast" people={model.people.cast} palette={palette} onOpen={onOpenPerson} /> : null}
      {model.people?.crew?.length ? <PeopleSection title="Crew" people={model.people.crew} palette={palette} onOpen={onOpenPerson} /> : null}
      {model.relatedSections?.length ? <DetailRelated
        model={{ sections: model.relatedSections, steamDlcs: model.steamDlcs || [] }}
        labels={model.relatedLabels || labels}
        palette={palette.mediaCard || palette}
        onOpen={onOpenItem}
        onOpenLink={onOpenExternal}
        onOpenExternal={onOpenExternal}
        onRate={onRate}
        web={false}
      /> : null}
    </> : null}
    {children || null}
  </View>;
}

const styles = StyleSheet.create({
  root: { gap: 18, minWidth: 0 },
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
