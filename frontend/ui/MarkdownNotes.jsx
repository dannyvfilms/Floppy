import React, { useRef, useState } from 'react';
import { Pressable, StyleSheet, Text, TextInput, View } from 'react-native';
import { applyMarkdownAction, normalizeSelection } from './markdown';

const DEFAULT_PALETTE = {
  background: '#18181b',
  surface: '#27272a',
  surfaceStrong: '#3f3f46',
  border: '#52525b',
  text: '#fafafa',
  textSecondary: '#d4d4d8',
  textMuted: '#a1a1aa',
  accent: '#6366f1',
  link: '#818cf8',
  danger: '#f87171',
  codeBackground: '#1f2328',
};

const DEFAULT_LABELS = {
  write: 'Write',
  preview: 'Preview',
  hint: 'Markdown supported',
  heading: 'Heading',
  bold: 'Bold',
  italic: 'Italic',
  code: 'Code',
  link: 'Link',
  quote: 'Quote',
  bulletedList: 'Bulleted list',
  numberedList: 'Numbered list',
  emptyPreview: 'Nothing to preview yet.',
  boldPlaceholder: 'bold text',
  italicPlaceholder: 'italic text',
  codePlaceholder: 'code',
  linkPlaceholder: 'link text',
};

const TOOLBAR = [
  { action: 'heading', glyph: 'H', label: 'heading' },
  { action: 'bold', glyph: 'B', label: 'bold' },
  { action: 'italic', glyph: 'I', label: 'italic' },
  { action: 'code', glyph: '<>', label: 'code' },
  { action: 'link', glyph: 'Link', label: 'link' },
  { action: 'quote', glyph: '>', label: 'quote' },
  { action: 'ul', glyph: 'UL', label: 'bulletedList' },
  { action: 'ol', glyph: 'OL', label: 'numberedList' },
];

function errorText(error) {
  if (!error) return '';
  return Array.isArray(error) ? error.join(' ') : String(error);
}

export function MarkdownNotes({
  value = '',
  onChangeText,
  label = 'Notes',
  labelHidden = false,
  hint,
  placeholder,
  error,
  disabled = false,
  accessibilityLabel,
  labels: suppliedLabels,
  palette: suppliedPalette,
  Preview,
  minHeight = 150,
  testID,
}) {
  const labels = { ...DEFAULT_LABELS, ...(suppliedLabels || {}) };
  const palette = { ...DEFAULT_PALETTE, ...(suppliedPalette || {}) };
  const [tab, setTab] = useState('write');
  const [pendingSelection, setPendingSelection] = useState(null);
  const selection = useRef({ start: 0, end: 0 });
  const input = useRef(null);
  const message = errorText(error);

  function change(next) {
    onChangeText?.(next);
  }

  function rememberSelection(event) {
    selection.current = normalizeSelection(event?.nativeEvent?.selection, String(value).length);
    if (pendingSelection) setPendingSelection(null);
  }

  function runAction(action) {
    const next = applyMarkdownAction(value, selection.current, action, {
      bold: labels.boldPlaceholder,
      italic: labels.italicPlaceholder,
      code: labels.codePlaceholder,
      link: labels.linkPlaceholder,
    });
    selection.current = next.selection;
    setPendingSelection(next.selection);
    change(next.value);
    input.current?.focus?.();
  }

  const tabs = (
    <View style={styles.tabs}>
      {['write', 'preview'].map(key => {
        const active = tab === key;
        return <Pressable key={key}
          accessibilityRole="tab"
          accessibilityState={{ selected: active }}
          accessibilityLabel={labels[key]}
          onPress={() => setTab(key)}
          style={({ pressed }) => [styles.tab, active && { backgroundColor: palette.surfaceStrong }, pressed && styles.pressed]}>
          <Text style={[styles.tabText, { color: active ? palette.text : palette.textMuted }]}>{labels[key]}</Text>
        </Pressable>;
      })}
    </View>
  );

  const toolbar = (
    <View style={styles.toolbar}>
      {TOOLBAR.map(item => <Pressable key={item.action}
        accessibilityRole="button"
        accessibilityLabel={labels[item.label]}
        disabled={disabled}
        onPress={() => runAction(item.action)}
        style={({ pressed }) => [styles.tool, pressed && { backgroundColor: palette.surfaceStrong }]}>
        <Text style={[styles.toolText, { color: disabled ? palette.textMuted : palette.textSecondary }]}>{item.glyph}</Text>
      </Pressable>)}
    </View>
  );

  return <View style={styles.root} testID={testID}>
    {!labelHidden ? <View style={styles.labelRow}>
      <Text style={[styles.label, { color: palette.textSecondary }]}>{label}</Text>
      <Text style={[styles.hint, { color: palette.textMuted }]}>{hint || labels.hint}</Text>
    </View> : null}
    <View style={[styles.frame, { borderColor: palette.border, backgroundColor: palette.background }]}>
      <View style={[styles.header, { borderBottomColor: palette.border, backgroundColor: palette.surface }]}>
        {tabs}
        {toolbar}
      </View>
      {tab === 'write' ? <TextInput
        ref={input}
        accessibilityLabel={accessibilityLabel || label}
        accessibilityState={{ disabled }}
        editable={!disabled}
        multiline
        onChangeText={change}
        onSelectionChange={rememberSelection}
        placeholder={placeholder}
        placeholderTextColor={palette.textMuted}
        selection={pendingSelection || undefined}
        textAlignVertical="top"
        value={String(value ?? '')}
        style={[styles.input, {
          minHeight,
          color: palette.text,
          opacity: disabled ? 0.6 : 1,
        }]} /> : <View style={[styles.preview, { minHeight }]}>
        {Preview
          ? <Preview markdown={value} labels={labels} palette={palette} />
          : <Text style={[styles.fallback, { color: palette.textSecondary }]}>{String(value || labels.emptyPreview)}</Text>}
      </View>}
    </View>
    {message ? <Text accessibilityRole="alert" style={[styles.error, { color: palette.danger }]}>{message}</Text> : null}
  </View>;
}

const styles = StyleSheet.create({
  root: { gap: 6 },
  labelRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 8 },
  label: { flexShrink: 1, fontSize: 13, fontWeight: '600' },
  hint: { flexShrink: 0, fontSize: 11 },
  frame: { borderWidth: 1, borderRadius: 8, overflow: 'hidden' },
  header: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', gap: 4, borderBottomWidth: 1, paddingVertical: 2 },
  tabs: { flexDirection: 'row', alignItems: 'center', gap: 2, paddingHorizontal: 2 },
  tab: { borderRadius: 5, paddingHorizontal: 10, paddingVertical: 6 },
  tabText: { fontSize: 13, fontWeight: '600' },
  pressed: { opacity: 0.75 },
  toolbar: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', gap: 2, marginLeft: 'auto', paddingHorizontal: 2 },
  tool: { borderRadius: 5, paddingHorizontal: 8, paddingVertical: 6 },
  toolText: { fontSize: 12, fontWeight: '600' },
  input: { paddingHorizontal: 12, paddingVertical: 10, fontSize: 13, lineHeight: 19 },
  preview: { paddingHorizontal: 12, paddingVertical: 10 },
  fallback: { fontSize: 13, lineHeight: 19 },
  error: { fontSize: 12, lineHeight: 17 },
});
