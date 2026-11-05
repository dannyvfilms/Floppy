import React from 'react';
import { Modal, ScrollView, StyleSheet, Text, View } from 'react-native';
import { Button } from './Button';
import { FormError, FormStatus } from './MediaCardFormControls';
import { MediaCardView } from './MediaCardView';

const DEFAULT_PALETTE = {
  background: '#18181b',
  text: '#fafafa',
  textSecondary: '#d4d4d8',
  textMuted: '#a1a1aa',
  surface: '#27272a',
  surfaceStrong: '#3f3f46',
  surfaceMuted: '#52525b',
  border: '#3f3f46',
  accent: '#6366f1',
  accentStrong: '#4f46e5',
  accentText: '#ffffff',
  danger: '#ef4444',
  success: '#10b981',
  card: '#27272a',
  link: '#818cf8',
  star: '#facc15',
  placeholder: '#3f3f46',
  focusStyle: {},
};

const DEFAULT_LABELS = {
  title: 'Recommendations',
  subtitle: 'Review and manage item recommendations for this list.',
  close: 'Close recommendations',
  from: 'From',
  ago: 'ago',
  approve: 'Approve and add',
  deny: 'Deny',
  view: 'View details',
  emptyTitle: 'No recommendations yet',
  emptyBody: 'When someone recommends an item for this list, it will appear here.',
  loading: 'Loading recommendations…',
  error: 'Recommendations could not load. Please try again in a moment.',
  permission: 'You do not have permission to manage recommendations for this list.',
  note: 'Note',
};

function mergePalette(palette) {
  return { ...DEFAULT_PALETTE, ...(palette || {}) };
}

function mergeLabels(labels) {
  return { ...DEFAULT_LABELS, ...(labels || {}) };
}

export function ListRecommendations({
  listName = '',
  recommendations = [],
  canEdit = true,
  status = 'ready',
  error,
  labels: suppliedLabels,
  palette,
  onClose,
  onApprove,
  onDeny,
  onView,
}) {
  const colors = mergePalette(palette);
  const copy = mergeLabels(suppliedLabels);

  return <Modal visible transparent animationType="fade" onRequestClose={onClose}>
    <View style={[styles.overlay, { backgroundColor: colors.background }]}>
      <View style={styles.screen}>
        <View style={styles.header}>
          <View style={styles.headingCopy}>
            <Text role="heading" aria-level={1} style={[styles.title, { color: colors.text }]}>{copy.title}</Text>
            <Text style={[styles.subtitle, { color: colors.textMuted }]}>{listName}</Text>
            <Text style={[styles.subtitle, { color: colors.textMuted }]}>{copy.subtitle}</Text>
          </View>
          <Button label={copy.close} tone="surface" onPress={onClose} palette={colors} />
        </View>
        <ScrollView contentContainerStyle={styles.body}>
          {!canEdit ? <FormError message={copy.permission} palette={colors} /> : null}
          {status === 'loading' ? <FormStatus message={copy.loading} tone="loading" palette={colors} /> : null}
          {status === 'error' ? <FormError message={error || copy.error} palette={colors} /> : null}
          {canEdit && status === 'ready' && recommendations.length === 0 ? <View style={styles.empty}>
            <Text style={[styles.emptyTitle, { color: colors.text }]}>{copy.emptyTitle}</Text>
            <Text style={[styles.emptyBody, { color: colors.textMuted }]}>{copy.emptyBody}</Text>
          </View> : null}
          {canEdit && status === 'ready' ? recommendations.map(rec => <View key={rec.id}
            style={[styles.card, { backgroundColor: colors.surface }]}>
            <View style={styles.cardTop}>
              <Text style={[styles.meta, { color: colors.textMuted }]}>
                {copy.from} <Text style={{ color: colors.textSecondary }}>{rec.recommender}</Text>
              </Text>
              <Text style={[styles.meta, { color: colors.textMuted }]}>{rec.dateLabel} {copy.ago}</Text>
            </View>
            <View style={styles.cardBody}>
              <View style={styles.cardMedia}>
                <MediaCardView model={rec.media} width={112} palette={colors} onOpen={() => onView?.(rec)} />
              </View>
              <View style={styles.cardActions}>
                <Button label={copy.approve} tone="primary" onPress={() => onApprove?.(rec)} palette={colors} />
                <Button label={copy.deny} tone="danger-solid" onPress={() => onDeny?.(rec)} palette={colors} />
                <Button label={copy.view} tone="surface" onPress={() => onView?.(rec)} palette={colors} />
              </View>
            </View>
            {rec.note ? <View style={[styles.note, { backgroundColor: colors.surfaceStrong }]}>
              <Text style={[styles.meta, { color: colors.textMuted }]}>{copy.note}</Text>
              <Text style={[styles.noteText, { color: colors.textSecondary }]}>"{rec.note}"</Text>
            </View> : null}
          </View>) : null}
        </ScrollView>
      </View>
    </View>
  </Modal>;
}

const styles = StyleSheet.create({
  overlay: { flex: 1 },
  screen: { flex: 1, paddingTop: 12 },
  header: { flexDirection: 'row', alignItems: 'flex-start', justifyContent: 'space-between', gap: 12, paddingHorizontal: 16, paddingBottom: 8 },
  headingCopy: { flex: 1, minWidth: 0, gap: 2 },
  title: { fontSize: 24, fontWeight: '700' },
  subtitle: { fontSize: 12, lineHeight: 17 },
  body: { paddingHorizontal: 16, paddingBottom: 32, gap: 12 },
  card: { borderRadius: 8, padding: 12, gap: 10 },
  cardTop: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', justifyContent: 'space-between', gap: 6 },
  meta: { fontSize: 12, lineHeight: 17 },
  cardBody: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'flex-start', gap: 12 },
  cardMedia: { flexDirection: 'row' },
  cardActions: { flex: 1, minWidth: 140, gap: 8 },
  note: { borderRadius: 8, padding: 10, gap: 2 },
  noteText: { fontSize: 13, fontStyle: 'italic', lineHeight: 18 },
  empty: { alignItems: 'center', gap: 6, paddingVertical: 40 },
  emptyTitle: { fontSize: 17, fontWeight: '600' },
  emptyBody: { fontSize: 13, lineHeight: 18, textAlign: 'center' },
});
