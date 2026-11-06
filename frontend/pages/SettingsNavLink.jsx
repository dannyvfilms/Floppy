import React from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { Icon } from '../ui/Icon';

// One settings navigation row. The browser adapter attaches the server URL as a
// native anchor so HTMX boost keeps working; native supplies onPress navigation.
export function SettingsNavLink({
  item,
  current = false,
  available = true,
  labels = {},
  palette = {},
  renderIcon,
  onPress,
  ...platformProps
}) {
  return <Pressable accessibilityRole={item.url ? 'link' : 'button'}
    accessibilityLabel={item.label}
    accessibilityHint={available ? undefined : labels.serverOnly}
    aria-current={current ? 'page' : undefined}
    accessibilityState={{ selected: current, disabled: !available }}
    disabled={!available}
    onPress={available ? onPress : undefined}
    {...platformProps}
    style={({ pressed, hovered, focused }) => [styles.item, {
      borderLeftColor: current ? palette.accentStrong || '#4f46e5' : 'transparent',
      backgroundColor: current ? (palette.surfaceStrong || '#3f3f46')
        : (hovered || pressed) ? (palette.surfaceMuted || '#52525b') : 'transparent',
      opacity: available ? 1 : 0.55,
    }, focused && palette.focusStyle]}>
    {item.iconSpec ? <View style={styles.itemIcon}><Icon spec={item.iconSpec} /></View>
      : renderIcon ? <View style={styles.itemIcon}>{renderIcon(item.icon, item)}</View> : null}
    <Text style={[styles.itemLabel, {
      color: current ? (palette.text || '#fafafa') : (palette.textMuted || '#a1a1aa'),
    }]}>{item.label}</Text>
    {available ? null : <Text style={[styles.itemMeta, { color: palette.textMuted || '#a1a1aa' }]}>{labels.serverOnly}</Text>}
  </Pressable>;
}

const styles = StyleSheet.create({
  item: { flexDirection: 'row', alignItems: 'center', gap: 12, borderLeftWidth: 2, paddingHorizontal: 8, paddingVertical: 8, borderRadius: 6, minWidth: 0 },
  itemIcon: { alignItems: 'center', justifyContent: 'center', width: 20, height: 20 },
  itemLabel: { fontSize: 14, lineHeight: 20, flexGrow: 1, flexShrink: 1, minWidth: 0 },
  itemMeta: { fontSize: 10, flexShrink: 0 },
});
