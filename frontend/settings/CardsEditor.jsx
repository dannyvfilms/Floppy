import React, { useEffect, useMemo, useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { FormSaveBar } from '../ui/FormSaveBar';
import { SelectField } from '../ui/SelectField';

const defaultPalette = {
  background: '#18181b',
  surface: '#27272a',
  surfaceStrong: '#3f3f46',
  surfaceMuted: '#52525b',
  border: '#52525b',
  text: '#fafafa',
  textSecondary: '#d4d4d8',
  textMuted: '#a1a1aa',
  accent: '#6366f1',
  accentStrong: '#4f46e5',
  accentText: '#ffffff',
  warning: '#f59e0b',
  danger: '#ef4444',
};

const defaultButtonPalette = {
  primary: { background: '#4f46e5', pressed: '#4338ca', hovered: '#4338ca', text: '#ffffff', border: 'transparent' },
  surface: { background: '#3f3f46', pressed: '#52525b', hovered: '#52525b', text: '#fafafa', border: '#3f3f46' },
  radius: 6,
};

const defaultLabels = {
  mediaCards: 'Media Cards',
  cardActions: 'Card actions',
  cardActionsHelp: 'Applies to every media type. Desktop hover actions stay available.',
  hoverActions: 'Hover actions on mobile',
  mediaType: 'Media type',
  copyFrom: 'Copy settings from',
  chooseType: 'Choose a media type',
  settingsActions: 'Settings actions',
  chooseAction: 'Choose an action',
  resetType: 'Reset type',
  useDefaults: 'Use defaults',
  allHover: 'Show all lines on hover',
  allAlways: 'Always show all lines',
  preview: 'Preview',
  sampleTitle: 'Sample title',
  ratingDisplay: 'Rating display',
  showRating: 'Show rating',
  hideRating: 'Hide rating',
  zeroRatings: 'Zero ratings',
  showZeros: 'Show zero ratings',
  hideZeros: 'Hide zero ratings',
  titleOverflow: 'Title overflow',
  ellipsis: 'Shorten with ellipsis',
  wrap: 'Wrap onto multiple lines',
  clip: 'Clip at the edge',
  titleLines: 'Title lines',
  oneLine: '1 line',
  twoLines: '2 lines',
  threeLines: '3 lines',
  allLines: 'All lines',
  titleHover: 'Title on hover',
  expandTitle: 'Expand title',
  keepTitle: 'Keep title unchanged',
  titleHoverLines: 'Title lines on hover',
  addLine: 'Add a line',
  chooseProperty: 'Choose a property',
  onCard: 'On card',
  noProperties: 'No properties yet. Choose a property above to add a line.',
  lineVisibility: 'Line visibility',
  showOnHover: 'Show on hover',
  alwaysShow: 'Always show',
  addToLine: 'Add to this line',
  remove: 'Remove',
  moveFieldLeft: 'Move property left',
  moveFieldRight: 'Move property right',
  moveLineUp: 'Move line up',
  moveLineDown: 'Move line down',
  unmatched: 'Not available on this media type',
  save: 'Save',
  saving: 'Saving…',
  savedTitle: 'All changes saved',
  savedCopy: 'Your card layouts are up to date.',
  dirtyTitle: 'Unsaved changes',
  dirtyCopy: 'Save your card layouts to keep your changes.',
  savingTitle: 'Saving card layouts',
  savingCopy: 'Applying your card layouts…',
  errorTitle: 'Could not save card layouts',
  saveError: 'Check the highlighted settings and try again.',
  validationError: 'Some card settings need attention.',
  lineError: 'Each line needs one to three properties.',
  progressError: 'Progress must be on its own line.',
};

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

function clampTitleLines(value) {
  if (value === 'all') return 'all';
  const count = Number(value);
  if (!Number.isInteger(count)) return 1;
  return Math.min(3, Math.max(1, count));
}

function raiseHoverLines(hoverLines, lines) {
  if (lines === 'all') return 'all';
  if (hoverLines === 'all') return 'all';
  return hoverLines < lines ? lines : hoverLines;
}

function ensureTitle(profile) {
  if (!profile.options || typeof profile.options !== 'object') profile.options = {};
  if (!profile.options.rating) profile.options.rating = { hide_zero: false, show: true };
  if (profile.options.rating.show === undefined) profile.options.rating.show = true;
  const title = profile.options.title;
  if (!title || typeof title !== 'object') {
    profile.options.title = { overflow: 'ellipsis', lines: 1, hover: 'bleed', hover_lines: 3 };
    return;
  }
  if (!['ellipsis', 'wrap', 'clip'].includes(title.overflow)) title.overflow = 'ellipsis';
  if (!['bleed', 'stay'].includes(title.hover)) title.hover = 'bleed';
  title.lines = clampTitleLines(title.lines);
  title.hover_lines = raiseHoverLines(clampTitleLines(title.hover_lines), title.lines);
}

function isolateProgress(lines) {
  const next = [];
  let progressMode = null;
  (lines || []).forEach(line => {
    const fields = (line.fields || []).filter(fieldId => fieldId !== 'progress');
    if ((line.fields || []).includes('progress')) progressMode = line.display || 'hover';
    if (fields.length) next.push({ fields, display: line.display || 'hover' });
  });
  if (progressMode) next.push({ fields: ['progress'], display: progressMode });
  return next;
}

function flatten(profile) {
  profile.fields = profile.lines.flatMap(line => line.fields);
  return profile;
}

function normalizeProfile(profile) {
  const next = clone(profile || {});
  if (!Array.isArray(next.lines)) {
    next.lines = (next.fields || []).map(fieldId => ({ fields: [fieldId], display: 'hover' }));
  }
  next.lines = isolateProgress(next.lines);
  ensureTitle(next);
  return flatten(next);
}

function sameValues(left, right) {
  return JSON.stringify(left) === JSON.stringify(right);
}

/**
 * Shared per-media-type card layout editor with a data-driven live preview.
 * The caller owns the saved profiles and touch behaviour plus persistence.
 */
export function CardsEditor({
  catalog = [],
  saved = {},
  initialSaved,
  initialTouchActions = false,
  active,
  touchActions = false,
  onChange,
  onSave,
  validate,
  labels,
  palette = {},
  buttonPalette = {},
  disabled = false,
  renderPreview,
}) {
  const copy = { ...defaultLabels, ...labels };
  const colors = { ...defaultPalette, ...palette };
  const typeIds = catalog.map(entry => entry.id);
  const [currentType, setCurrentType] = useState(typeIds.includes(active) ? active : (typeIds[0] || 'movie'));
  const [unmatched, setUnmatched] = useState({});
  const [saving, setSaving] = useState(false);
  const [localErrors, setLocalErrors] = useState({});
  const [localError, setLocalError] = useState('');
  const values = { saved, touchActions: Boolean(touchActions) };
  const serialized = useMemo(() => JSON.stringify(values), [saved, touchActions]);
  const baseline = { saved: initialSaved || saved, touchActions: Boolean(initialTouchActions) };
  const dirty = useMemo(() => !sameValues(values, baseline), [saved, touchActions, initialSaved, initialTouchActions]);
  const current = catalog.find(entry => entry.id === currentType) || catalog[0];
  const profile = useMemo(() => normalizeProfile(saved[currentType] || initialSaved?.[currentType] || { lines: [] }), [saved, initialSaved, currentType]);

  useEffect(() => {
    setLocalError('');
    setLocalErrors({});
  }, [serialized]);

  function update(nextSaved, nextTouch = touchActions) {
    onChange?.({ saved: nextSaved, touchActions: Boolean(nextTouch) });
  }

  function setProfile(nextProfile) {
    const nextSaved = { ...saved, [currentType]: flatten(nextProfile) };
    update(nextSaved);
  }

  function currentProfileBase() {
    return normalizeProfile(saved[currentType] || initialSaved?.[currentType] || { lines: [] });
  }

  function fieldLabel(fieldId) {
    return current?.fields?.find(field => field.id === fieldId)?.label || fieldId;
  }

  function allowedField(fieldId) {
    return (current?.fields || []).some(field => field.id === fieldId);
  }

  function usedFields(nextProfile) {
    const used = new Set();
    (nextProfile.lines || []).forEach(line => line.fields.forEach(fieldId => used.add(fieldId)));
    return used;
  }

  function poolFields(nextProfile = profile) {
    const used = usedFields(nextProfile);
    const fields = (current?.fields || []).filter(field => !used.has(field.id));
    const extras = (unmatched[currentType] || []).filter(field => !used.has(field.id));
    return fields.concat(extras.map(field => ({ ...field, unmatched: true })));
  }

  function copySources() {
    const families = [['tv', 'season', 'episode'], ['book', 'comic', 'manga']];
    const family = families.find(group => group.includes(currentType)) || [];
    return catalog
      .filter(entry => entry.id !== currentType)
      .sort((left, right) => {
        const leftRank = family.indexOf(left.id);
        const rightRank = family.indexOf(right.id);
        const leftOrder = leftRank === -1 ? family.length : leftRank;
        const rightOrder = rightRank === -1 ? family.length : rightRank;
        if (leftOrder !== rightOrder) return leftOrder - rightOrder;
        return String(left.label).localeCompare(String(right.label));
      });
  }

  function writeLines(lines) {
    const next = currentProfileBase();
    next.lines = isolateProgress(lines);
    setProfile(next);
  }

  function addField(fieldId, lineIndex = null) {
    if (!fieldId || !allowedField(fieldId)) return;
    if (fieldId === 'progress') {
      placeProgress(null);
      return;
    }
    const next = currentProfileBase();
    if (lineIndex !== null) {
      const line = next.lines[lineIndex];
      if (!line || line.fields.length >= 3 || line.fields.includes('progress') || line.fields.includes(fieldId)) return;
      line.fields = [...line.fields, fieldId];
    } else {
      next.lines.push({ fields: [fieldId], display: 'hover' });
    }
    setProfile(next);
  }

  function placeProgress(fromLineIndex) {
    const next = currentProfileBase();
    let display = 'hover';
    if (fromLineIndex !== null) {
      const fromLine = next.lines[fromLineIndex];
      if (!fromLine) return;
      display = fromLine.display || 'hover';
      fromLine.fields = fromLine.fields.filter(fieldId => fieldId !== 'progress');
    }
    next.lines = next.lines.filter(line => line.fields.length > 0);
    if (!next.lines.some(line => line.fields.length === 1 && line.fields[0] === 'progress')) {
      next.lines.push({ fields: ['progress'], display });
    }
    setProfile(next);
  }

  function removeField(lineIndex, fieldId) {
    const next = currentProfileBase();
    const line = next.lines[lineIndex];
    if (!line) return;
    line.fields = line.fields.filter(id => id !== fieldId);
    next.lines = next.lines.filter(entry => entry.fields.length > 0);
    setProfile(next);
  }

  function moveField(lineIndex, fieldId, direction) {
    const next = currentProfileBase();
    const line = next.lines[lineIndex];
    if (!line) return;
    const index = line.fields.indexOf(fieldId);
    const target = index + direction;
    if (index < 0 || target < 0 || target >= line.fields.length) return;
    const fields = [...line.fields];
    [fields[index], fields[target]] = [fields[target], fields[index]];
    line.fields = fields;
    setProfile(next);
  }

  function reorderLine(index, direction) {
    const next = currentProfileBase();
    const target = index + direction;
    if (target < 0 || target >= next.lines.length) return;
    const lines = [...next.lines];
    [lines[index], lines[target]] = [lines[target], lines[index]];
    next.lines = lines;
    setProfile(next);
  }

  function setLineMode(index, mode) {
    const next = currentProfileBase();
    if (next.lines[index]) next.lines[index].display = mode;
    setProfile(next);
  }

  function setAllLinesMode(mode) {
    const next = currentProfileBase();
    next.lines = next.lines.map(line => ({ ...line, display: mode }));
    setProfile(next);
  }

  function setOption(group, key, value) {
    const next = currentProfileBase();
    ensureTitle(next);
    next.options[group][key] = value;
    setProfile(next);
  }

  function setTitleLines(key, value) {
    const next = currentProfileBase();
    ensureTitle(next);
    next.options.title[key] = clampTitleLines(value);
    next.options.title.hover_lines = raiseHoverLines(next.options.title.hover_lines, next.options.title.lines);
    setProfile(next);
  }

  function setTitleHover(value) {
    const next = currentProfileBase();
    ensureTitle(next);
    next.options.title.hover = value;
    next.options.title.hover_lines = raiseHoverLines(next.options.title.hover_lines, next.options.title.lines);
    setProfile(next);
  }

  function titleLineVisible(count) {
    const lines = profile.options?.title?.lines || 1;
    if (count === 'all') return true;
    return lines !== 'all' && Number(count) >= lines;
  }

  function resetType() {
    setUnmatched(current => ({ ...current, [currentType]: [] }));
    writeLines([]);
  }

  function useDefaults() {
    const base = initialSaved?.[currentType];
    if (!base) return;
    setUnmatched(current => ({ ...current, [currentType]: [] }));
    const nextSaved = { ...saved, [currentType]: normalizeProfile(base) };
    update(nextSaved);
  }

  function copyFrom(sourceId) {
    if (!sourceId || sourceId === currentType) return;
    const source = normalizeProfile(saved[sourceId] || {});
    const allowed = new Set((current?.fields || []).map(field => field.id));
    const labelsById = new Map((catalog.find(entry => entry.id === sourceId)?.fields || []).map(field => [field.id, field.label]));
    const lines = [];
    const extras = [];
    const seen = new Set();
    source.lines.forEach(line => {
      const fields = [];
      line.fields.forEach(fieldId => {
        if (seen.has(fieldId)) return;
        seen.add(fieldId);
        if (allowed.has(fieldId)) fields.push(fieldId);
        else extras.push({ id: fieldId, label: labelsById.get(fieldId) || fieldId });
      });
      if (fields.length) lines.push({ fields, display: line.display || 'hover' });
    });
    const next = currentProfileBase();
    next.lines = isolateProgress(lines);
    if (source.options?.title) next.options.title = clone(source.options.title);
    if (source.options?.rating) next.options.rating = clone(source.options.rating);
    ensureTitle(next);
    setUnmatched(current => ({ ...current, [currentType]: extras }));
    setProfile(next);
  }

  function validateValues(nextSaved = saved) {
    if (validate) return validate({ saved: nextSaved, touchActions }) || {};
    const problems = {};
    Object.entries(nextSaved).forEach(([typeId, entry]) => {
      if (!typeIds.includes(typeId)) return;
      (entry.lines || []).forEach(line => {
        if (!line.fields || line.fields.length < 1 || line.fields.length > 3) problems.lines = copy.lineError;
        if (line.fields?.includes('progress') && line.fields.length > 1) problems.lines = copy.progressError;
      });
    });
    return problems;
  }

  async function save() {
    if (saving || disabled) return;
    const normalized = {};
    catalog.forEach(entry => {
      normalized[entry.id] = normalizeProfile(saved[entry.id] || initialSaved?.[entry.id] || { lines: [] });
    });
    const problems = validateValues(normalized);
    if (Object.keys(problems).length) {
      setLocalErrors(problems);
      setLocalError(copy.validationError);
      return;
    }
    setLocalErrors({});
    setLocalError('');
    setSaving(true);
    try {
      await onSave?.({ values: { saved: normalized, touchActions: Boolean(touchActions) }, payload: { version: 1, types: normalized } });
    } catch (reason) {
      setLocalError(reason?.message || copy.saveError);
    } finally {
      setSaving(false);
    }
  }

  const typeOptions = catalog.map(entry => ({ value: entry.id, label: entry.label }));
  const actionOptions = [
    { value: 'reset', label: copy.resetType },
    { value: 'defaults', label: copy.useDefaults },
    { value: 'hover', label: copy.allHover },
    { value: 'dormant', label: copy.allAlways },
  ];
  const lineOptions = [
    { value: 'hover', label: copy.showOnHover },
    { value: 'dormant', label: copy.alwaysShow },
  ];
  const titleLineOptions = [
    { value: '1', label: copy.oneLine },
    { value: '2', label: copy.twoLines },
    { value: '3', label: copy.threeLines },
    { value: 'all', label: copy.allLines },
  ];
  const hoverLineOptions = titleLineOptions.map(option => ({ ...option, disabled: option.value !== 'all' && !titleLineVisible(option.value) }));
  const available = poolFields(profile);
  const addOptions = available.filter(field => !field.unmatched).map(field => ({ value: field.id, label: field.label }));
  const extras = (unmatched[currentType] || []);

  return <View style={styles.form}>
    <View style={styles.section}>
      <View style={styles.sectionHeading}>
        <Text role="heading" aria-level={3} style={[styles.sectionTitle, { color: colors.text }]}>{copy.cardActions}</Text>
        <Text style={[styles.help, { color: colors.textMuted }]}>{copy.cardActionsHelp}</Text>
      </View>
      <SelectField
        id="cards-touch-actions"
        label={copy.hoverActions}
        options={[
          { value: 'off', label: 'Show actions on touch devices' },
          { value: 'on', label: 'Hide actions on touch devices' },
        ]}
        value={touchActions ? 'on' : 'off'}
        disabled={disabled}
        palette={colors}
        onChange={event => update(saved, event.target.value === 'on')}
      />
    </View>

    <View style={styles.section}>
      <View style={styles.sectionHeading}>
        <Text role="heading" aria-level={3} style={[styles.sectionTitle, { color: colors.text }]}>{copy.mediaCards}</Text>
        <Text style={[styles.help, { color: colors.textMuted }]}>Choose how cards look for each media type. Add properties below; up to three can share a line.</Text>
      </View>
      <SelectField
        id="cards-media-type"
        label={copy.mediaType}
        options={typeOptions}
        value={currentType}
        disabled={disabled}
        palette={colors}
        onChange={event => setCurrentType(event.target.value)}
      />
      <View style={styles.toolbarRow}>
        <View style={styles.toolbarField}>
          <SelectField
            id="cards-copy"
            label={copy.copyFrom}
            placeholder={copy.chooseType}
            options={copySources().map(entry => ({ value: entry.id, label: entry.label }))}
            value=""
            disabled={disabled}
            palette={colors}
            onChange={event => copyFrom(event.target.value)}
          />
        </View>
        <View style={styles.toolbarField}>
          <SelectField
            id="cards-actions"
            label={copy.settingsActions}
            placeholder={copy.chooseAction}
            options={actionOptions}
            value=""
            disabled={disabled}
            palette={colors}
            onChange={event => {
              const action = event.target.value;
              if (action === 'reset') resetType();
              else if (action === 'defaults') useDefaults();
              else if (action) setAllLinesMode(action);
            }}
          />
        </View>
      </View>

      <View style={[styles.preview, { borderColor: colors.border, backgroundColor: colors.background }]}>
        <Text style={[styles.label, { color: colors.textMuted }]}>{copy.preview}</Text>
        {renderPreview ? renderPreview({ type: currentType, saved }) : <View style={[styles.previewCard, { borderColor: colors.border, backgroundColor: colors.surface }]}>
          <View style={[styles.previewPoster, { backgroundColor: colors.surfaceStrong }]}>
            <Text style={[styles.previewPosterText, { color: colors.textMuted }]}>Floppy</Text>
          </View>
          <Text
            numberOfLines={profile.options?.title?.lines === 'all' ? undefined : Number(profile.options?.title?.lines || 1)}
            style={[styles.previewTitle, { color: colors.text }]}>
            {copy.sampleTitle}
          </Text>
          {profile.options?.rating?.show === false ? null : <Text style={[styles.previewRating, { color: colors.warning }]}>★★★★☆</Text>}
          {profile.lines.map((line, index) => <Text key={`preview-${index}`} style={[styles.previewLine, { color: line.display === 'dormant' ? colors.textSecondary : colors.textMuted }]}>
            {line.display === 'dormant' ? '' : '⋯ '}{line.fields.map(fieldLabel).join(' · ')}
          </Text>)}
        </View>}
      </View>

      <View style={styles.optionGrid}>
        <View style={styles.optionCell}>
          <SelectField
            id="cards-rating-show"
            label={copy.ratingDisplay}
            options={[{ value: 'show', label: copy.showRating }, { value: 'hide', label: copy.hideRating }]}
            value={profile.options?.rating?.show === false ? 'hide' : 'show'}
            disabled={disabled}
            palette={colors}
            onChange={event => setOption('rating', 'show', event.target.value === 'show')}
          />
        </View>
        <View style={styles.optionCell}>
          <SelectField
            id="cards-rating-zero"
            label={copy.zeroRatings}
            options={[{ value: 'show', label: copy.showZeros }, { value: 'hide', label: copy.hideZeros }]}
            value={profile.options?.rating?.hide_zero ? 'hide' : 'show'}
            disabled={disabled || profile.options?.rating?.show === false}
            palette={colors}
            onChange={event => setOption('rating', 'hide_zero', event.target.value === 'hide')}
          />
        </View>
        <View style={styles.optionCell}>
          <SelectField
            id="cards-title-overflow"
            label={copy.titleOverflow}
            options={[
              { value: 'ellipsis', label: copy.ellipsis },
              { value: 'wrap', label: copy.wrap },
              { value: 'clip', label: copy.clip },
            ]}
            value={profile.options?.title?.overflow || 'ellipsis'}
            disabled={disabled}
            palette={colors}
            onChange={event => setOption('title', 'overflow', event.target.value)}
          />
        </View>
        <View style={styles.optionCell}>
          <SelectField
            id="cards-title-lines"
            label={copy.titleLines}
            options={titleLineOptions}
            value={String(profile.options?.title?.lines || 1)}
            disabled={disabled}
            palette={colors}
            onChange={event => setTitleLines('lines', event.target.value)}
          />
        </View>
        <View style={styles.optionCell}>
          <SelectField
            id="cards-title-hover"
            label={copy.titleHover}
            options={[{ value: 'bleed', label: copy.expandTitle }, { value: 'stay', label: copy.keepTitle }]}
            value={profile.options?.title?.hover || 'bleed'}
            disabled={disabled}
            palette={colors}
            onChange={event => setTitleHover(event.target.value)}
          />
        </View>
        {profile.options?.title?.hover === 'bleed' ? <View style={styles.optionCell}>
          <SelectField
            id="cards-title-hover-lines"
            label={copy.titleHoverLines}
            options={hoverLineOptions}
            value={String(profile.options?.title?.hover_lines || 3)}
            disabled={disabled}
            palette={colors}
            onChange={event => setTitleLines('hover_lines', event.target.value)}
          />
        </View> : null}
      </View>

      {localErrors.lines ? <Text accessibilityRole="alert" style={[styles.help, { color: colors.danger }]}>{localErrors.lines}</Text> : null}

      {addOptions.length ? <SelectField
        id="cards-add-line"
        label={copy.addLine}
        placeholder={copy.chooseProperty}
        options={addOptions}
        value=""
        disabled={disabled}
        palette={colors}
        onChange={event => addField(event.target.value)}
      /> : null}

      {extras.length ? <View style={styles.extras}>
        <Text style={[styles.label, { color: colors.textMuted }]}>{copy.unmatched}</Text>
        <View style={styles.chipRow}>
          {extras.map(field => <Pressable
            key={field.id}
            accessibilityRole="button"
            accessibilityLabel={`${copy.remove}: ${field.label}`}
            onPress={() => setUnmatched(current => ({ ...current, [currentType]: (current[currentType] || []).filter(item => item.id !== field.id) }))}
            style={({ pressed }) => [styles.chip, { borderColor: colors.border, backgroundColor: colors.surface }, pressed && { backgroundColor: colors.surfaceStrong }]}>
            <Text style={[styles.chipText, { color: colors.textSecondary }]}>{field.label} ×</Text>
          </Pressable>)}
        </View>
      </View> : null}

      <View>
        <Text style={[styles.label, { color: colors.textMuted }]}>{copy.onCard}</Text>
        <View style={[styles.linesPanel, { borderColor: colors.border, backgroundColor: colors.surface }]}>
          {profile.lines.length === 0 ? <Text style={[styles.empty, { color: colors.textMuted }]}>{copy.noProperties}</Text> : null}
          {profile.lines.map((line, lineIndex) => {
            const lineAvailable = available.filter(field => !field.unmatched && field.id !== 'progress' && !line.fields.includes(field.id) && !line.fields.includes('progress') && line.fields.length < 3);
            return <View key={`line-${lineIndex}`} style={[styles.line, { borderColor: colors.border, backgroundColor: colors.background }]}>
              <View style={styles.lineHeader}>
                <Text style={[styles.lineTitle, { color: colors.text }]}>{`Line ${lineIndex + 1}`}</Text>
                <View style={styles.moveRow}>
                  <Pressable
                    accessibilityRole="button"
                    accessibilityLabel={`${copy.moveLineUp} ${lineIndex + 1}`}
                    disabled={disabled || lineIndex === 0}
                    onPress={() => reorderLine(lineIndex, -1)}
                    style={({ pressed }) => [styles.moveButton, { borderColor: colors.border }, pressed && { backgroundColor: colors.surfaceStrong }]}>
                    <Text style={[styles.moveText, { color: colors.textMuted }]}>↑</Text>
                  </Pressable>
                  <Pressable
                    accessibilityRole="button"
                    accessibilityLabel={`${copy.moveLineDown} ${lineIndex + 1}`}
                    disabled={disabled || lineIndex === profile.lines.length - 1}
                    onPress={() => reorderLine(lineIndex, 1)}
                    style={({ pressed }) => [styles.moveButton, { borderColor: colors.border }, pressed && { backgroundColor: colors.surfaceStrong }]}>
                    <Text style={[styles.moveText, { color: colors.textMuted }]}>↓</Text>
                  </Pressable>
                </View>
              </View>
              <View style={styles.chipRow}>
                {line.fields.map((fieldId, fieldIndex) => <View key={fieldId} style={[styles.fieldChip, { borderColor: colors.border, backgroundColor: colors.surfaceStrong }]}>
                  <Pressable
                    accessibilityRole="button"
                    accessibilityLabel={`${copy.moveFieldLeft}: ${fieldLabel(fieldId)}`}
                    disabled={disabled || fieldIndex === 0}
                    onPress={() => moveField(lineIndex, fieldId, -1)}
                    style={styles.fieldArrow}>
                    <Text style={[styles.fieldArrowText, { color: colors.textMuted }]}>‹</Text>
                  </Pressable>
                  <Text style={[styles.fieldChipText, { color: colors.text }]}>{fieldLabel(fieldId)}</Text>
                  <Pressable
                    accessibilityRole="button"
                    accessibilityLabel={`${copy.moveFieldRight}: ${fieldLabel(fieldId)}`}
                    disabled={disabled || fieldIndex === line.fields.length - 1}
                    onPress={() => moveField(lineIndex, fieldId, 1)}
                    style={styles.fieldArrow}>
                    <Text style={[styles.fieldArrowText, { color: colors.textMuted }]}>›</Text>
                  </Pressable>
                  <Pressable
                    accessibilityRole="button"
                    accessibilityLabel={`${copy.remove}: ${fieldLabel(fieldId)}`}
                    disabled={disabled}
                    onPress={() => removeField(lineIndex, fieldId)}
                    style={styles.fieldRemove}>
                    <Text style={[styles.fieldRemoveText, { color: colors.textSecondary }]}>×</Text>
                  </Pressable>
                </View>)}
              </View>
              <SelectField
                id={`cards-line-${lineIndex}-display`}
                label={copy.lineVisibility}
                options={lineOptions}
                value={line.display || 'hover'}
                disabled={disabled}
                palette={colors}
                onChange={event => setLineMode(lineIndex, event.target.value)}
              />
              {lineAvailable.length ? <SelectField
                id={`cards-line-${lineIndex}-add`}
                label={copy.addToLine}
                placeholder={copy.chooseProperty}
                options={lineAvailable.map(field => ({ value: field.id, label: field.label }))}
                value=""
                disabled={disabled}
                palette={colors}
                onChange={event => addField(event.target.value, lineIndex)}
              /> : null}
            </View>;
          })}
        </View>
      </View>
    </View>

    {copy.footnote ? <Text style={[styles.footnote, { color: colors.textMuted }]}>{copy.footnote}</Text> : null}

    <FormSaveBar
      dirty={dirty}
      saving={saving}
      disabled={disabled}
      error={localError}
      onSave={save}
      saveLabel={copy.save}
      labels={copy}
      palette={colors}
      buttonPalette={{ ...defaultButtonPalette, ...buttonPalette }}
    />
  </View>;
}

const styles = StyleSheet.create({
  form: { gap: 20 },
  section: { gap: 12 },
  sectionHeading: { gap: 2 },
  sectionTitle: { fontSize: 15, fontWeight: '700' },
  help: { fontSize: 12, lineHeight: 17 },
  label: { fontSize: 12, fontWeight: '600' },
  toolbarRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 10 },
  toolbarField: { flexGrow: 1, flexBasis: 180, minWidth: 0 },
  optionGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: 10 },
  optionCell: { flexGrow: 1, flexBasis: 150, minWidth: 0 },
  footnote: { fontSize: 12, lineHeight: 17 },
  preview: { gap: 8, borderWidth: 1, borderRadius: 10, padding: 12 },
  previewCard: { alignSelf: 'center', width: 160, gap: 5, borderWidth: 1, borderRadius: 10, padding: 8 },
  previewPoster: { width: '100%', aspectRatio: 2 / 3, borderRadius: 6, alignItems: 'center', justifyContent: 'center' },
  previewPosterText: { fontSize: 12, fontWeight: '600' },
  previewTitle: { fontSize: 13, fontWeight: '700' },
  previewRating: { fontSize: 12 },
  previewLine: { fontSize: 11, lineHeight: 15 },
  extras: { gap: 6 },
  chipRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 6 },
  chip: { borderWidth: 1, borderRadius: 6, paddingHorizontal: 8, paddingVertical: 4 },
  chipText: { fontSize: 12 },
  linesPanel: { gap: 8, borderWidth: 1, borderRadius: 10, padding: 10 },
  empty: { fontSize: 12, paddingVertical: 8, textAlign: 'center' },
  line: { gap: 8, borderWidth: 1, borderRadius: 8, padding: 8 },
  lineHeader: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 8 },
  lineTitle: { fontSize: 12, fontWeight: '600' },
  moveRow: { flexDirection: 'row', gap: 6 },
  moveButton: { width: 30, height: 28, borderWidth: 1, borderRadius: 6, alignItems: 'center', justifyContent: 'center' },
  moveText: { fontSize: 13, fontWeight: '700' },
  fieldChip: { flexDirection: 'row', alignItems: 'center', gap: 2, borderWidth: 1, borderRadius: 6, paddingHorizontal: 4, paddingVertical: 3 },
  fieldChipText: { fontSize: 12 },
  fieldArrow: { paddingHorizontal: 2 },
  fieldArrowText: { fontSize: 13, fontWeight: '700' },
  fieldRemove: { paddingHorizontal: 3 },
  fieldRemoveText: { fontSize: 13, fontWeight: '700' },
});
