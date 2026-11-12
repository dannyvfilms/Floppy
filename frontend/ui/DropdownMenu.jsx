import React, { useRef, useState } from 'react';
import { Pressable, StyleSheet, View, useWindowDimensions } from 'react-native';
import { Modal } from './Modal';
import { DROPDOWN, dropdownPlacement } from './dropdownMetrics';

// Anchor coordinates are in the window, while a sheet's modal host is local to
// the sheet. Measure the host so the same menu positions correctly in both.
export function DropdownMenu({ open, onClose, children, palette, closeLabel, anchor,
  estimatedHeight = 112, layerProps }) {
  const viewport = useWindowDimensions();
  const host = useRef(null);
  const [bounds, setBounds] = useState(null);
  const dropdown = Boolean(anchor);
  const width = bounds?.width || viewport.width;
  const height = bounds?.height || viewport.height;
  const placement = anchor ? dropdownPlacement(anchor, bounds || { x: 0, y: 0, width, height }, estimatedHeight) : null;
  return <Modal transparent visible={open} animationType={dropdown ? 'none' : 'fade'} onRequestClose={onClose}>
    <View ref={host} {...layerProps} style={dropdown ? StyleSheet.absoluteFill : styles.modalRoot}
      onLayout={() => host.current?.measureInWindow?.((hostX, hostY, hostWidth, hostHeight) => {
        setBounds(current => current?.x === hostX && current?.y === hostY && current?.width === hostWidth && current?.height === hostHeight
          ? current : { x: hostX, y: hostY, width: hostWidth, height: hostHeight });
      })}>
      <Pressable accessibilityRole="button" accessibilityLabel={closeLabel} onPress={onClose}
        style={[StyleSheet.absoluteFill, dropdown ? null : { backgroundColor: palette.overlay }]} />
      <View accessibilityViewIsModal style={[styles.menu, dropdown && [styles.popover, placement], {
        maxHeight: Math.max(80, height - 16), backgroundColor: dropdown ? palette.surface : palette.surfaceStrong,
        borderColor: palette.border,
      }]}>{children}</View>
    </View>
  </Modal>;
}

const styles = StyleSheet.create({
  modalRoot: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 24 },
  menu: { width: DROPDOWN.width, borderRadius: DROPDOWN.radius, borderWidth: 1, paddingVertical: DROPDOWN.paddingVertical },
  popover: { position: 'absolute', shadowColor: '#000', shadowOpacity: 0.35, shadowRadius: 12,
    shadowOffset: { width: 0, height: 6 }, elevation: 8 },
});
