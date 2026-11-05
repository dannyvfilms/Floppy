import React, { useEffect, useMemo, useState } from 'react';
import { Pressable, StyleSheet, Text, TextInput, View } from 'react-native';
import { FormSaveBar } from '../ui/FormSaveBar';
import { SelectField } from '../ui/SelectField';
import { ToggleChip } from '../ui/ToggleChip';

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
  danger: '#ef4444',
};

const defaultButtonPalette = {
  primary: { background: '#4f46e5', pressed: '#4338ca', hovered: '#4338ca', text: '#ffffff', border: 'transparent' },
  surface: { background: '#3f3f46', pressed: '#52525b', hovered: '#52525b', text: '#fafafa', border: '#3f3f46' },
  radius: 6,
};

const defaultLabels = {
  title: 'Appearance',
  theme: 'Theme',
  themeHelp: 'Choose a starting point, then make it yours.',
  customPalette: 'Custom palette',
  detailPages: 'Detail pages',
  detailHelp: 'Keep useful sections visible and place them where you expect them.',
  pageType: 'Page type',
  shown: 'Shown',
  hidden: 'Hidden',
  moveUp: 'Move up',
  moveDown: 'Move down',
  save: 'Save appearance',
  saving: 'Saving…',
  savedTitle: 'All changes saved',
  savedCopy: 'Your appearance is up to date.',
  dirtyTitle: 'Unsaved changes',
  dirtyCopy: 'Changes apply after saving.',
  savingTitle: 'Saving appearance',
  savingCopy: 'Applying your appearance…',
  errorTitle: 'Could not save appearance',
  saveError: 'Check the highlighted settings and try again.',
  validationError: 'Some appearance settings need attention.',
  invalidColor: 'Enter a color like #10141f.',
};

const presetSwatches = {
  system: '#d4d4d8',
  light: '#f4f4f5',
  dark: '#3f3f46',
  catppuccin_mocha: '#cba6f7',
  dracula: '#bd93f9',
  nord: '#88c0d0',
  gruvbox: '#fabd2f',
  oled: '#000000',
  glass: '#a5b4fc',
  plex: '#e5a00d',
  projector: '#f59e0b',
  video_store: '#ef4444',
  custom: '#10b981',
};

const hexColor = /^#[0-9a-fA-F]{6}$/;

function sameValues(left, right) {
  return JSON.stringify(left) === JSON.stringify(right);
}

function enabledKeys(layouts, familyKey, zoneKey) {
  return layouts?.[familyKey]?.[zoneKey] || [];
}

function orderedSections(sections, order) {
  return [...sections].sort((left, right) => {
    const leftIndex = order.indexOf(left.key);
    const rightIndex = order.indexOf(right.key);
    return (leftIndex < 0 ? 999 : leftIndex) - (rightIndex < 0 ? 999 : rightIndex);
  });
}

function canMove(order, sectionKey, direction) {
  const index = order.indexOf(sectionKey);
  return index >= 0 && index + direction >= 0 && index + direction < order.length;
}

function clampEffect(value, definition) {
  const step = definition.step || 1;
  const min = definition.min ?? 0;
  const max = definition.max ?? 100;
  return Math.min(max, Math.max(min, Number(value) + step));
}

/**
 * Shared appearance and detail-layout editor. The caller owns the theme,
 * palette and layout values plus persistence; the component owns local
 * validation and the dirty/saving/error presentation.
 */
export function AppearanceEditor({
  presets = {},
  colors = {},
  effects = {},
  families = {},
  values = { theme: 'system', palette: {}, layouts: {} },
  initialValues,
  onChange,
  onSave,
  validate,
  labels,
  palette = {},
  buttonPalette = {},
  disabled = false,
}) {
  const copy = { ...defaultLabels, ...labels };
  const colors_ = { ...defaultPalette, ...palette };
  const [saving, setSaving] = useState(false);
  const [localErrors, setLocalErrors] = useState({});
  const [localError, setLocalError] = useState('');
  const serialized = useMemo(() => JSON.stringify(values), [values]);
  const baseline = initialValues || values;
  const dirty = useMemo(() => !sameValues(values, baseline), [values, baseline]);
  const familyKeys = Object.keys(families);
  const [selectedFamily, setSelectedFamily] = useState(familyKeys[0] || '');
  const activeFamily = familyKeys.includes(selectedFamily) ? selectedFamily : familyKeys[0];
  const theme = values.theme || 'system';
  const paletteValues = values.palette || {};
  const layouts = values.layouts || {};

  useEffect(() => {
    setLocalError('');
    setLocalErrors({});
  }, [serialized]);

  function update(next) {
    onChange?.(next);
  }

  function setTheme(nextTheme) {
    update({ ...values, theme: nextTheme });
  }

  function setPalette(key, nextColor) {
    update({ ...values, palette: { ...paletteValues, [key]: nextColor } });
  }

  function stepEffect(key, direction) {
    const definition = effects[key] || {};
    update({
      ...values,
      palette: { ...paletteValues, [key]: clampEffect(paletteValues[key] ?? definition.default ?? 0, definition) },
    });
  }

  function copyLayouts() {
    return Object.fromEntries(Object.entries(layouts).map(([familyKey, zones]) => [familyKey, { ...zones }]));
  }

  function toggleSection(familyKey, zoneKey, sectionKey) {
    const next = copyLayouts();
    const keys = enabledKeys(next, familyKey, zoneKey);
    next[familyKey] = next[familyKey] || {};
    next[familyKey][zoneKey] = keys.includes(sectionKey)
      ? keys.filter(key => key !== sectionKey)
      : [...keys, sectionKey];
    update({ ...values, layouts: next });
  }

  function moveSection(familyKey, zoneKey, sectionKey, direction) {
    const keys = enabledKeys(layouts, familyKey, zoneKey);
    if (!canMove(keys, sectionKey, direction)) return;
    const next = copyLayouts();
    const nextKeys = [...keys];
    const index = nextKeys.indexOf(sectionKey);
    [nextKeys[index], nextKeys[index + direction]] = [nextKeys[index + direction], nextKeys[index]];
    next[familyKey] = { ...(next[familyKey] || {}), [zoneKey]: nextKeys };
    update({ ...values, layouts: next });
  }

  function validateValues() {
    if (validate) return validate(values) || {};
    const problems = {};
    if (theme === 'custom') {
      Object.entries(colors).forEach(([key, definition]) => {
        const color = paletteValues[key] ?? definition.default;
        if (!hexColor.test(String(color || ''))) {
          problems[`color:${key}`] = `${definition.label || key}: ${copy.invalidColor}`;
        }
      });
      Object.entries(effects).forEach(([key, definition]) => {
        const value = Number(paletteValues[key] ?? definition.default ?? 0);
        if (!Number.isFinite(value) || value < (definition.min ?? 0) || value > (definition.max ?? 100)) {
          problems[`effect:${key}`] = `${definition.label || key} is out of range.`;
        }
      });
    }
    return problems;
  }

  async function save() {
    if (saving || disabled) return;
    const problems = validateValues();
    if (Object.keys(problems).length) {
      setLocalErrors(problems);
      setLocalError(copy.validationError);
      return;
    }
    setLocalErrors({});
    setLocalError('');
    setSaving(true);
    try {
      await onSave?.({ values });
    } catch (reason) {
      setLocalError(reason?.message || copy.saveError);
    } finally {
      setSaving(false);
    }
  }

  const themeOptions = Object.entries(presets);
  const colorEntries = Object.entries(colors);
  const effectEntries = Object.entries(effects);
  const family = activeFamily ? families[activeFamily] : null;
  const familyOptions = familyKeys.map(key => ({ value: key, label: families[key].label || key }));

  return <View style={styles.form}>
    <View style={styles.section}>
      <View style={styles.sectionHeading}>
        <Text role="heading" aria-level={3} style={[styles.sectionTitle, { color: colors_.text }]}>{copy.theme}</Text>
        <Text style={[styles.help, { color: colors_.textMuted }]}>{copy.themeHelp}</Text>
      </View>
      <View style={styles.themeGrid}>
        {themeOptions.map(([value, preset]) => {
          const selected = theme === value;
          return <Pressable
            key={value}
            accessibilityRole="radio"
            accessibilityLabel={preset.label || value}
            accessibilityState={{ checked: selected, disabled }}
            disabled={disabled}
            onPress={() => setTheme(value)}
            style={({ pressed }) => [styles.themeOption, {
              borderColor: selected ? colors_.accent : colors_.border,
              backgroundColor: colors_.background,
            }, pressed && !disabled && { backgroundColor: colors_.surfaceStrong }]}>
            <View style={[styles.swatch, { backgroundColor: presetSwatches[value] || colors_.accent }]} />
            <Text style={[styles.themeLabel, { color: colors_.text }]}>{preset.label || value}</Text>
            {selected ? <Text style={[styles.selectedMark, { color: colors_.accent }]}>✓</Text> : null}
          </Pressable>;
        })}
      </View>

      {theme === 'custom' ? <View style={[styles.panel, { borderColor: colors_.border, backgroundColor: colors_.surface }]}>
        <Text style={[styles.panelTitle, { color: colors_.text }]}>{copy.customPalette}</Text>
        <View style={styles.colorGrid}>
          {colorEntries.map(([key, definition]) => {
            const value = String(paletteValues[key] ?? definition.default ?? '');
            const invalid = Boolean(localErrors[`color:${key}`]);
            return <View key={key} style={[styles.colorField, { backgroundColor: colors_.background }]}>
              <Text style={[styles.label, { color: colors_.textSecondary }]}>{definition.label || key}</Text>
              <View style={styles.colorRow}>
                <View style={[styles.colorSwatch, { backgroundColor: hexColor.test(value) ? value : colors_.surfaceMuted, borderColor: colors_.border }]} />
                <TextInput
                  accessibilityLabel={`${definition.label || key} color`}
                  value={value}
                  editable={!disabled}
                  autoCapitalize="none"
                  autoCorrect={false}
                  onChangeText={next => setPalette(key, next)}
                  style={[styles.colorInput, {
                    borderColor: invalid ? colors_.danger : colors_.border,
                    backgroundColor: colors_.surface,
                    color: colors_.textSecondary,
                    opacity: disabled ? 0.5 : 1,
                  }]} />
              </View>
              {invalid ? <Text accessibilityRole="alert" style={[styles.help, { color: colors_.danger }]}>{localErrors[`color:${key}`]}</Text> : null}
            </View>;
          })}
        </View>
        <View style={styles.effectGrid}>
          {effectEntries.map(([key, definition]) => {
            const value = Number(paletteValues[key] ?? definition.default ?? 0);
            const invalid = Boolean(localErrors[`effect:${key}`]);
            return <View key={key} style={[styles.effectField, { backgroundColor: colors_.background }]}>
              <Text style={[styles.label, { color: colors_.textSecondary }]}>{definition.label || key}</Text>
              <View style={styles.effectRow}>
                <Pressable
                  accessibilityRole="button"
                  accessibilityLabel={`Decrease ${definition.label || key}`}
                  disabled={disabled || value <= (definition.min ?? 0)}
                  onPress={() => stepEffect(key, -1)}
                  style={({ pressed }) => [styles.stepButton, { borderColor: colors_.border }, pressed && { backgroundColor: colors_.surfaceStrong }]}>
                  <Text style={[styles.stepText, { color: colors_.text }]}>−</Text>
                </Pressable>
                <Text style={[styles.effectValue, { color: invalid ? colors_.danger : colors_.textMuted }]}>
                  {value}{definition.unit || ''}
                </Text>
                <Pressable
                  accessibilityRole="button"
                  accessibilityLabel={`Increase ${definition.label || key}`}
                  disabled={disabled || value >= (definition.max ?? 100)}
                  onPress={() => stepEffect(key, 1)}
                  style={({ pressed }) => [styles.stepButton, { borderColor: colors_.border }, pressed && { backgroundColor: colors_.surfaceStrong }]}>
                  <Text style={[styles.stepText, { color: colors_.text }]}>+</Text>
                </Pressable>
              </View>
            </View>;
          })}
        </View>
      </View> : null}
    </View>

    <View style={styles.section}>
      <View style={styles.sectionHeading}>
        <Text role="heading" aria-level={3} style={[styles.sectionTitle, { color: colors_.text }]}>{copy.detailPages}</Text>
        <Text style={[styles.help, { color: colors_.textMuted }]}>{copy.detailHelp}</Text>
      </View>
      {familyOptions.length ? <SelectField
        id="appearance-family"
        label={copy.pageType}
        options={familyOptions}
        value={activeFamily}
        disabled={disabled}
        palette={colors_}
        onChange={event => setSelectedFamily(event.target.value)}
      /> : null}
      {family ? Object.entries(family.zones || {}).map(([zoneKey, zone]) => {
        const order = enabledKeys(layouts, activeFamily, zoneKey);
        const sections = orderedSections(zone.sections || [], order);
        return <View key={zoneKey} style={[styles.zone, { borderColor: colors_.border, backgroundColor: colors_.surface }]}>
          <Text role="heading" aria-level={4} style={[styles.zoneTitle, { color: colors_.text }]}>{zone.label || zoneKey}</Text>
          {sections.map(section => {
            const enabled = order.includes(section.key);
            return <View key={section.key} style={styles.sectionRow}>
              <View style={styles.sectionToggle}>
                <ToggleChip
                  value={enabled}
                  label={section.label || section.key}
                  offLabel={copy.hidden}
                  onLabel={copy.shown}
                  disabled={disabled}
                  palette={colors_}
                  onChange={() => toggleSection(activeFamily, zoneKey, section.key)}
                />
              </View>
              <View style={styles.moveRow}>
                <Pressable
                  accessibilityRole="button"
                  accessibilityLabel={`${copy.moveUp}: ${section.label || section.key}`}
                  disabled={disabled || !enabled || !canMove(order, section.key, -1)}
                  onPress={() => moveSection(activeFamily, zoneKey, section.key, -1)}
                  style={({ pressed }) => [styles.moveButton, { borderColor: colors_.border }, pressed && { backgroundColor: colors_.surfaceStrong }]}>
                  <Text style={[styles.moveText, { color: colors_.textMuted }]}>↑</Text>
                </Pressable>
                <Pressable
                  accessibilityRole="button"
                  accessibilityLabel={`${copy.moveDown}: ${section.label || section.key}`}
                  disabled={disabled || !enabled || !canMove(order, section.key, 1)}
                  onPress={() => moveSection(activeFamily, zoneKey, section.key, 1)}
                  style={({ pressed }) => [styles.moveButton, { borderColor: colors_.border }, pressed && { backgroundColor: colors_.surfaceStrong }]}>
                  <Text style={[styles.moveText, { color: colors_.textMuted }]}>↓</Text>
                </Pressable>
              </View>
            </View>;
          })}
        </View>;
      }) : null}
    </View>

    <FormSaveBar
      dirty={dirty}
      saving={saving}
      disabled={disabled}
      error={localError}
      onSave={save}
      saveLabel={copy.save}
      labels={copy}
      palette={colors_}
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
  themeGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  themeOption: { flexGrow: 1, flexBasis: 140, flexDirection: 'row', alignItems: 'center', gap: 8, borderWidth: 1, borderRadius: 10, padding: 10 },
  swatch: { width: 18, height: 18, borderRadius: 5 },
  themeLabel: { flexShrink: 1, fontSize: 13, fontWeight: '600' },
  selectedMark: { fontSize: 13, fontWeight: '700' },
  panel: { gap: 14, borderWidth: 1, borderRadius: 10, padding: 12 },
  panelTitle: { fontSize: 14, fontWeight: '600' },
  colorGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: 10 },
  colorField: { flexGrow: 1, flexBasis: 150, gap: 6, borderRadius: 8, padding: 8 },
  label: { fontSize: 12, fontWeight: '600' },
  colorRow: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  colorSwatch: { width: 22, height: 22, borderRadius: 5, borderWidth: 1 },
  colorInput: { flex: 1, borderWidth: 1, borderRadius: 7, paddingHorizontal: 8, paddingVertical: 6, fontSize: 13 },
  effectGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: 10 },
  effectField: { flexGrow: 1, flexBasis: 150, gap: 6, borderRadius: 8, padding: 8 },
  effectRow: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  stepButton: { width: 30, height: 30, borderWidth: 1, borderRadius: 7, alignItems: 'center', justifyContent: 'center' },
  stepText: { fontSize: 16, fontWeight: '700' },
  effectValue: { flex: 1, textAlign: 'center', fontSize: 12 },
  zone: { gap: 10, borderWidth: 1, borderRadius: 10, padding: 12 },
  zoneTitle: { fontSize: 14, fontWeight: '600' },
  sectionRow: { gap: 8, borderRadius: 8, paddingVertical: 2 },
  sectionToggle: { minWidth: 0 },
  moveRow: { flexDirection: 'row', gap: 6, justifyContent: 'flex-end' },
  moveButton: { width: 32, height: 30, borderWidth: 1, borderRadius: 7, alignItems: 'center', justifyContent: 'center' },
  moveText: { fontSize: 14, fontWeight: '700' },
});
