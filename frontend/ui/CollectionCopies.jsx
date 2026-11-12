import { Modal } from './Modal';
import React from 'react';
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { Badge } from './Badge';
import { actionIcons } from './actionIcons';
import { Button } from './Button';
import { Icon } from './Icon';
import { DateTimePicker } from './DateTimePicker';
import { SelectField } from './SelectField';
import { FormError, FormField, FormHeader, FormSelect, FormTextField } from './MediaCardFormControls';

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
  warning: '#fbbf24',
  radius: 10,
  radiusSmall: 6,
  overlay: 'rgba(9, 9, 11, 0.72)',
  focusStyle: {},
};

const DEFAULT_LABELS = {
  title: 'Collection Entry',
  existing: 'Existing Entries',
  addCopy: 'Add Copy',
  yes: 'Yes',
  addAnother: 'Add Another Copy',
  editCopy: 'Edit Copy',
  save: 'Save',
  cancel: 'Cancel',
  remove: 'Remove',
  edit: 'Edit',
  collected: 'Collected',
  noCopies: 'No owned copies recorded.',
  format: 'Format',
  empty: 'No copies yet.',
  completeness: 'Completeness',
  partial: 'Partial',
  full: 'Full',
  copyLabel: 'Copy',
  seasonScope: 'Apply collection to',
  thisItem: 'This item only',
  season: 'A season',
  episodes: 'Every episode',
  seasonNumber: 'Season',
  cascade: 'Saving creates one copy for every episode in the selected scope.',
  cascadeItem: 'Saving adds a copy for this item only.',
  cascadeSeason: 'Saving adds one copy for every episode in this season.',
  cascadeEpisodes: 'Saving adds one copy for every episode in the show.',
  required: 'This field is required.',
  invalidNumber: 'Enter a number.',
  minimum: 'Must be at least zero.',
  ownerOnly: 'Only the collection owner can edit copies.',
  close: 'Close',
  saved: 'Copy saved.',
};

function mergePalette(palette) {
  return { ...DEFAULT_PALETTE, ...(palette || {}) };
}

function mergeLabels(labels) {
  return { ...DEFAULT_LABELS, ...(labels || {}) };
}

function qualityLine(copy) {
  return [copy.mediaType, copy.resolution, copy.hdr, copy.audioCodec, copy.audioChannels]
    .filter(Boolean).join(' · ');
}

function CopyRow({ copy, labels, palette, canMutate, onEdit, onRemove }) {
  const detail = qualityLine(copy);
  return <View style={[styles.copyRow, { borderColor: palette.border, backgroundColor: palette.surfaceStrong }]}>
    <View style={styles.copyBody}>
      <View style={styles.copyTitleRow}>
        <Text style={[styles.copyTitle, { color: palette.text }]}>{copy.label || labels.copyLabel}</Text>
        {copy.completeness?.isPartial ? <Badge
          label={`${copy.completeness.collected}/${copy.completeness.total} · ${labels.partial}`}
          size="xs" nowrap palette={{
            outline: { color: palette.warning, borderColor: palette.border, borderWidth: 1 },
          }} /> : null}
      </View>
      {detail ? <Text style={[styles.copyDetail, { color: palette.textSecondary }]}>{detail}</Text> : null}
      {copy.customSummary ? <Text style={[styles.copyMeta, { color: palette.textMuted }]}>{copy.customSummary}</Text> : null}
      {copy.purchasePrice || copy.purchaseLocation ? <Text style={[styles.copyMeta, { color: palette.textMuted }]}>
        {[copy.purchasePrice, copy.purchaseLocation].filter(Boolean).join(' · ')}
      </Text> : null}
      {copy.collectedAt ? <Text style={[styles.copyMeta, { color: palette.textMuted }]}>
        {labels.collected}: {copy.collectedAtLabel || copy.collectedAt}
      </Text> : null}
    </View>
    {canMutate ? <View style={styles.copyActions}>
      {onEdit ? <Pressable accessibilityRole="button" accessibilityLabel={`${labels.edit} ${copy.label || labels.copyLabel}`}
        onPress={() => onEdit(copy)} style={styles.iconButton}>
        <Icon spec={actionIcons.edit} color={palette.accent} size={16} style={[styles.iconText, { color: palette.accent }]}>{'✎'}</Icon>
      </Pressable> : null}
      {onRemove ? <Pressable accessibilityRole="button" accessibilityLabel={`${labels.remove} ${copy.label || labels.copyLabel}`}
        onPress={() => onRemove(copy)} style={styles.iconButton}>
        <Icon spec={actionIcons.trash} color={palette.danger} size={16} style={[styles.iconText, { color: palette.danger }]}>{'⌫'}</Icon>
      </Pressable> : null}
    </View> : null}
  </View>;
}

export function CollectionCopySummary({ copies = [], labels: suppliedLabels, palette: suppliedPalette, canMutate = false, onEdit, onRemove }) {
  const labels = mergeLabels(suppliedLabels);
  const palette = mergePalette(suppliedPalette);
  if (!copies.length) return <Text style={[styles.emptyCopy, { color: palette.textMuted }]}>{labels.noCopies}</Text>;
  return <View style={styles.copyList}>
    {copies.map(copy => <CopyRow key={copy.id} copy={copy} labels={labels} palette={palette}
      canMutate={canMutate} onEdit={onEdit} onRemove={onRemove} />)}
  </View>;
}

function CheckboxField({ label, value, onChange, palette, editable, help, yes = 'Yes' }) {
  return <FormField label={label} palette={palette}>
    <Pressable accessibilityRole="checkbox" accessibilityLabel={label}
      accessibilityState={{ checked: !!value, disabled: !editable }}
      disabled={!editable} onPress={() => onChange?.(!value)}
      style={({ pressed }) => [styles.checkboxRow, {
        borderColor: value ? palette.accent : palette.border,
        backgroundColor: value ? `${palette.accent}22` : palette.surfaceStrong,
        opacity: editable ? (pressed ? 0.7 : 1) : 0.6,
      }]}>
      <View style={[styles.checkboxBox, { borderColor: value ? palette.accent : palette.border, backgroundColor: value ? palette.accent : 'transparent' }]}>
        {value ? <Text style={[styles.checkboxCheck, { color: palette.accentContrast }]}>✓</Text> : null}
      </View>
      <Text style={[styles.checkboxLabel, { color: palette.textSecondary }]}>{yes}</Text>
    </Pressable>
    {help ? <Text style={[styles.help, { color: palette.textMuted }]}>{help}</Text> : null}
  </FormField>;
}

function MediumFields({ fields = [], values, errors, labels, palette, canMutate, onChange, popover }) {
  return <View style={styles.fieldsGrid}>
    {fields.map(field => {
      if (field.type === 'select') {
        return <View key={field.name} style={styles.fieldCell}>
          <FormField label={field.label} required={field.required} error={errors[field.name]}
            palette={palette}>
            <SelectField labelHidden filter popover={popover} multiple={field.multiple} label={field.label} value={values[field.name] ?? ''}
              options={field.options || []} palette={palette} disabled={!canMutate}
              onChange={event => onChange?.(field.name, event.target.value)} />
          </FormField>
        </View>;
      }
      if (field.type === 'checkbox') {
        return <View key={field.name} style={styles.fieldCell}>
          <CheckboxField label={field.label} value={!!values[field.name]}
            palette={palette} editable={canMutate} yes={labels.yes}
            onChange={value => onChange?.(field.name, value)} />
        </View>;
      }
      if (field.type === 'datetime') {
        return <View key={field.name} style={styles.fieldCell}>
          <FormField label={field.label} error={errors[field.name]} palette={palette}>
            <DateTimePicker value={values[field.name] ?? ''} trackTime
              onChange={value => onChange?.(field.name, value)} palette={palette} />
          </FormField>
        </View>;
      }
      return <View key={field.name} style={styles.fieldCell}>
        <FormTextField label={field.label}
          value={values[field.name] ?? ''} required={field.required}
          error={errors[field.name]} placeholder={field.placeholder}
          keyboardType={field.type === 'number' ? 'decimal-pad' : 'default'}
          editable={canMutate} palette={palette}
          onChangeText={value => onChange?.(field.name, value)} />
      </View>;
    })}
  </View>;
}

export function CollectionCopyEditor({
  fields = [],
  values = {},
  errors = {},
  labels: suppliedLabels,
  palette: suppliedPalette,
  canMutate = false,
  onChange,
  popover = false,
  children,
}) {
  const labels = mergeLabels(suppliedLabels);
  const palette = mergePalette(suppliedPalette);
  if (!canMutate) return <Text style={[styles.readOnly, { color: palette.textMuted, borderColor: palette.border }]}>
    {labels.ownerOnly}
  </Text>;
  return <View style={styles.editor}>
    <MediumFields fields={fields} values={values} errors={errors} labels={labels}
      palette={palette} canMutate={canMutate} onChange={onChange} popover={popover} />
    {children}
  </View>;
}

export function CollectionSeasonCascade({
  scope = 'item',
  seasons = [],
  selectedSeason,
  labels: suppliedLabels,
  palette: suppliedPalette,
  canMutate = false,
  onScopeChange,
  onSeasonChange,
}) {
  const labels = mergeLabels(suppliedLabels);
  const palette = mergePalette(suppliedPalette);
  if (!seasons.length) return null;
  const scopeOptions = [
    { value: 'item', label: labels.thisItem },
    { value: 'season', label: labels.season },
    { value: 'episodes', label: labels.episodes },
  ];
  const seasonOptions = seasons.map(season => ({
    value: String(season.number),
    label: season.label || `Season ${season.number}`,
  }));
  const note = scope === 'season' ? labels.cascadeSeason
    : scope === 'episodes' ? labels.cascadeEpisodes
      : labels.cascadeItem;
  return <View style={[styles.cascade, { borderColor: palette.border, backgroundColor: palette.surfaceStrong }]}>
    <FormSelect label={labels.seasonScope} value={scope} options={scopeOptions}
      palette={palette} onChange={value => onScopeChange?.(value)} />
    {scope === 'season' ? <FormSelect label={labels.seasonNumber}
      value={String(selectedSeason ?? seasonOptions[0]?.value ?? '')}
      options={seasonOptions} palette={palette}
      onChange={value => onSeasonChange?.(value)} /> : null}
    <Text style={[styles.cascadeNote, { color: palette.textMuted }]}>{note}</Text>
  </View>;
}

export function CollectionCopyDialog({
  visible = false,
  embedded = false,
  item,
  copies = [],
  fields = [],
  values = {},
  errors = {},
  labels: suppliedLabels,
  palette: suppliedPalette,
  canMutate = false,
  scope = 'item',
  seasons = [],
  selectedSeason,
  editingId = null,
  busy = false,
  saveNote = '',
  onClose,
  onChange,
  onScopeChange,
  onSeasonChange,
  onSave,
  onEdit,
  onRemove,
  children,
}) {
  const labels = mergeLabels(suppliedLabels);
  const palette = mergePalette(suppliedPalette);
  if (!item) return null;
  const completeness = item.completeness;
  const content = <>
        <ScrollView style={styles.dialogScroll} contentContainerStyle={styles.dialogContent}
          keyboardShouldPersistTaps="handled">
          <View style={styles.itemHeader}>
            <Text style={[styles.itemTitle, { color: palette.text }]}>{item.title}</Text>
            <Text style={[styles.itemMeta, { color: palette.textSecondary }]}>
              {[item.mediaTypeLabel || item.mediaType, item.format, item.resolution].filter(Boolean).join(' · ')}
            </Text>
            {completeness?.total ? <View style={styles.badgeRow}>
              <Badge label={completeness.isPartial
                ? `${completeness.collected}/${completeness.total} · ${labels.partial}`
                : `${completeness.total}/${completeness.total} · ${labels.full}`}
                size="sm" nowrap palette={{
                  outline: { color: completeness.isPartial ? palette.warning : palette.success, borderColor: palette.border, borderWidth: 1 },
                }} />
            </View> : null}
          </View>

          <Text style={[styles.sectionTitle, { color: palette.textMuted }]}>
            {labels.existing}
          </Text>
          <CollectionCopySummary copies={copies} labels={labels} palette={palette}
            canMutate={canMutate} onEdit={onEdit} onRemove={onRemove} />

          <Text style={[styles.sectionTitle, { color: palette.textMuted }]}>
            {editingId ? labels.editCopy : copies.length ? labels.addAnother : labels.addCopy}
          </Text>
          <CollectionCopyEditor fields={fields} values={values} errors={errors}
            labels={labels} palette={palette} canMutate={canMutate} onChange={onChange} popover={embedded} />
          {canMutate ? <CollectionSeasonCascade scope={scope} seasons={seasons} selectedSeason={selectedSeason}
            labels={labels} palette={palette} canMutate={canMutate}
            onScopeChange={onScopeChange} onSeasonChange={onSeasonChange} /> : null}
          {children}

          <FormError message={errors.form} palette={palette} />
          {saveNote ? <Text accessibilityLiveRegion="polite" style={[styles.saveNote, { color: palette.success }]}>
            {saveNote}
          </Text> : null}
        </ScrollView>
        <View style={[styles.dialogFooter, { borderColor: palette.border }]}>
          <Button label={labels.cancel} tone="surface" palette={palette} onPress={onClose} />
          {canMutate ? <Button label={editingId ? labels.save : labels.addCopy}
            palette={palette} busy={busy} disabled={busy} onPress={onSave} /> : null}
        </View>
  </>;
  if (embedded) return <View style={styles.embedded}>{content}</View>;
  return <Modal visible={visible} transparent animationType="fade" onRequestClose={onClose}>
    <View style={[styles.overlay, { backgroundColor: palette.overlay }]}>
      <Pressable accessibilityRole="button" accessibilityLabel={labels.close}
        style={StyleSheet.absoluteFill} onPress={onClose} />
      <View style={[styles.dialog, { backgroundColor: palette.surface, borderColor: palette.border }]}>
        <FormHeader title={labels.title} closeLabel={labels.close} onClose={onClose} palette={palette} />
        {content}
      </View>
    </View>
  </Modal>;
}

const styles = StyleSheet.create({
  copyList: { gap: 8 },
  copyRow: { flexDirection: 'row', alignItems: 'flex-start', gap: 8, borderWidth: 1, borderRadius: 10, padding: 10 },
  copyBody: { flex: 1, minWidth: 0, gap: 3 },
  copyTitleRow: { flexDirection: 'row', alignItems: 'center', flexWrap: 'wrap', gap: 6 },
  copyTitle: { fontSize: 13, fontWeight: '700' },
  copyDetail: { fontSize: 12, lineHeight: 17 },
  copyMeta: { fontSize: 11, lineHeight: 16 },
  copyActions: { flexDirection: 'row', gap: 2 },
  iconButton: { width: 32, height: 32, alignItems: 'center', justifyContent: 'center' },
  iconText: { fontSize: 17 },
  emptyCopy: { fontSize: 12, paddingVertical: 4 },
  editor: { gap: 14 },
  fieldsGrid: { flexDirection: 'row', flexWrap: 'wrap', columnGap: 16, rowGap: 16 },
  fieldCell: { flexGrow: 1, flexBasis: 240, minWidth: 0 },
  checkboxRow: { flexDirection: 'row', alignItems: 'center', gap: 10, borderWidth: 1, borderRadius: 8, minHeight: 44, paddingHorizontal: 10 },
  checkboxBox: { width: 18, height: 18, borderWidth: 1, borderRadius: 4, alignItems: 'center', justifyContent: 'center' },
  checkboxCheck: { fontSize: 12, fontWeight: '700' },
  checkboxLabel: { fontSize: 13, fontWeight: '600' },
  help: { fontSize: 12, lineHeight: 17 },
  readOnly: { borderWidth: 1, borderRadius: 8, padding: 10, fontSize: 12, lineHeight: 17 },
  cascade: { borderWidth: 1, borderRadius: 10, padding: 12, gap: 12 },
  cascadeNote: { fontSize: 12, lineHeight: 17 },
  overlay: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 16 },
  dialog: { width: '100%', maxWidth: 620, maxHeight: '88%', borderWidth: 1, borderRadius: 14, padding: 16 },
  embedded: { flex: 1, paddingHorizontal: 16 },
  dialogScroll: { flexGrow: 0 },
  dialogContent: { gap: 16, paddingBottom: 8 },
  itemHeader: { gap: 4 },
  itemTitle: { fontSize: 18, fontWeight: '700' },
  itemMeta: { fontSize: 12 },
  badgeRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 6, marginTop: 2 },
  sectionTitle: { fontSize: 11, fontWeight: '700', letterSpacing: 0.6, textTransform: 'uppercase' },
  saveNote: { fontSize: 12, fontWeight: '600' },
  dialogFooter: { flexDirection: 'row', justifyContent: 'flex-end', gap: 8, borderTopWidth: 1, paddingTop: 12, marginTop: 8 },
});
