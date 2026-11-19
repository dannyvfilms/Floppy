import React from 'react';
import { Pressable, StyleSheet, Switch, Text, View } from 'react-native';
import { Button } from '../ui/Button';
import { Icon } from '../ui/Icon';
import { ReorderList } from '../ui/ReorderList';
import { ToggleChip } from '../ui/ToggleChip';

export const sidebarCopy = {
  title: 'Sidebar',
  description: 'Choose which media types appear and how they are ordered.',
  typesTitle: 'Media Types',
  typesCopy: 'Control which media types are visible throughout the app (sidebar, search, calendar, notifications). Use the arrows to set their sidebar order.',
  discover: 'Discover',
  save: 'Save Preferences',
};

function Row({ label, icon, enabled, onToggle, onUp, onDown, upDisabled, downDisabled, palette, arrows, handle, drag }) {
  return <View style={[styles.row, { backgroundColor: palette.surfaceStrong, borderRadius: drag ? 6 : palette.radius ?? 6 }]}>
    <View style={styles.label}>
      {handle || (onUp ? <View style={styles.arrows}>
        <Pressable accessibilityRole="button" accessibilityLabel={`Move ${label} up`} disabled={upDisabled}
          onPress={onUp} style={[styles.arrow, upDisabled && styles.dim]}>
          <Icon spec={arrows.up} color={palette.textMuted} size={16} />
        </Pressable>
        <Pressable accessibilityRole="button" accessibilityLabel={`Move ${label} down`} disabled={downDisabled}
          onPress={onDown} style={[styles.arrow, downDisabled && styles.dim]}>
          <Icon spec={arrows.down} color={palette.textMuted} size={16} />
        </Pressable>
      </View> : <View style={drag ? { width: 16 } : styles.arrows} />)}
      {icon ? <Icon spec={icon} color={palette.textMuted} size={20} /> : null}
      <Text style={[styles.text, { color: palette.textSecondary }]}>{label}</Text>
    </View>
    {drag ? <ToggleChip value={enabled} onChange={onToggle} label={label} labelHidden
      palette={{ ...palette, pageCards: true }} /> : <Switch value={enabled} onValueChange={onToggle} accessibilityLabel={label}
      trackColor={{ false: palette.surfaceMuted, true: palette.accentStrong }} thumbColor={palette.onAccentStrong || palette.text}
      activeThumbColor={palette.onAccentStrong || palette.text} />}
  </View>;
}

/** Settings > Sidebar: media-type visibility, order and the Discover switch. Props only. */
export function SettingsSidebarView({
  types = [], showDiscover = true, discoverIcon, arrows = {}, dragIcon, saving = false, error = '', success = '',
  titleIcon, typesIcon, onToggle, onMove, onToggleDiscover, onSave, labels = {}, palette = {}, buttonPalette = {},
}) {
  const copy = { ...sidebarCopy, ...labels };
  return <View testID="settings-card" style={[styles.card, { backgroundColor: palette.surface, borderRadius: palette.radius ?? 8 }]}>
    <View style={styles.title}>
      {titleIcon ? <Icon spec={titleIcon} color={palette.link} size={24} /> : null}
      <Text role="heading" aria-level={2} style={[styles.titleText, { color: palette.text }]}>{copy.title}</Text>
    </View>
    <Text style={[styles.copy, { color: palette.textMuted }, dragIcon && { marginBottom: 4 }]}>{copy.description}</Text>
    <View style={styles.title}>
      {typesIcon ? <Icon spec={typesIcon} color={palette.link} size={20} /> : null}
      <Text role="heading" aria-level={3} style={[styles.heading, { color: palette.text }]}>{copy.typesTitle}</Text>
    </View>
    <Text style={[styles.copy, { color: palette.textMuted }]}>{copy.typesCopy}</Text>
    <View style={styles.list}>
      <Row label={copy.discover} icon={discoverIcon} enabled={showDiscover} onToggle={onToggleDiscover} palette={palette} arrows={arrows} drag={Boolean(dragIcon)} />
      {dragIcon ? <ReorderList items={types} keyForItem={type => type.value} labelForItem={type => type.label}
        icon={dragIcon} palette={palette} disabled={saving}
        onMove={(from, to) => onMove?.(types[from].value, to - from)}
        renderItem={(type, index, handle) => <Row label={type.label} icon={type.icon} enabled={type.enabled}
          handle={handle} drag onToggle={() => onToggle?.(type.value)} palette={palette} arrows={arrows} />} />
        : types.map((type, index) => <Row key={type.value} label={type.label} icon={type.icon} enabled={type.enabled}
        onToggle={() => onToggle?.(type.value)} onUp={() => onMove?.(type.value, -1)} onDown={() => onMove?.(type.value, 1)}
        upDisabled={index === 0} downDisabled={index === types.length - 1} palette={palette} arrows={arrows} />)}
    </View>
    {error ? <Text accessibilityRole="alert" style={[styles.copy, { color: palette.danger }]}>{error}</Text> : null}
    {success ? <Text accessibilityRole="status" style={[styles.copy, { color: palette.success }]}>{success}</Text> : null}
    <View style={styles.save}>
      <Button label={saving ? 'Saving…' : copy.save} busy={saving} onPress={onSave} palette={buttonPalette} />
    </View>
  </View>;
}

const styles = StyleSheet.create({
  card: { padding: 24, gap: 16 },
  title: { flexDirection: 'row', alignItems: 'center', gap: 12 },
  titleText: { fontSize: 20, lineHeight: 28, fontWeight: '600' },
  copy: { fontSize: 14, lineHeight: 20 },
  heading: { fontSize: 18, lineHeight: 28, fontWeight: '600' },
  list: { gap: 12 },
  save: { flexDirection: 'row' },
  row: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', padding: 12, gap: 8 },
  label: { flexDirection: 'row', alignItems: 'center', gap: 8, flexShrink: 1 },
  arrows: { flexDirection: 'row', width: 56 },
  arrow: { width: 28, height: 28, alignItems: 'center', justifyContent: 'center' },
  dim: { opacity: 0.3 },
  text: { fontSize: 14, flexShrink: 1 },
});
