import React, { useEffect, useMemo, useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { Button } from './Button';

const DEFAULT_PALETTE = {
  panel: '#27272a',
  surfaceDim: '#18181b',
  surfaceStrong: '#3f3f46',
  surfaceHover: '#52525b',
  border: '#3f3f46',
  text: '#fafafa',
  textSecondary: '#d4d4d8',
  textMuted: '#a1a1aa',
  accent: '#6366f1',
  accentContrast: '#18181b',
  warning: '#f59e0b',
  radius: 8,
  focusStyle: {},
};

const DEFAULT_LABELS = {
  catalogs: 'Catalogs',
  hint: 'Use the URL below, not the address of this page. It works in Stremio directly, or in an addon manager such as AIOStreams or AIOMetadata.',
  copy: 'Copy URL',
  copied: 'Copied.',
  install: 'Install in Stremio',
  noneSelected: 'Nothing selected. The default catalogs will be used.',
  copyFailed: 'Could not copy the URL. Select it and copy it manually.',
  publishPrefix: 'Publish ',
  moveUpPrefix: 'Move ',
  moveUpSuffix: ' up',
  moveDownPrefix: 'Move ',
  moveDownSuffix: ' down',
};

function mergePalette(palette) {
  return { ...DEFAULT_PALETTE, ...(palette || {}) };
}

function mergeLabels(labels) {
  return { ...DEFAULT_LABELS, ...(labels || {}) };
}

function buttonPalette(colors) {
  return {
    primary: {
      background: colors.accent,
      pressed: colors.accent,
      hovered: colors.accent,
      text: colors.accentContrast,
      border: 'transparent',
    },
    surface: {
      background: colors.surfaceStrong,
      pressed: colors.surfaceHover,
      hovered: colors.surfaceHover,
      text: colors.text,
      border: 'transparent',
    },
    radius: colors.radius,
    focusStyle: colors.focusStyle,
  };
}

function initialOrder(options, selectedIds) {
  const byId = new Map(options.map(option => [option.id, option]));
  const ordered = selectedIds.filter(id => byId.has(id));
  options.forEach(option => {
    if (!ordered.includes(option.id)) ordered.push(option.id);
  });
  return ordered;
}

function initialChecked(options, selectedIds) {
  return Object.fromEntries(options.map(option => [option.id, selectedIds.includes(option.id)]));
}

function configUrl(baseUrl, chosen) {
  const base = String(baseUrl || '').replace(/\/+$/, '');
  if (!chosen.length) return `${base}/manifest.json`;
  return `${base}/c/${chosen.map(id => encodeURIComponent(id)).join(',')}/manifest.json`;
}

function CatalogRow({
  option,
  index,
  last,
  checked,
  colors,
  copy,
  onToggle,
  onMove,
}) {
  return <View style={[styles.row, { borderColor: colors.border, borderBottomWidth: last ? 0 : 1 }]}>
    <Pressable accessibilityRole="checkbox" accessibilityState={{ checked }}
      accessibilityLabel={`${copy.publishPrefix}${option.label}`}
      onPress={onToggle} style={styles.checkTarget}>
      <View style={[styles.checkbox, {
        borderColor: checked ? colors.accent : colors.border,
        backgroundColor: checked ? colors.accent : 'transparent',
      }]}>
        {checked ? <Text style={[styles.checkMark, { color: colors.accentContrast }]}>✓</Text> : null}
      </View>
    </Pressable>
    <Text numberOfLines={1} style={[styles.name, { color: checked ? colors.text : colors.textMuted }]}>
      {`Floppy: ${option.label}`}
    </Text>
    <Text style={[styles.type, { color: colors.textMuted }]}>{option.stremio_type}</Text>
    <Pressable accessibilityRole="button"
      accessibilityLabel={`${copy.moveUpPrefix}${option.label}${copy.moveUpSuffix}`}
      accessibilityState={{ disabled: index === 0 }}
      disabled={index === 0}
      onPress={() => onMove(index, -1)}
      style={[styles.move, { backgroundColor: colors.surfaceStrong, opacity: index === 0 ? 0.3 : 1 }]}>
      <Text style={[styles.moveText, { color: colors.textSecondary }]}>↑</Text>
    </Pressable>
    <Pressable accessibilityRole="button"
      accessibilityLabel={`${copy.moveDownPrefix}${option.label}${copy.moveDownSuffix}`}
      accessibilityState={{ disabled: last }}
      disabled={last}
      onPress={() => onMove(index, 1)}
      style={[styles.move, { backgroundColor: colors.surfaceStrong, opacity: last ? 0.3 : 1 }]}>
      <Text style={[styles.moveText, { color: colors.textSecondary }]}>↓</Text>
    </Pressable>
  </View>;
}

export function StremioAddonConfigurator({
  options = [],
  selectedIds = [],
  baseUrl = '',
  labels = {},
  palette = {},
  onCopy,
  onInstall,
  onConfigurationChange,
}) {
  const colors = mergePalette(palette);
  const copy = mergeLabels(labels);
  const buttons = buttonPalette(colors);
  const optionKey = JSON.stringify(options.map(option => option.id));
  const selectedKey = JSON.stringify(selectedIds);
  const [order, setOrder] = useState(() => initialOrder(options, selectedIds));
  const [checked, setChecked] = useState(() => initialChecked(options, selectedIds));
  const [copied, setCopied] = useState(false);
  const [copyError, setCopyError] = useState('');
  const byId = useMemo(() => Object.fromEntries(options.map(option => [option.id, option])), [optionKey]);

  useEffect(() => {
    setOrder(initialOrder(options, selectedIds));
    setChecked(initialChecked(options, selectedIds));
  }, [optionKey, selectedKey]);

  useEffect(() => {
    if (!copied) return undefined;
    const timer = setTimeout(() => setCopied(false), 2000);
    return () => clearTimeout(timer);
  }, [copied]);

  const chosen = order.filter(id => checked[id]);
  const url = configUrl(baseUrl, chosen);

  function toggle(id) {
    setChecked(current => ({ ...current, [id]: !current[id] }));
    onConfigurationChange?.({ selected: chosen.includes(id) ? chosen.filter(item => item !== id) : [...chosen, id], order: [...order] });
  }

  function move(index, delta) {
    const target = index + delta;
    if (target < 0 || target >= order.length) return;
    const next = [...order];
    [next[index], next[target]] = [next[target], next[index]];
    setOrder(next);
    onConfigurationChange?.({ selected: next.filter(id => checked[id]), order: next });
  }

  async function copyUrl() {
    try {
      await onCopy?.(url);
      setCopied(true);
      setCopyError('');
    } catch (error) {
      setCopied(false);
      setCopyError(error?.message || copy.copyFailed);
    }
  }

  return <View style={styles.root}>
    <Text role="heading" aria-level={2} style={[styles.heading, { color: colors.textMuted }]}>{copy.catalogs}</Text>
    <View style={[styles.list, { borderColor: colors.border, backgroundColor: colors.panel }]}>
      {order.map((id, index) => {
        const option = byId[id];
        if (!option) return null;
        return <CatalogRow key={id} option={option} index={index} last={index === order.length - 1}
          checked={Boolean(checked[id])} colors={colors} copy={copy}
          onToggle={() => toggle(id)} onMove={move} />;
      })}
    </View>

    <Text style={[styles.hint, { color: colors.textMuted }]}>{copy.hint}</Text>
    <View style={[styles.urlBox, { borderColor: colors.border, backgroundColor: colors.surfaceDim }]}>
      <Text selectable accessibilityLabel={copy.copy} style={[styles.url, { color: colors.textSecondary }]}>{url}</Text>
    </View>

    {chosen.length ? null : <Text style={[styles.warning, { color: colors.warning }]}>{copy.noneSelected}</Text>}
    {copyError ? <Text accessibilityRole="alert" style={[styles.warning, { color: colors.warning }]}>{copyError}</Text> : null}

    <View style={styles.actions}>
      <Button label={copy.install} onPress={() => onInstall?.(url)} palette={buttons} />
      <Button label={copied ? copy.copied : copy.copy} tone="surface" onPress={copyUrl} palette={buttons} />
    </View>
  </View>;
}

const styles = StyleSheet.create({
  root: { gap: 12 },
  heading: { fontSize: 12, fontWeight: '700', letterSpacing: 0.8, textTransform: 'uppercase' },
  list: { borderWidth: 1, borderRadius: 8, paddingHorizontal: 12, paddingVertical: 4 },
  row: { flexDirection: 'row', alignItems: 'center', gap: 10, paddingVertical: 8 },
  checkTarget: { paddingVertical: 2, paddingRight: 2 },
  checkbox: { width: 18, height: 18, borderRadius: 4, borderWidth: 1, alignItems: 'center', justifyContent: 'center' },
  checkMark: { fontSize: 12, fontWeight: '700', lineHeight: 16 },
  name: { flexGrow: 1, flexShrink: 1, fontSize: 14 },
  type: { fontSize: 12 },
  move: { width: 28, height: 28, borderRadius: 6, alignItems: 'center', justifyContent: 'center' },
  moveText: { fontSize: 14, lineHeight: 18 },
  hint: { fontSize: 12, lineHeight: 17 },
  urlBox: { borderWidth: 1, borderRadius: 6, padding: 12 },
  url: { fontFamily: 'monospace', fontSize: 12, lineHeight: 17 },
  warning: { fontSize: 12, lineHeight: 17 },
  actions: { flexDirection: 'row', flexWrap: 'wrap', gap: 10 },
});
