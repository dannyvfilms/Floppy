import React from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { Icon } from './Icon';
import { actionIcons } from './actionIcons';

export function DetailTrackSplit({ primary, edit, palette, inline = false, menu = [], menuOpen = false, horizontalPadding, secondaryWidth, secondaryIconSize }) {
  return primary ? <View style={styles.trackRoot}><View style={[styles.primaryRow, inline ? styles.primaryRowInline : null]}>
      <Pressable accessibilityRole="button" onPress={primary.onPress} disabled={primary.disabled}
        style={({ pressed, hovered }) => [styles.primary, inline ? { flexGrow: 0, flexShrink: 0, flexBasis: 'auto' } : null, horizontalPadding ? { paddingHorizontal: horizontalPadding } : null, edit ? styles.primaryJoined : null, {
          backgroundColor: pressed || hovered ? (palette.hoveredAccent || palette.accent) : palette.accentStrong,
          opacity: primary.disabled ? 0.6 : 1,
        }]}>
        {primary.icon ? <Icon spec={actionIcons[primary.icon === 'checkmark' ? 'check' : primary.icon]} size={20} color={palette.accentContrast} /> : null}
        <Text style={[styles.primaryText, { color: palette.accentContrast }]}>{primary.label}</Text>
      </Pressable>
      {edit ? <Pressable accessibilityRole="button" accessibilityLabel={edit.label} accessibilityState={edit.accessibilityState} onPress={edit.onPress}
        style={({ pressed, hovered }) => [styles.edit, secondaryWidth ? { width: secondaryWidth } : null, {
          backgroundColor: pressed || hovered ? (palette.hoveredAccent || palette.accent) : palette.accentStrong,
          borderLeftColor: palette.accent,
        }]}>
        <Icon spec={actionIcons[edit.icon || 'edit']} size={secondaryIconSize || 20} color={palette.accentContrast} />
      </Pressable> : null}
    </View>{menuOpen && menu.length ? <View style={[styles.trackMenu, { backgroundColor: palette.surfaceStrong, borderColor: palette.border }]}>
      {menu.map(item => <Pressable key={item.key} accessibilityRole="button" onPress={item.onPress}
        style={({ pressed, hovered }) => [styles.trackMenuItem, pressed || hovered ? { backgroundColor: palette.surfaceMuted } : null]}>
        <Text style={{ color: palette.textSecondary, fontSize: 14, lineHeight: 20 }}>{item.label}</Text>
      </Pressable>)}
    </View> : null}</View> : null;
}

const styles = StyleSheet.create({
  primaryRowInline: { flexShrink: 0 },
  primaryRow: { flexDirection: 'row' },
  trackRoot: { position: 'relative', zIndex: 50 },
  trackMenu: { position: 'absolute', top: '100%', left: 0, marginTop: 8, width: 208, borderWidth: 1, borderRadius: 6, paddingVertical: 4, zIndex: 50, shadowColor: '#000', shadowOpacity: 0.15, shadowRadius: 8, shadowOffset: { width: 0, height: 4 } },
  trackMenuItem: { paddingHorizontal: 16, paddingVertical: 8 },
  primary: { flex: 1, minHeight: 48, flexDirection: 'row', gap: 8, alignItems: 'center', justifyContent: 'center', borderRadius: 12, paddingHorizontal: 16 },
  primaryJoined: { borderTopRightRadius: 0, borderBottomRightRadius: 0 },
  primaryText: { fontSize: 16, fontWeight: '500' },
  edit: { width: 48, alignItems: 'center', justifyContent: 'center', borderTopRightRadius: 12, borderBottomRightRadius: 12, borderLeftWidth: 1 },
});
