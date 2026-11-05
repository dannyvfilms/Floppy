import React, { useState } from 'react';
import {
  Image,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';
import { Button } from './Button';
import { Spinner } from './Spinner';

const defaultPalette = {
  text: '#fafafa',
  textSecondary: '#d4d4d8',
  textMuted: '#a1a1aa',
  surface: '#27272a',
  surfaceStrong: '#3f3f46',
  surfaceMuted: '#52525b',
  border: '#3f3f46',
  accent: '#6366f1',
  accentStrong: '#4f46e5',
  accentText: '#ffffff',
  danger: '#ef4444',
  radius: 8,
  radiusSmall: 6,
  button: {
    radius: 6,
    primary: { background: '#4f46e5', pressed: '#4338ca', hovered: '#4338ca', text: '#ffffff', border: 'transparent' },
    surface: { background: '#3f3f46', pressed: '#52525b', hovered: '#52525b', text: '#fafafa', border: '#3f3f46' },
    focusStyle: {},
  },
};

const defaultLabels = {
  choose: 'Choose an image',
  drag: 'drag and drop',
  urlToggle: 'Enter a URL',
  urlPlaceholder: 'Link to an image, or to a book or comic page',
  urlLabel: 'Image or page link',
  current: 'Current',
  new: 'New',
  save: 'Save Changes',
  saving: 'Saving',
  cancel: 'Cancel',
  retry: 'Try again',
  candidatesLoading: 'Looking for other covers…',
  candidatesError: 'Other covers could not load.',
  candidatesEmpty: 'No other covers found.',
  accepted: 'JPEG, PNG or WebP, up to 10 MB',
  camera: 'Take a photo',
  selectedEdition: 'Selected',
  editionsLoading: 'Looking for editions…',
  editionsError: 'Editions could not load.',
  noEditions: 'No editions found.',
  noEditionsQuery: 'No editions match this search.',
};

function candidateId(candidate, index) {
  return candidate.id ?? candidate.uri ?? candidate.image ?? `candidate-${index}`;
}

function candidateUri(candidate) {
  return candidate.uri ?? candidate.image ?? '';
}

function Tile({ uri, label, selected, onPress, palette, copy, onError }) {
  return <Pressable
    accessibilityRole="button"
    accessibilityLabel={label}
    accessibilityState={{ selected }}
    onPress={onPress}
    style={styles.tile}>
    <Image
      source={{ uri }}
      accessibilityIgnoresInvertColors
      onError={onError}
      style={[styles.tileImage, {
        backgroundColor: palette.surfaceMuted,
        borderColor: selected ? palette.accent : 'transparent',
      }]}
    />
    {selected ? <View style={[styles.check, { backgroundColor: palette.accent }]}>
      <Text style={[styles.checkText, { color: palette.accentText }]}>✓</Text>
    </View> : null}
    <Text numberOfLines={2} style={[styles.tileLabel, { color: palette.textMuted }]}>{label}</Text>
    <Text style={styles.srOnly}>{selected ? copy.current : ''}</Text>
  </Pressable>;
}

export function ArtworkPicker({
  title,
  description,
  current,
  candidates = [],
  candidatesState = 'ready',
  selected = null,
  url = '',
  showUrl = false,
  dragActive = false,
  accepted,
  supportsDrag = true,
  cameraLabel = '',
  labels = {},
  palette: paletteOverrides,
  saving = false,
  error = '',
  onChooseFile,
  onCamera,
  onToggleUrl,
  onUrlChange,
  onPickCandidate,
  onReset,
  onSave,
  onRetryCandidates,
  testID,
}) {
  const palette = { ...defaultPalette, ...paletteOverrides };
  const copy = { ...defaultLabels, ...labels };
  const [failed, setFailed] = useState({});
  const currentUri = current?.uri ?? current ?? '';
  const selectedKind = selected?.kind ?? 'current';
  const currentSelected = selectedKind === 'current';
  const visibleCandidates = candidates.filter((candidate, index) => !failed[candidateId(candidate, index)]);
  const custom = selected && (selectedKind === 'file' || selectedKind === 'url');

  function failCandidate(candidate, index) {
    setFailed(value => ({ ...value, [candidateId(candidate, index)]: true }));
  }

  return <View style={styles.root} testID={testID}>
    {title ? <Text role="heading" aria-level={3} style={[styles.title, { color: palette.text }]}>{title}</Text> : null}
    {description ? <Text style={[styles.description, { color: palette.textMuted }]}>{description}</Text> : null}

    <View style={[styles.dropZone, {
      backgroundColor: palette.surfaceStrong,
      borderColor: dragActive ? palette.accent : 'transparent',
      borderStyle: dragActive ? 'dashed' : 'solid',
    }]}>
      <Pressable accessibilityRole="button" accessibilityLabel={copy.choose} onPress={onChooseFile}>
        <Text style={[styles.action, { color: palette.accent }]}>{copy.choose}</Text>
      </Pressable>
      {supportsDrag ? <>
        <Text style={[styles.dot, { color: palette.textMuted }]}>·</Text>
        <Text style={[styles.hint, { color: palette.textSecondary }]}>{copy.drag}</Text>
      </> : null}
      <Text style={[styles.dot, { color: palette.textMuted }]}>·</Text>
      <Pressable accessibilityRole="button" accessibilityLabel={copy.urlToggle} onPress={onToggleUrl}>
        <Text style={[styles.action, { color: palette.accent }]}>{copy.urlToggle}</Text>
      </Pressable>
      {onCamera ? <>
        <Text style={[styles.dot, { color: palette.textMuted }]}>·</Text>
        <Pressable accessibilityRole="button" accessibilityLabel={cameraLabel || copy.camera} onPress={onCamera}>
          <Text style={[styles.action, { color: palette.accent }]}>{cameraLabel || copy.camera}</Text>
        </Pressable>
      </> : null}
    </View>

    {showUrl ? <TextInput
      accessibilityLabel={copy.urlLabel}
      value={url}
      onChangeText={onUrlChange}
      placeholder={copy.urlPlaceholder}
      placeholderTextColor={palette.textMuted}
      autoCapitalize="none"
      autoCorrect={false}
      keyboardType="url"
      style={[styles.input, {
        color: palette.text,
        backgroundColor: palette.surfaceStrong,
        borderColor: palette.border,
        borderRadius: palette.radiusSmall,
      }]}
    /> : null}

    <Text style={[styles.accepted, { color: palette.textMuted }]}>{accepted || copy.accepted}</Text>

    <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.tiles}>
      <Tile
        uri={currentUri}
        label={copy.current}
        selected={currentSelected}
        onPress={onReset}
        palette={palette}
        copy={copy}
      />
      {custom ? <Tile
        uri={selected.uri}
        label={selected.title || copy.new}
        selected
        onPress={() => {}}
        palette={palette}
        copy={copy}
      /> : null}
      {candidatesState === 'loading' ? <View style={styles.state}>
        <Spinner size={16} color={palette.accent} />
        <Text accessibilityLiveRegion="polite" style={[styles.stateText, { color: palette.textMuted }]}>{copy.candidatesLoading}</Text>
      </View> : null}
      {candidatesState === 'error' ? <View style={styles.state}>
        <Text style={[styles.stateText, { color: palette.textMuted }]}>{copy.candidatesError}</Text>
        {onRetryCandidates ? <Pressable accessibilityRole="button" accessibilityLabel={copy.retry} onPress={onRetryCandidates}>
          <Text style={[styles.action, { color: palette.accent }]}>{copy.retry}</Text>
        </Pressable> : null}
      </View> : null}
      {candidatesState === 'ready' ? visibleCandidates.map((candidate, index) => {
        const id = candidateId(candidate, index);
        const uri = candidateUri(candidate);
        const isSelected = selectedKind === 'candidate' && selected?.id === id;
        return <Tile
          key={id}
          uri={uri}
          label={candidate.title || ''}
          selected={isSelected}
          onPress={() => onPickCandidate?.({ ...candidate, id, uri })}
          palette={palette}
          copy={copy}
          onError={() => failCandidate(candidate, index)}
        />;
      }) : null}
      {candidatesState === 'ready' && !visibleCandidates.length ? <View style={styles.state}>
        <Text style={[styles.stateText, { color: palette.textMuted }]}>{copy.candidatesEmpty}</Text>
      </View> : null}
    </ScrollView>

    {error ? <Text accessibilityLiveRegion="polite" role="alert" style={[styles.error, { color: palette.danger }]}>{error}</Text> : null}

    {selected && !currentSelected ? <View style={styles.actions}>
      <Button label={copy.cancel} tone="surface" onPress={onReset} palette={palette.button} />
      <Button label={saving ? copy.saving : copy.save} busy={saving} disabled={saving}
        onPress={onSave} palette={palette.button} />
    </View> : null}
  </View>;
}

function rowMeta(row) {
  return (row.meta || []).filter(Boolean);
}

export function EditionPicker({
  title,
  description,
  provider,
  query = '',
  placeholder,
  results = [],
  selected = null,
  selectedId = null,
  state = 'idle',
  open = false,
  overlay = false,
  labels = {},
  palette: paletteOverrides,
  onQueryChange,
  onFocus,
  onSelect,
  onRetry,
  testID,
}) {
  const palette = { ...defaultPalette, ...paletteOverrides };
  const copy = { ...defaultLabels, ...labels };
  const selectedRow = selectedId != null
    ? results.find(row => String(row.id) === String(selectedId))
    : null;
  const activeSelected = selected || selectedRow;
  return <View style={styles.root} testID={testID}>
    {title ? <Text role="heading" aria-level={3} style={[styles.title, { color: palette.text }]}>{title}</Text> : null}
    {provider ? <Text style={[styles.provider, { color: palette.textMuted }]}>{provider}</Text> : null}
    {description ? <Text style={[styles.description, { color: palette.textMuted }]}>{description}</Text> : null}

    {activeSelected ? <View style={styles.selectedBlock}>
      <Text style={[styles.selectedLabel, { color: palette.textMuted }]}>{copy.selectedEdition}</Text>
      <View style={[styles.selectedRow, {
        backgroundColor: palette.surface,
        borderColor: palette.border,
        borderRadius: palette.radiusSmall,
      }]}>
        <EditionImage uri={activeSelected.uri} palette={palette} />
        <View style={styles.rowText}>
          <Text style={[styles.rowTitle, { color: palette.text }]}>{activeSelected.title}</Text>
          {rowMeta(activeSelected).map((line, index) => <Text key={index} numberOfLines={2}
            style={[styles.rowMeta, { color: palette.textMuted }]}>{line}</Text>)}
        </View>
      </View>
    </View> : null}

    <View style={styles.search}>
      <TextInput
        accessibilityLabel={title || placeholder}
        value={query}
        onChangeText={onQueryChange}
        onFocus={onFocus}
        placeholder={placeholder}
        placeholderTextColor={palette.textMuted}
        autoComplete="off"
        autoCorrect={false}
        autoCapitalize="none"
        returnKeyType="search"
        style={[styles.input, {
          color: palette.text,
          backgroundColor: palette.surfaceStrong,
          borderColor: palette.border,
          borderRadius: palette.radiusSmall,
        }]}
      />
      {open ? <View style={[styles.results, overlay && styles.overlay, {
        backgroundColor: palette.surface,
        borderColor: palette.border,
        borderRadius: palette.radiusSmall,
      }]}>
        {state === 'loading' ? <View style={styles.state}>
          <Spinner size={16} color={palette.accent} />
          <Text accessibilityLiveRegion="polite" style={[styles.stateText, { color: palette.textMuted }]}>{copy.editionsLoading}</Text>
        </View> : null}
        {state === 'error' ? <View style={styles.state}>
          <Text style={[styles.stateText, { color: palette.textMuted }]}>{copy.editionsError}</Text>
          {onRetry ? <Pressable accessibilityRole="button" accessibilityLabel={copy.retry} onPress={onRetry}>
            <Text style={[styles.action, { color: palette.accent }]}>{copy.retry}</Text>
          </Pressable> : null}
        </View> : null}
        {state === 'ready' ? (results.length ? results.map((row, index) => {
          const isSelected = selectedId != null && String(row.id) === String(selectedId);
          return <Pressable
            key={row.id ?? index}
            accessibilityRole="button"
            accessibilityLabel={[row.title, ...rowMeta(row)].filter(Boolean).join(', ')}
            accessibilityState={{ selected: isSelected }}
            onPress={() => onSelect?.(row)}
            style={({ pressed }) => [styles.resultRow, {
              borderTopWidth: index === 0 ? 0 : 1,
              borderTopColor: palette.border,
              backgroundColor: pressed ? palette.surfaceStrong : 'transparent',
            }]}>
            <EditionImage uri={row.uri} palette={palette} />
            <View style={styles.rowText}>
              <Text style={[styles.rowTitle, { color: palette.text }]}>{row.title}</Text>
              {rowMeta(row).map((line, lineIndex) => <Text key={lineIndex} numberOfLines={2}
                style={[styles.rowMeta, { color: palette.textMuted }]}>{line}</Text>)}
            </View>
            {isSelected ? <Text style={[styles.selected, { color: palette.accent }]}>{copy.selectedEdition}</Text> : null}
          </Pressable>;
        }) : <Text style={[styles.empty, { color: palette.textMuted }]}>{query ? copy.noEditionsQuery : copy.noEditions}</Text>) : null}
      </View> : null}
    </View>
  </View>;
}

function EditionImage({ uri, palette }) {
  if (!uri) {
    return <View style={[styles.thumb, styles.thumbEmpty, { backgroundColor: palette.surfaceStrong }]}>
      <Text style={[styles.thumbGlyph, { color: palette.textMuted }]}>?</Text>
    </View>;
  }
  return <Image source={{ uri }} accessibilityIgnoresInvertColors
    style={[styles.thumb, { backgroundColor: palette.surfaceStrong }]} />;
}

const styles = StyleSheet.create({
  root: { gap: 10 },
  title: { fontSize: 17, fontWeight: '600' },
  description: { fontSize: 12, lineHeight: 18 },
  provider: { fontSize: 11, fontWeight: '700', letterSpacing: 0.5, textTransform: 'uppercase' },
  dropZone: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', justifyContent: 'center', gap: 8, borderWidth: 1, borderRadius: 10, paddingHorizontal: 14, paddingVertical: 20 },
  action: { fontSize: 13, fontWeight: '600' },
  hint: { fontSize: 13 },
  dot: { fontSize: 13 },
  input: { borderWidth: 1, paddingHorizontal: 10, paddingVertical: 9, fontSize: 13 },
  accepted: { fontSize: 11 },
  tiles: { flexDirection: 'row', gap: 12, paddingVertical: 4, alignItems: 'flex-start' },
  tile: { width: 120, gap: 4 },
  tileImage: { width: '100%', aspectRatio: 2 / 3, borderRadius: 8, borderWidth: 2 },
  tileLabel: { fontSize: 11 },
  check: { position: 'absolute', top: 4, right: 4, minWidth: 18, height: 18, borderRadius: 4, alignItems: 'center', justifyContent: 'center', paddingHorizontal: 3 },
  checkText: { fontSize: 11, fontWeight: '700' },
  srOnly: { fontSize: 1, opacity: 0, height: 0 },
  state: { flexDirection: 'row', alignItems: 'center', gap: 8, paddingVertical: 12, paddingHorizontal: 4, maxWidth: 260 },
  stateText: { fontSize: 12, lineHeight: 17 },
  error: { fontSize: 12, lineHeight: 17 },
  actions: { flexDirection: 'row', justifyContent: 'flex-end', gap: 8 },
  selectedBlock: { gap: 4 },
  selectedLabel: { fontSize: 11, fontWeight: '600' },
  selectedRow: { flexDirection: 'row', alignItems: 'center', gap: 10, borderWidth: 1, paddingHorizontal: 10, paddingVertical: 8 },
  rowText: { flex: 1, minWidth: 0, gap: 2 },
  rowTitle: { fontSize: 13 },
  rowMeta: { fontSize: 11 },
  selected: { fontSize: 11, fontWeight: '600' },
  search: { position: 'relative', zIndex: 5 },
  results: { borderWidth: 1, overflow: 'hidden' },
  overlay: { position: 'absolute', top: '100%', left: 0, right: 0, marginTop: 4, maxHeight: 384, zIndex: 50, overflow: 'auto' },
  resultRow: { flexDirection: 'row', alignItems: 'flex-start', gap: 10, paddingHorizontal: 10, paddingVertical: 8 },
  thumb: { width: 32, height: 40, borderRadius: 4 },
  thumbEmpty: { alignItems: 'center', justifyContent: 'center' },
  thumbGlyph: { fontSize: 14, fontWeight: '700' },
  empty: { fontSize: 12, paddingHorizontal: 10, paddingVertical: 8 },
});
