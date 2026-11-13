import React, { useContext, useRef, useState } from 'react';
import { Animated, Pressable, StyleSheet, Text, TextInput, View, useWindowDimensions } from 'react-native';
import { Modal } from './Modal';
import { DROPDOWN, dropdownPlacement } from './dropdownMetrics';
import { KeyboardOverlapContext } from './keyboardOverlapContext';

// Anchor coordinates are in the window, while a sheet's modal host is local to
// the sheet. Measure the host so the same menu positions correctly in both.
export function DropdownMenu({ open, onClose, children, palette, closeLabel, anchor,
  estimatedHeight = 112, layerProps }) {
  return <Modal transparent visible={open} animationType={anchor ? 'none' : 'fade'} onRequestClose={onClose}>
    <DropdownMenuContent {...{ onClose, children, palette, closeLabel, anchor, estimatedHeight, layerProps }} />
  </Modal>;
}

// Keep keyboard-driven layout inside the modal host: Duo registers modal children in a separate
// commit, which would otherwise consume the keyboard's LayoutAnimation before the menu resizes.
function DropdownMenuContent({ onClose, children, palette, closeLabel, anchor, estimatedHeight, layerProps }) {
  const viewport = useWindowDimensions();
  const host = useRef(null);
  const [bounds, setBounds] = useState(null);
  const dropdown = Boolean(anchor);
  const useKeyboardOverlap = useContext(KeyboardOverlapContext);
  const keyboard = useKeyboardOverlap(true);
  const width = bounds?.width || viewport.width;
  const fullHeight = bounds?.height || viewport.height;
  // Placement ignores the keyboard, so opening it never moves the menu: the top stays where it was and only
  // the bottom comes up, the menu getting shorter and scrolling (the Search suggestions fit the same way).
  const placement = anchor ? dropdownPlacement(anchor, { ...(bounds || { x: 0, y: 0 }), width, height: fullHeight }, estimatedHeight) : null;
  const baseRoom = placement?.top != null ? fullHeight - placement.top - 8
    : placement?.bottom != null ? fullHeight - placement.bottom - 8 : fullHeight - 16;
  const overlap = placement?.bottom != null ? 0 : keyboard;
  const room = typeof overlap === 'number' ? Math.max(80, baseRoom - overlap)
    : overlap.interpolate({ inputRange: [0, Math.max(1, baseRoom - 80)], outputRange: [Math.max(80, baseRoom), 80], extrapolate: 'clamp' });
  const paddingBottom = typeof keyboard === 'number' ? 24 + keyboard : Animated.add(24, keyboard);
  return <Animated.View ref={host} {...layerProps} style={dropdown ? StyleSheet.absoluteFill : [styles.modalRoot, { paddingBottom }]}
      onLayout={() => host.current?.measureInWindow?.((hostX, hostY, hostWidth, hostHeight) => {
        setBounds(current => current?.x === hostX && current?.y === hostY && current?.width === hostWidth && current?.height === hostHeight
          ? current : { x: hostX, y: hostY, width: hostWidth, height: hostHeight });
      })}>
      <Pressable accessibilityRole="button" accessibilityLabel={closeLabel} onPress={onClose}
        style={[StyleSheet.absoluteFill, dropdown ? null : { backgroundColor: palette.overlay }]} />
      <Animated.View accessibilityViewIsModal style={[styles.menu, dropdown && [styles.popover, placement], {
        maxHeight: room, backgroundColor: dropdown ? palette.surface : palette.surfaceStrong,
        borderColor: palette.border,
      }]}>{children}</Animated.View>
    </Animated.View>;
}

// One row of an app dropdown: the sidebar options, the Search media type and the library settings menu all
// draw it, so their size, spacing, colours and hover match. The row owns its colours (text, muted detail and
// the surface-muted hover/selected background) and reads them from the caller's palette; a caller only adds
// `danger` for a destructive row. `icon` is an already-rendered node (each platform supplies its own glyph).
export function DropdownItem({ label, icon, detail, selected = false, disabled = false, danger = false, onPress, palette,
  numberOfLines, accessibilityRole = 'menuitem', testID }) {
  const color = danger ? palette.danger : palette.textSecondary;
  return <Pressable accessibilityRole={accessibilityRole} accessibilityLabel={label}
    accessibilityState={{ disabled, selected }} disabled={disabled} onPress={onPress} testID={testID}
    style={({ hovered, pressed }) => [styles.item, (hovered || pressed || selected) && !disabled && { backgroundColor: palette.surfaceMuted },
      disabled && { opacity: 0.5 }]}>
    {icon || null}
    <Text numberOfLines={numberOfLines} style={[styles.itemText, { color }]}>{label}</Text>
    {detail ? <Text style={[styles.itemDetail, { color: palette.textMuted }]}>{detail}</Text> : null}
  </Pressable>;
}

const styles = StyleSheet.create({
  item: { flexDirection: 'row', alignItems: 'center', gap: DROPDOWN.itemGap,
    paddingHorizontal: DROPDOWN.itemPaddingHorizontal, paddingVertical: DROPDOWN.itemPaddingVertical },
  itemText: { flexShrink: 1, fontSize: DROPDOWN.fontSize },
  itemDetail: { marginLeft: 'auto', fontSize: 12 },
  modalRoot: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 24 },
  menu: { width: DROPDOWN.width, borderRadius: DROPDOWN.radius, borderWidth: 1, paddingVertical: DROPDOWN.paddingVertical },
  popover: { position: 'absolute', shadowColor: '#000', shadowOpacity: 0.35, shadowRadius: 12,
    shadowOffset: { width: 0, height: 6 }, elevation: 8 },
});
