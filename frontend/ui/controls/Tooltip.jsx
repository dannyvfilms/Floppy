import { Modal, ModalCloseButton } from '../Modal';
import React, { useEffect, useRef, useState } from 'react';
import { Pressable, StyleSheet, Text, useWindowDimensions, View } from 'react-native';

// Legacy visual intent: a small muted info trigger and a compact help bubble.
const FALLBACK_PALETTE = {
  triggerBackground: 'transparent',
  triggerHoverBackground: 'rgba(161, 161, 170, 0.16)',
  triggerBorder: 'transparent',
  triggerText: '#a1a1aa',
  triggerSize: 20,
  bubbleBackground: '#3f3f46',
  bubbleBorder: '#3f3f46',
  bubbleText: '#fafafa',
  bubbleWidth: 240,
  bubbleRadius: 8,
  closeText: '#a1a1aa',
  fontSize: 12,
  overlay: 'transparent',
  focusStyle: {},
};

const PLACEMENTS = new Set(['top', 'bottom', 'left', 'right']);
const VIEWPORT_MARGIN = 8;
const ANCHOR_GAP = 8;

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

/**
 * Accessible help trigger with a native popover bubble.
 *
 * The legacy contract is `Tooltip({ label, text })`. Callers may also control
 * visibility with `open`/`onOpenChange`, choose a `placement`, supply a palette,
 * or replace the trigger glyph with `trigger`/`children`.
 */
export function Tooltip({
  label,
  text,
  open,
  onOpenChange,
  placement = 'top',
  palette,
  trigger,
  children,
  closeLabel = 'Close',
}) {
  const viewport = useWindowDimensions();
  const [internalOpen, setInternalOpen] = useState(false);
  const [anchor, setAnchor] = useState(null);
  const [bubbleHeight, setBubbleHeight] = useState(0);
  const triggerRef = useRef(null);
  const isControlled = open !== undefined;
  const visible = isControlled ? Boolean(open) : internalOpen;
  const colors = { ...FALLBACK_PALETTE, ...(palette || {}) };
  const fontSize = colors.fontSize ?? 12;
  const side = PLACEMENTS.has(placement) ? placement : 'top';
  const content = text ?? label ?? '';
  const customTrigger = trigger ?? children;

  function changeOpen(next) {
    if (!isControlled) {
      setInternalOpen(next);
    }
    onOpenChange?.(next);
  }

  function close() {
    changeOpen(false);
  }

  function measureTrigger() {
    const node = triggerRef.current;
    if (!node || typeof node.measureInWindow !== 'function') {
      return;
    }
    node.measureInWindow((x, y, width, height) => {
      setAnchor({ x, y, width, height });
    });
  }

  useEffect(() => {
    if (visible) {
      measureTrigger();
    } else {
      setAnchor(null);
      setBubbleHeight(0);
    }
  }, [visible]);

  const bubbleWidth = Math.min(
    colors.bubbleWidth ?? 240,
    Math.max(0, viewport.width - VIEWPORT_MARGIN * 2),
  );
  const height = bubbleHeight || 48;
  let left;
  let top;

  if (anchor) {
    if (side === 'left' || side === 'right') {
      top = anchor.y + anchor.height / 2 - height / 2;
      left = side === 'left'
        ? anchor.x - bubbleWidth - ANCHOR_GAP
        : anchor.x + anchor.width + ANCHOR_GAP;
      if (side === 'left' && left < VIEWPORT_MARGIN) {
        left = anchor.x + anchor.width + ANCHOR_GAP;
      }
      if (side === 'right' && left + bubbleWidth > viewport.width - VIEWPORT_MARGIN) {
        left = anchor.x - bubbleWidth - ANCHOR_GAP;
      }
    } else {
      left = anchor.x + anchor.width / 2 - bubbleWidth / 2;
      top = side === 'bottom'
        ? anchor.y + anchor.height + ANCHOR_GAP
        : anchor.y - height - ANCHOR_GAP;
      if (side === 'top' && top < VIEWPORT_MARGIN) {
        top = anchor.y + anchor.height + ANCHOR_GAP;
      }
      if (side === 'bottom' && top + height > viewport.height - VIEWPORT_MARGIN) {
        top = anchor.y - height - ANCHOR_GAP;
      }
    }
  } else {
    left = (viewport.width - bubbleWidth) / 2;
    top = (viewport.height - height) / 2;
  }

  left = clamp(left, VIEWPORT_MARGIN, Math.max(VIEWPORT_MARGIN, viewport.width - bubbleWidth - VIEWPORT_MARGIN));
  top = clamp(top, VIEWPORT_MARGIN, Math.max(VIEWPORT_MARGIN, viewport.height - height - VIEWPORT_MARGIN));

  const renderedTrigger = typeof customTrigger === 'function'
    ? customTrigger({ open: visible, onOpenChange: changeOpen, toggle: () => changeOpen(!visible) })
    : customTrigger;
  const triggerContent = customTrigger
    ? typeof renderedTrigger === 'string'
      ? <Text style={{ color: colors.triggerText }}>{renderedTrigger}</Text>
      : renderedTrigger
    : <View accessible={false} importantForAccessibility="no-hide-descendants"
      style={[styles.glyph, {
        width: colors.triggerSize,
        height: colors.triggerSize,
        borderRadius: colors.triggerSize / 2,
        borderColor: colors.triggerBorder,
      }]}>
      <Text style={[styles.glyphText, { color: colors.triggerText, fontSize }]}>i</Text>
    </View>;

  return <View style={styles.root}>
    <Pressable
      ref={triggerRef}
      accessibilityRole="button"
      accessibilityLabel={label || (typeof content === 'string' ? content : undefined)}
      accessibilityState={{ expanded: visible }}
      hitSlop={6}
      onPress={() => changeOpen(!visible)}
      style={({ pressed, hovered, focused }) => [styles.trigger, {
        width: customTrigger ? undefined : colors.triggerSize,
        height: customTrigger ? undefined : colors.triggerSize,
        borderRadius: colors.triggerSize / 2,
        backgroundColor: pressed || hovered ? colors.triggerHoverBackground : colors.triggerBackground,
      }, focused && colors.focusStyle]}>
      {triggerContent}
    </Pressable>
    <Modal visible={visible} transparent animationType="fade" onRequestClose={close}>
      <View style={styles.overlay} pointerEvents="box-none" accessibilityViewIsModal>
        <Pressable accessible={false} style={[StyleSheet.absoluteFill, { backgroundColor: colors.overlay }]}
          onPress={close} />
        <View
          onLayout={event => {
            const next = event.nativeEvent.layout.height;
            if (Math.abs(next - bubbleHeight) > 0.5) {
              setBubbleHeight(next);
            }
          }}
          style={[styles.bubble, {
            left,
            top,
            width: bubbleWidth,
            backgroundColor: colors.bubbleBackground,
            borderColor: colors.bubbleBorder,
            borderRadius: colors.bubbleRadius,
          }]}>
          <Text accessibilityLiveRegion="polite" style={[styles.bubbleText, {
            color: colors.bubbleText,
            fontSize,
            lineHeight: fontSize * 1.3,
          }]}>{content}</Text>
          <ModalCloseButton accessibilityRole="button" accessibilityLabel={closeLabel}
            hitSlop={6} onPress={close} style={styles.close}>
            <Text style={[styles.closeText, { color: colors.closeText }]}>×</Text>
          </ModalCloseButton>
        </View>
      </View>
    </Modal>
  </View>;
}

const styles = StyleSheet.create({
  root: { alignSelf: 'flex-start' },
  trigger: { alignItems: 'center', justifyContent: 'center' },
  glyph: { alignItems: 'center', justifyContent: 'center', borderWidth: 1 },
  glyphText: { fontWeight: '700' },
  overlay: { flex: 1 },
  bubble: {
    position: 'absolute',
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: 8,
    borderWidth: 1,
    padding: 12,
  },
  bubbleText: { flexShrink: 1 },
  close: { alignItems: 'center', justifyContent: 'center', width: 18, height: 18 },
  closeText: { fontSize: 16, fontWeight: '600', lineHeight: 18 },
});
