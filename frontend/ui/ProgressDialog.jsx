import React from 'react';
import { Modal, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { progressFallbackPalette } from './ProgressBar';
import { ProgressBreakdown } from './ProgressBreakdown';

const defaultLabels = {
  cancelRewatch: 'Cancel rewatch',
  cancelling: 'Cancelling…',
  close: 'Close',
};

/**
 * The detail progress dialog: card-title header, cancel-rewatch action, close
 * and the shared season/episode breakdown.
 *
 * Presentation only: the caller owns loading, cancellation and navigation.
 */
export function ProgressDialog({
  visible = true,
  title,
  model,
  labels,
  palette,
  status = 'ready',
  cancelling = false,
  onClose,
  onCancelRewatch,
  onOpenSeason,
  onOpenEpisode,
}) {
  const colors = { ...progressFallbackPalette, ...palette };
  const text = { ...defaultLabels, ...labels };
  const canCancel = Boolean(model?.runKey && onCancelRewatch);
  return <Modal visible={visible} transparent animationType="fade" onRequestClose={() => onClose?.()}>
    <View style={styles.root}>
      <Pressable accessible={false}
        style={[StyleSheet.absoluteFill, styles.backdrop]}
        onPress={() => onClose?.()} />
      <View accessibilityViewIsModal
        style={[styles.dialog, {
          borderColor: colors.surfaceBorder,
          backgroundColor: colors.background || colors.surface,
        }]}>
        <View style={[styles.header, { borderBottomColor: colors.surfaceBorder }]}>
          <Text numberOfLines={1} style={[styles.title, { color: colors.text }]}>{title}</Text>
          <View style={styles.actions}>
            <Pressable accessibilityRole="button"
              accessibilityLabel={text.close}
              onPress={() => onClose?.()}
              style={({ focused }) => [styles.close, focused && colors.focusStyle]}>
              <Text style={[styles.closeText, { color: colors.textMuted }]}>×</Text>
            </Pressable>
            {canCancel
              ? <Pressable accessibilityRole="button"
                accessibilityState={{ busy: cancelling, disabled: cancelling }}
                disabled={cancelling}
                onPress={() => onCancelRewatch()}
                style={({ focused }) => [styles.cancel, focused && colors.focusStyle]}>
                <Text style={[styles.cancelText, { color: cancelling ? colors.textMuted : colors.textSecondary }]}>
                  {cancelling ? text.cancelling : text.cancelRewatch}
                </Text>
              </Pressable>
              : null}
          </View>
        </View>
        <ScrollView style={styles.bodyWrap} contentContainerStyle={styles.body}>
          <ProgressBreakdown model={model}
            labels={labels}
            palette={colors}
            status={status}
            cancelling={cancelling}
            onOpenSeason={onOpenSeason}
            onOpenEpisode={onOpenEpisode} />
        </ScrollView>
      </View>
    </View>
  </Modal>;
}

const styles = StyleSheet.create({
  root: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 16 },
  backdrop: { backgroundColor: 'rgba(0, 0, 0, 0.5)' },
  dialog: { width: '100%', maxWidth: 672, maxHeight: '90%', overflow: 'hidden', borderWidth: 1, borderRadius: 16 },
  header: { flexDirection: 'row', alignItems: 'center', gap: 12, borderBottomWidth: 1, paddingHorizontal: 16, paddingVertical: 12 },
  title: { flex: 1, fontSize: 16, fontWeight: '600' },
  actions: { flexDirection: 'row-reverse', alignItems: 'center', gap: 12 },
  cancel: { paddingVertical: 4 },
  cancelText: { fontSize: 12, textDecorationLine: 'underline' },
  close: { alignItems: 'center', justifyContent: 'center', width: 32, height: 32, borderRadius: 16 },
  closeText: { fontSize: 22, lineHeight: 24 },
  bodyWrap: { flexShrink: 1 },
  body: { paddingHorizontal: 16, paddingVertical: 12 },
});
