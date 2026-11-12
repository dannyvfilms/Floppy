import React, { useMemo, useRef, useState } from 'react';
import { PanResponder, StyleSheet, View } from 'react-native';
import { Icon } from './Icon';

function ReorderRow({ children, label, index, count, positions, onMove, icon, palette, disabled }) {
  const [offset, setOffset] = useState(0);
  const latest = useRef();
  latest.current = { index, count, positions, onMove, disabled };
  const responder = useMemo(() => PanResponder.create({
    onStartShouldSetPanResponder: () => !latest.current.disabled,
    onMoveShouldSetPanResponder: () => !latest.current.disabled,
    onPanResponderMove: (_, gesture) => setOffset(gesture.dy),
    onPanResponderRelease: (_, gesture) => {
      const current = latest.current;
      const origin = current.positions.current[current.index];
      if (origin) {
        const center = origin.y + origin.height / 2 + gesture.dy;
        let target = current.index;
        let distance = Infinity;
        current.positions.current.forEach((row, position) => {
          if (!row) return;
          const next = Math.abs(center - row.y - row.height / 2);
          if (next < distance) { target = position; distance = next; }
        });
        if (target !== current.index) current.onMove(current.index, target);
      }
      setOffset(0);
    },
    onPanResponderTerminate: () => setOffset(0),
  }), []);
  const handle = <View {...responder.panHandlers} hitSlop={8}
    accessible accessibilityRole="adjustable" accessibilityLabel={`Reorder ${label}`}
    accessibilityHint="Drag to reorder, or use the move up and move down accessibility actions."
    accessibilityState={{ disabled }}
    accessibilityValue={{ min: 1, max: count, now: index + 1 }}
    aria-valuemin={1} aria-valuemax={count} aria-valuenow={index + 1}
    accessibilityActions={disabled ? [] : [
      ...(index > 0 ? [{ name: 'decrement', label: 'Move up' }] : []),
      ...(index < count - 1 ? [{ name: 'increment', label: 'Move down' }] : []),
    ]}
    onAccessibilityAction={event => {
      if (disabled) return;
      if (!['increment', 'decrement'].includes(event.nativeEvent.actionName)) return;
      const target = index + (event.nativeEvent.actionName === 'increment' ? 1 : -1);
      if (target >= 0 && target < count) onMove(index, target);
    }}
    style={styles.handle}>
    <Icon spec={icon} color={palette.textMuted} size={16} />
  </View>;
  return <View onLayout={event => { positions.current[index] = event.nativeEvent.layout; }}
    style={offset ? { transform: [{ translateY: offset }], zIndex: 1, opacity: 0.85 } : undefined}>
    {children(handle)}
  </View>;
}

/** Props-only reorder presentation; measured native layouts determine drop targets. */
export function ReorderList({ items, keyForItem, labelForItem, renderItem, onMove, icon, palette, disabled = false, gap = 12 }) {
  const positions = useRef([]);
  positions.current.length = items.length;
  if (!icon) return <>{items.map((item, index) => <React.Fragment key={keyForItem(item)}>{renderItem(item, index, null)}</React.Fragment>)}</>;
  return <View style={{ gap }}>
    {items.map((item, index) => <ReorderRow key={keyForItem(item)} label={labelForItem(item)}
      index={index} count={items.length} positions={positions} onMove={onMove}
      icon={icon} palette={palette} disabled={disabled}>
      {handle => renderItem(item, index, handle)}
    </ReorderRow>)}
  </View>;
}

const styles = StyleSheet.create({
  handle: { width: 16, minHeight: 20, alignItems: 'center', justifyContent: 'center', flexShrink: 0 },
});
