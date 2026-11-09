import { Modal, ModalCloseButton } from '../Modal';
import React, { useEffect, useRef } from 'react';
import {
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
  useWindowDimensions,
} from 'react-native';

// The legacy small dialog: a centred card on a 50% black backdrop, 32rem wide,
// 1.25rem of padding, an 18px title beside a secondary close button, and 1rem
// between body blocks. These fallbacks mirror the semantic colour tokens used by
// the web controls so the same card reads correctly on a bare native surface.
const fallbackPalette = {
  surface: '#27272a',
  surfaceStrong: '#3f3f46',
  surfaceBorder: '#3f3f46',
  surfaceHover: '#52525b',
  border: '#3f3f46',
  text: '#fafafa',
  textMuted: '#a1a1aa',
  link: '#818cf8',
  backdrop: 'rgba(0, 0, 0, 0.5)',
  radius: 8,
  focusStyle: {},
};

/**
 * Universal modal dialog.
 *
 * Presentation only: the caller owns the form, loading state and submit
 * handlers. `actions` is an optional footer slot (usually shared Button
 * elements); when it is an array each entry is rendered in the same row.
 *
 * Platform behaviour: `onRequestClose` covers Escape on web and the Android
 * back button on native. React Native Web's Modal already traps focus and
 * restores it to the element that opened the dialog on unmount; native focus
 * return is owned by the platform. Focusing the close button on open is the
 * same best-effort initial focus the legacy dialog requested with autoFocus.
 */
export function Dialog({
  open,
  title,
  closeLabel = 'Close',
  onClose,
  children,
  palette,
  actions,
}) {
  const closeRef = useRef(null);
  const { height } = useWindowDimensions();
  const colors = { ...fallbackPalette, ...palette };
  const background = colors.surfaceStrong || colors.surface;
  const borderColor = colors.surfaceBorder || colors.border;
  const backdrop = palette?.overlay || palette?.backdrop || fallbackPalette.backdrop;
  const radius = colors.radius ?? fallbackPalette.radius;

  useEffect(() => {
    if (!open) return;
    // Optional call: native host refs are not focusable.
    closeRef.current?.focus?.();
  }, [open]);

  const close = () => onClose?.();

  return <Modal
    visible={Boolean(open)}
    transparent
    animationType="fade"
    accessibilityViewIsModal
    onRequestClose={close}>
    <View style={styles.root}>
      <Pressable
        accessible={false}
        accessibilityElementsHidden
        importantForAccessibility="no-hide-descendants"
        onPress={close}
        style={[StyleSheet.absoluteFill, { backgroundColor: backdrop }]} />
      <View
        accessibilityViewIsModal
        role="dialog"
        accessibilityLabel={title}
        style={[
          styles.dialog,
          {
            maxHeight: Math.max(240, height - 32),
            backgroundColor: background,
            borderColor,
            borderRadius: radius,
          },
        ]}>
        <View style={styles.header}>
          <Text accessibilityRole="header" style={[styles.title, { color: colors.text }]}>{title}</Text>
          <ModalCloseButton
            ref={closeRef}
            accessibilityRole="button"
            accessibilityLabel={closeLabel}
            onPress={close}
            style={({ pressed, hovered, focused }) => [
              styles.close,
              {
                backgroundColor: pressed || hovered ? colors.surfaceHover : colors.surface,
                borderColor,
                borderRadius: Math.max(0, radius - 2),
              },
              focused && colors.focusStyle,
            ]}>
            <Text style={[styles.closeText, { color: colors.link || colors.text }]}>×</Text>
          </ModalCloseButton>
        </View>
        {children ? <ScrollView
          style={styles.bodyWrap}
          contentContainerStyle={styles.body}>
          {children}
        </ScrollView> : null}
        {actions ? <View style={styles.actions}>{actions}</View> : null}
      </View>
    </View>
  </Modal>;
}

const styles = StyleSheet.create({
  root: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 16 },
  dialog: {
    width: '100%',
    maxWidth: 512,
    padding: 20,
    borderWidth: 1,
    overflow: 'hidden',
  },
  header: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    alignItems: 'center',
    gap: 12,
  },
  title: { flex: 1, minWidth: 0, fontSize: 18, fontWeight: '600' },
  close: {
    alignItems: 'center',
    justifyContent: 'center',
    minWidth: 34,
    paddingHorizontal: 16,
    paddingVertical: 8,
    borderWidth: 1,
  },
  closeText: { fontSize: 14, lineHeight: 20 },
  bodyWrap: { flexShrink: 1, marginTop: 16 },
  body: { gap: 16 },
  actions: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    justifyContent: 'flex-end',
    gap: 8,
    marginTop: 16,
  },
});
