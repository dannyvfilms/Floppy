import React from 'react';
import { Pressable, StyleSheet, Text, TextInput, View } from 'react-native';
import { Button } from './Button';
import { FormError, FormField, FormSelect, FormTextField } from './MediaCardFormControls';

const DEFAULT_PALETTE = {
  text: '#fafafa',
  textSecondary: '#d4d4d8',
  textMuted: '#a1a1aa',
  surface: '#27272a',
  surfaceStrong: '#3f3f46',
  surfaceMuted: '#52525b',
  border: '#3f3f46',
  accent: '#6366f1',
  accentStrong: '#4f46e5',
  accentContrast: '#ffffff',
  danger: '#f87171',
  success: '#34d399',
  radius: 10,
  radiusSmall: 6,
  overlay: 'rgba(9, 9, 11, 0.72)',
  focusStyle: {},
};

const DEFAULT_LABELS = {
  title: 'Custom Fields',
  manage: 'Manage custom fields',
  noFields: 'No custom fields for this media type yet.',
  groupName: 'Group name',
  fieldName: 'Field name',
  addGroup: 'Add group',
  addField: 'Add field',
  remove: 'Remove',
  moveUp: 'Move up',
  moveDown: 'Move down',
  type: 'Type',
  mediaTypes: 'Media types',
  options: 'Options',
  optionsHint: 'One option per line',
  save: 'Save Fields',
  saving: 'Saving…',
  discard: 'Discard',
  unsaved: 'Unsaved changes',
  ownerOnly: 'Only the collection owner can manage custom fields.',
  groupRequired: 'Every group needs a name.',
  fieldRequired: 'Every field needs a label.',
  mediaTypeRequired: 'needs at least one media type.',
  edit: 'Edit custom field values',
  done: 'Done',
  yes: 'Yes',
  select: 'Select',
  emptyOption: '-',
  required: 'This field is required.',
};

const FIELD_TYPE_LABELS = {
  text: 'Text',
  number: 'Number',
  date: 'Date',
  select: 'Select',
  checkbox: 'Checkbox',
};

function mergePalette(palette) {
  return { ...DEFAULT_PALETTE, ...(palette || {}) };
}

function mergeLabels(labels) {
  return { ...DEFAULT_LABELS, ...(labels || {}) };
}

function fieldKey(field) {
  return String(field.id ?? field.clientId ?? field.client_id ?? field.label);
}

function moveItem(items, index, delta) {
  const target = index + delta;
  if (target < 0 || target >= items.length) return items;
  const next = [...items];
  const [item] = next.splice(index, 1);
  next.splice(target, 0, item);
  return next;
}

function updateGroup(groups, index, patch) {
  return groups.map((group, position) => position === index ? { ...group, ...patch } : group);
}

function updateField(groups, groupIndex, fieldIndex, patch) {
  return groups.map((group, position) => {
    if (position !== groupIndex) return group;
    return {
      ...group,
      fields: group.fields.map((field, fieldPosition) =>
        fieldPosition === fieldIndex ? { ...field, ...patch } : field),
    };
  });
}

function ValueCheckbox({ field, value, editable, palette, onChange }) {
  return <FormField label={field.label} palette={palette}>
    <Pressable accessibilityRole="checkbox" accessibilityLabel={field.label}
      accessibilityState={{ checked: !!value, disabled: !editable }}
      disabled={!editable} onPress={() => onChange?.(!value)}
      style={({ pressed }) => [styles.checkboxRow, {
        borderColor: value ? palette.accent : palette.border,
        backgroundColor: value ? `${palette.accent}22` : palette.surfaceStrong,
        opacity: editable ? (pressed ? 0.7 : 1) : 0.6,
      }]}>
      <View style={[styles.checkboxBox, {
        borderColor: value ? palette.accent : palette.border,
        backgroundColor: value ? palette.accent : 'transparent',
      }]}>
        {value ? <Text style={[styles.checkboxCheck, { color: palette.accentContrast }]}>✓</Text> : null}
      </View>
      <Text style={[styles.checkboxLabel, { color: palette.textSecondary }]}>{value ? DEFAULT_LABELS.yes : 'No'}</Text>
    </Pressable>
  </FormField>;
}

export function CollectionFieldValueInputs({
  groups = [],
  values = {},
  errors = {},
  labels: suppliedLabels,
  palette: suppliedPalette,
  canEdit = false,
  onChange,
}) {
  const labels = mergeLabels(suppliedLabels);
  const palette = mergePalette(suppliedPalette);
  if (!groups.length) return <Text style={[styles.empty, { color: palette.textMuted }]}>{labels.noFields}</Text>;
  return <View style={styles.valueGroups}>
    {groups.map(group => <View key={group.id || group.name} style={styles.valueGroup}>
      <Text style={[styles.groupHeading, { color: palette.textMuted }]}>{group.name}</Text>
      <View style={styles.valueGrid}>
        {group.fields.map(field => {
          const key = String(field.id);
          const value = values[key];
          const fieldType = field.fieldType || field.field_type || 'text';
          if (fieldType === 'select') {
            return <FormSelect key={key} label={field.label}
              value={value ?? ''}
              options={[{ value: '', label: labels.emptyOption },
                ...(field.options || []).map(option => ({ value: option, label: option }))]}
              error={errors[key]} palette={palette}
              onChange={next => { if (canEdit) onChange?.(key, next); }} />;
          }
          if (fieldType === 'checkbox') {
            return <ValueCheckbox key={key} field={field} value={value} editable={canEdit}
              palette={palette} onChange={next => onChange?.(key, next)} />;
          }
          return <FormTextField key={key} label={field.label}
            value={value ?? ''}
            error={errors[key]}
            keyboardType={fieldType === 'number' ? 'decimal-pad' : 'default'}
            editable={canEdit} palette={palette}
            placeholder={fieldType === 'date' ? 'YYYY-MM-DD' : undefined}
            onChangeText={next => { if (canEdit) onChange?.(key, next); }} />;
        })}
      </View>
    </View>)}
  </View>;
}

function ManageField({ field, groupIndex, fieldIndex, fieldTypes, mediaTypes, palette, labels, onChange }) {
  const selectedTypes = field.mediaTypes || field.media_types || [];
  return <View style={[styles.manageField, { borderColor: palette.border }]}>
    <View style={styles.manageFieldHeader}>
      <View style={styles.manageFieldTitle}>
        <TextInput accessibilityLabel={labels.fieldName} value={field.label || ''}
          onChangeText={label => onChange(groupIndex, fieldIndex, { label })}
          placeholder={labels.fieldName} placeholderTextColor={palette.textMuted}
          selectionColor={palette.accent}
          style={[styles.inlineInput, { color: palette.text, borderColor: palette.border }]} />
      </View>
      <View style={styles.reorderRow}>
        <Pressable accessibilityRole="button" accessibilityLabel={labels.moveUp}
          onPress={() => onChange(groupIndex, fieldIndex, null, 'up')} style={styles.smallButton}>
          <Text style={[styles.smallGlyph, { color: palette.textSecondary }]}>↑</Text>
        </Pressable>
        <Pressable accessibilityRole="button" accessibilityLabel={labels.moveDown}
          onPress={() => onChange(groupIndex, fieldIndex, null, 'down')} style={styles.smallButton}>
          <Text style={[styles.smallGlyph, { color: palette.textSecondary }]}>↓</Text>
        </Pressable>
        <Pressable accessibilityRole="button" accessibilityLabel={labels.remove}
          onPress={() => onChange(groupIndex, fieldIndex, null, 'removeField')} style={styles.smallButton}>
          <Text style={[styles.smallGlyph, { color: palette.danger }]}>×</Text>
        </Pressable>
      </View>
    </View>
    <FormSelect label={labels.type} value={field.fieldType || field.field_type || 'text'}
      options={fieldTypes} palette={palette}
      onChange={value => onChange(groupIndex, fieldIndex, { fieldType: value })} />
    <FormField label={labels.mediaTypes} palette={palette}>
      <View style={styles.chipWrap}>
        {mediaTypes.map(option => {
          const selected = selectedTypes.includes(option.value);
          return <Pressable key={option.value} accessibilityRole="checkbox"
            accessibilityLabel={option.label} accessibilityState={{ checked: selected }} aria-checked={selected}
            onPress={() => onChange(groupIndex, fieldIndex, {
              mediaTypes: selected
                ? selectedTypes.filter(value => value !== option.value)
                : [...selectedTypes, option.value],
            })}
            style={({ pressed }) => [styles.mediaChip, {
              backgroundColor: selected ? `${palette.accent}33` : palette.surfaceStrong,
              borderColor: selected ? palette.accent : palette.border,
              opacity: pressed ? 0.7 : 1,
            }]}>
            <Text style={[styles.mediaChipText, { color: selected ? palette.text : palette.textMuted }]}>
              {option.label}
            </Text>
          </Pressable>;
        })}
      </View>
    </FormField>
    {(field.fieldType || field.field_type) === 'select' ? <FormTextField
      label={labels.options}
      value={field.optionsText ?? (field.options || []).join('\n')}
      help={labels.optionsHint} palette={palette}
      onChangeText={value => onChange(groupIndex, fieldIndex, { optionsText: value })} /> : null}
  </View>;
}

export function CollectionFieldManager({
  groups = [],
  fieldTypes = [],
  mediaTypes = [],
  labels: suppliedLabels,
  palette: suppliedPalette,
  canManage = false,
  dirty = false,
  saving = false,
  error = '',
  onChange,
  onSave,
  onReset,
}) {
  const labels = mergeLabels(suppliedLabels);
  const palette = mergePalette(suppliedPalette);
  if (!canManage) return <Text style={[styles.readOnly, { color: palette.textMuted, borderColor: palette.border }]}>
    {labels.ownerOnly}
  </Text>;

  function changeGroup(groupIndex, patch) {
    onChange?.(updateGroup(groups, groupIndex, patch));
  }

  function changeField(groupIndex, fieldIndex, patch, operation) {
    if (operation === 'removeField') {
      onChange?.(updateGroup(groups, groupIndex, {
        fields: groups[groupIndex].fields.filter((field, index) => index !== fieldIndex),
      }));
      return;
    }
    if (operation === 'up' || operation === 'down') {
      onChange?.(updateGroup(groups, groupIndex, {
        fields: moveItem(groups[groupIndex].fields, fieldIndex, operation === 'up' ? -1 : 1),
      }));
      return;
    }
    onChange?.(updateField(groups, groupIndex, fieldIndex, patch));
  }

  function removeGroup(index) {
    onChange?.(groups.filter((group, position) => position !== index));
  }

  function moveGroup(index, delta) {
    onChange?.(moveItem(groups, index, delta));
  }

  function addGroup() {
    onChange?.([...groups, {
      clientId: `group-${groups.length + 1}-${Date.now()}`,
      id: null,
      name: '',
      fields: [],
    }]);
  }

  function addField(index) {
    const group = groups[index];
    onChange?.(updateGroup(groups, index, {
      fields: [...group.fields, {
        clientId: `field-${group.fields.length + 1}-${Date.now()}`,
        id: null,
        label: '',
        fieldType: 'text',
        mediaTypes: [],
        optionsText: '',
      }],
    }));
  }

  return <View style={styles.manager}>
    <View style={styles.managerHeader}>
      <Text style={[styles.sectionTitle, { color: palette.textMuted }]}>{labels.title}</Text>
      {dirty ? <Text style={[styles.unsaved, { color: palette.warning || palette.textMuted }]}>{labels.unsaved}</Text> : null}
    </View>

    {groups.map((group, groupIndex) => <View key={group.clientId || group.id || group.name}
      style={[styles.manageGroup, { borderColor: palette.border, backgroundColor: palette.surfaceStrong }]}>
      <View style={styles.manageGroupHeader}>
        <TextInput accessibilityLabel={labels.groupName} value={group.name || ''}
          onChangeText={name => changeGroup(groupIndex, { name })}
          placeholder={labels.groupName} placeholderTextColor={palette.textMuted}
          selectionColor={palette.accent}
          style={[styles.inlineInput, styles.groupInput, { color: palette.text, borderColor: palette.border }]} />
        <View style={styles.reorderRow}>
          <Pressable accessibilityRole="button" accessibilityLabel={`${labels.moveUp} group`}
            onPress={() => moveGroup(groupIndex, -1)} style={styles.smallButton}>
            <Text style={[styles.smallGlyph, { color: palette.textSecondary }]}>↑</Text>
          </Pressable>
          <Pressable accessibilityRole="button" accessibilityLabel={`${labels.moveDown} group`}
            onPress={() => moveGroup(groupIndex, 1)} style={styles.smallButton}>
            <Text style={[styles.smallGlyph, { color: palette.textSecondary }]}>↓</Text>
          </Pressable>
          <Pressable accessibilityRole="button" accessibilityLabel={`${labels.remove} ${group.name || labels.groupName}`}
            onPress={() => removeGroup(groupIndex)} style={styles.smallButton}>
            <Text style={[styles.smallGlyph, { color: palette.danger }]}>×</Text>
          </Pressable>
        </View>
      </View>

      {group.fields.map((field, fieldIndex) => <ManageField key={field.clientId || field.id || field.label}
        field={field} groupIndex={groupIndex} fieldIndex={fieldIndex}
        fieldTypes={fieldTypes.length ? fieldTypes : Object.entries(FIELD_TYPE_LABELS)
          .map(([value, label]) => ({ value, label }))}
        mediaTypes={mediaTypes} palette={palette} labels={labels} onChange={changeField} />)}

      <Button label={labels.addField} tone="surface" palette={palette}
        onPress={() => addField(groupIndex)} />
    </View>)}

    <Button label={labels.addGroup} tone="surface" palette={palette} onPress={addGroup} />
    <FormError message={error} palette={palette} />
    <View style={styles.managerFooter}>
      {dirty ? <Button label={labels.discard} tone="surface" palette={palette} onPress={onReset} /> : null}
      <Button label={saving ? labels.saving : labels.save} palette={palette}
        busy={saving} disabled={saving} onPress={onSave} />
    </View>
  </View>;
}

const styles = StyleSheet.create({
  valueGroups: { gap: 14 },
  valueGroup: { gap: 8 },
  groupHeading: { fontSize: 11, fontWeight: '700', letterSpacing: 0.6, textTransform: 'uppercase' },
  valueGrid: { gap: 14 },
  empty: { fontSize: 12, lineHeight: 17 },
  checkboxRow: { flexDirection: 'row', alignItems: 'center', gap: 10, borderWidth: 1, borderRadius: 8, minHeight: 44, paddingHorizontal: 10 },
  checkboxBox: { width: 18, height: 18, borderWidth: 1, borderRadius: 4, alignItems: 'center', justifyContent: 'center' },
  checkboxCheck: { fontSize: 12, fontWeight: '700' },
  checkboxLabel: { fontSize: 13, fontWeight: '600' },
  manager: { gap: 12 },
  managerHeader: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 8 },
  sectionTitle: { fontSize: 11, fontWeight: '700', letterSpacing: 0.6, textTransform: 'uppercase' },
  unsaved: { fontSize: 11, fontWeight: '600' },
  manageGroup: { borderWidth: 1, borderRadius: 10, padding: 10, gap: 12 },
  manageGroupHeader: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  manageField: { borderWidth: 1, borderRadius: 8, padding: 10, gap: 12 },
  manageFieldHeader: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  manageFieldTitle: { flex: 1, minWidth: 0 },
  inlineInput: { minHeight: 40, borderWidth: 1, borderRadius: 6, paddingHorizontal: 8, fontSize: 13 },
  groupInput: { flex: 1, fontWeight: '700' },
  reorderRow: { flexDirection: 'row', gap: 2 },
  smallButton: { width: 32, height: 32, alignItems: 'center', justifyContent: 'center' },
  smallGlyph: { fontSize: 16, fontWeight: '700' },
  chipWrap: { flexDirection: 'row', flexWrap: 'wrap', gap: 6 },
  mediaChip: { borderWidth: 1, borderRadius: 9999, paddingHorizontal: 10, paddingVertical: 6 },
  mediaChipText: { fontSize: 11, fontWeight: '600' },
  readOnly: { borderWidth: 1, borderRadius: 8, padding: 10, fontSize: 12, lineHeight: 17 },
  managerFooter: { flexDirection: 'row', justifyContent: 'flex-end', gap: 8 },
});
