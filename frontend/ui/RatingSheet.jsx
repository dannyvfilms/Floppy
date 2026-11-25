import React from 'react';
import { Pressable, ScrollView, StyleSheet, Text, View, useWindowDimensions } from 'react-native';
import { Modal, ModalCloseButton } from './Modal';
import { Icon } from './Icon';
import { actionIcons } from './actionIcons';
import { Button } from './Button';
import { Title } from './Title';

// The frame both rating sheets share (the scale editor and the criteria scoring sheet): a centered card on
// desktop web, a full-height presentation sheet on phones and native. Header with a close button, a scrolling
// body of grouped lists, and the Cancel / primary footer the Collection modal uses.
const MOBILE_MAX_WIDTH = 640;

export function RatingSheet({
  open, title, subtitle, onClose, children, footer, palette, closeLabel = 'Close',
  primaryLabel, onPrimary, primaryBusy = false, primaryDisabled = false, cancelLabel = 'Cancel', danger,
}) {
  const { width, height } = useWindowDimensions();
  const mobile = width < MOBILE_MAX_WIDTH;
  const card = mobile
    ? { width: '100%', height: '94%', borderTopLeftRadius: 16, borderTopRightRadius: 16 }
    : { width: Math.min(560, width - 32), maxHeight: Math.min(760, height - 48), borderRadius: 14 };
  return <Modal visible={open} transparent animationType={mobile ? 'slide' : 'fade'} onRequestClose={onClose}>
    <View style={[styles.root, { justifyContent: mobile ? 'flex-end' : 'center' }]}>
      <Pressable accessible={false} style={StyleSheet.absoluteFill} onPress={onClose}>
        <View style={[StyleSheet.absoluteFill, { backgroundColor: 'rgba(9, 9, 11, 0.72)' }]} />
      </Pressable>
      <View accessibilityViewIsModal role="dialog" aria-modal accessibilityLabel={title}
        style={[styles.card, card, { backgroundColor: palette.surfaceDim || palette.background || palette.surface, borderColor: palette.border }]}>
        <View style={[styles.bar, { borderColor: palette.border }]}>
          <View style={styles.barText}>
            <Title size="bar" numberOfLines={2} color={palette.text}>{title}</Title>
            {subtitle ? <Text style={[styles.subtitle, { color: palette.textMuted }]}>{subtitle}</Text> : null}
          </View>
          <ModalCloseButton accessibilityRole="button" accessibilityLabel={closeLabel} onPress={onClose} style={styles.close}>
            <Icon spec={actionIcons.x} color={palette.textMuted} size={20} />
          </ModalCloseButton>
        </View>
        <ScrollView style={styles.scroll} contentContainerStyle={styles.body} keyboardShouldPersistTaps="handled">
          {children}
          {danger}
        </ScrollView>
        {footer || (onPrimary ? <View style={[styles.footer, { borderColor: palette.border }, mobile && { paddingBottom: 30 }]}>
          <View style={styles.footerButton}>
            <Button label={cancelLabel} tone="ghost" size="lg" width="full" onPress={onClose}
              palette={{ ...palette, ghost: { background: 'transparent', pressed: palette.surfaceStrong,
                hovered: palette.surfaceStrong, text: palette.textSecondary, border: palette.border } }} />
          </View>
          <View style={styles.footerButton}>
            <Button label={primaryLabel} size="lg" width="full" palette={palette} busy={primaryBusy}
              disabled={primaryBusy || primaryDisabled} onPress={onPrimary} />
          </View>
        </View> : null)}
      </View>
    </View>
  </Modal>;
}

const styles = StyleSheet.create({
  root: { flex: 1, alignItems: 'center' },
  card: { borderWidth: StyleSheet.hairlineWidth, overflow: 'hidden' },
  bar: { flexDirection: 'row', alignItems: 'flex-start', gap: 12, paddingHorizontal: 16, paddingVertical: 14,
    borderBottomWidth: StyleSheet.hairlineWidth },
  barText: { flex: 1, gap: 2 },
  subtitle: { fontSize: 13, lineHeight: 18 },
  close: { padding: 4 },
  scroll: { flexShrink: 1 },
  body: { padding: 16, gap: 16 },
  footer: { flexDirection: 'row', gap: 12, padding: 16, borderTopWidth: StyleSheet.hairlineWidth },
  footerButton: { flex: 1 },
});
