import React from 'react';
import { ActivityIndicator, StyleSheet, Text, View } from 'react-native';
import { Button } from '../ui/Button';
import {
  DetailActions,
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
    {error ? <View style={[styles.notice, { borderColor: palette.danger || '#ef4444' }]}>
      <Text accessibilityLiveRegion="polite" style={[styles.noticeText, { color: palette.danger || '#ef4444' }]}>{error || copy.error}</Text>
      {onRetry ? <Button label={copy.retry} tone="surface" palette={palette} onPress={onRetry} /> : null}
    </View> : null}
    {loading ? <View accessibilityLiveRegion="polite" style={styles.loading}>
      <ActivityIndicator color={palette.accent || '#6366f1'} />
      <Text style={[styles.loadingText, { color: palette.textMuted || '#a1a1aa' }]}>{copy.loading}</Text>
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
  notice: { gap: 8, borderWidth: 1, borderRadius: 8, padding: 12, alignItems: 'flex-start' },
  noticeText: { fontSize: 13, lineHeight: 18 },
  loading: { alignItems: 'center', justifyContent: 'center', gap: 10, paddingVertical: 48 },
  loadingText: { fontSize: 13 },
});
