import React, { useState } from 'react';
import { Pressable, StyleSheet, Text, TextInput, View } from 'react-native';
import { CollectionGroup, CollectionRow, CollectionTextRow, separatorStyle } from './CollectionCopies';
import { Icon } from './Icon';
import { actionIcons } from './actionIcons';
import { NumberStepper } from './NumberPickerRow';
import { RatingSheet } from './RatingSheet';
import { ReorderList } from './ReorderList';
import { systemFillColor } from './separatorColor';
import {
  MAX_CRITERIA, MAX_TIERS, addCriterion, addTier, formatScore, groupByTier, moveInTier, moveToTier,
  removeCriterion, updateCriterion, validateDraft,
} from './ratingScaleModel';

const DEFAULT_LABELS = {
  newTitle: 'Create Rating Scale',
  editTitle: 'Edit Rating Scale',
  subtitle: 'Each criterion has its own range. Higher weights count more.',
  name: 'Name',
  namePlaceholder: 'Anime, Movies, Games',
  criterionName: 'Criterion name',
  range: 'Range',
  to: 'to',
  weight: 'Weight',
  addCriterion: 'Add Criterion',
  addTier: 'Add Weight Tier',
  moveUp: 'Move to lower weight',
  moveDown: 'Move to higher weight',
  remove: 'Remove criterion',
  save: 'Save',
  saving: 'Saving',
  cancel: 'Cancel',
  close: 'Close',
  delete: 'Delete Rating Scale',
  deleteHint: 'Ratings already saved with this scale keep their scores.',
};

// Creates or edits a named rating scale. Criteria sit in weight tiers (Weight 1, Weight 2, ...): the tier a
// criterion is in is its weight, so there is no weight field. Drag a handle to reorder inside a tier, or use the
// arrows to move a criterion to the next tier. Minimum and maximum use the date picker's number controls.
// Props only: the adapter owns the draft, saving and deleting.
export function RatingScaleEditor({
  open, draft, onChange, onSave, onClose, onDelete, busy = false, error = '', palette,
  labels: suppliedLabels, renderWheel,
}) {
  const labels = { ...DEFAULT_LABELS, ...suppliedLabels };
  const [picker, setPicker] = useState(null);
  const [checked, setChecked] = useState(false);
  if (!draft) return null;
  const errors = checked ? validateDraft(draft) : {};
  const tiers = groupByTier(draft.criteria, draft.tiers);
  const fill = systemFillColor() || palette.surfaceStrong;
  const edit = (id, changes) => onChange(updateCriterion(draft, id, changes));

  function save() {
    setChecked(true);
    if (Object.keys(validateDraft(draft)).length) return;
    onSave(draft);
  }

  const pill = (criterion, which) => {
    const open = picker && picker.id === criterion.id && picker.which === which;
    return <Pressable accessibilityRole="button" accessibilityState={{ expanded: Boolean(open) }}
      accessibilityLabel={`${criterion.name || labels.criterionName} ${which === 'min' ? 'minimum' : 'maximum'}: ${formatScore(criterion[which])}`}
      onPress={() => setPicker(open ? null : { id: criterion.id, which })}
      style={({ pressed }) => [styles.pill, { backgroundColor: fill, opacity: pressed ? 0.72 : 1,
        borderColor: open ? palette.accent : 'transparent' }]}>
      <Text style={[styles.pillText, { color: palette.text }]}>{formatScore(criterion[which])}</Text>
    </Pressable>;
  };

  const arrow = (criterion, direction, label) => {
    const target = criterion.weight + direction;
    if (target < 1 || target > draft.tiers) return null;
    return <Pressable key={direction} accessibilityRole="button" accessibilityLabel={`${label}: ${criterion.name || labels.criterionName}`}
      hitSlop={6} onPress={() => onChange(moveToTier(draft, criterion.id, target))} style={styles.iconButton}>
      <View style={direction < 0 ? { transform: [{ rotate: '180deg' }] } : undefined}>
        <Icon spec={actionIcons.chevronDown} color={palette.textMuted} size={18} />
      </View>
    </Pressable>;
  };

  const criterionBlock = (criterion, handle) => {
    const active = picker && picker.id === criterion.id ? picker.which : null;
    const message = errors[criterion.id];
    return <View key={criterion.id}>
      <View style={styles.nameRow}>
        {handle}
        <TextInput accessibilityLabel={labels.criterionName} value={criterion.name}
          placeholder={labels.criterionName} placeholderTextColor={palette.textMuted} selectionColor={palette.accent}
          onChangeText={name => edit(criterion.id, { name })}
          style={[styles.nameInput, { color: palette.text }]} />
        {draft.tiers > 1 ? <>{arrow(criterion, -1, labels.moveUp)}{arrow(criterion, 1, labels.moveDown)}</> : null}
        {draft.criteria.length > 1 ? <Pressable accessibilityRole="button" hitSlop={6}
          accessibilityLabel={`${labels.remove}: ${criterion.name || labels.criterionName}`}
          onPress={() => onChange(removeCriterion(draft, criterion.id))} style={styles.iconButton}>
          <Icon spec={actionIcons.trash} color={palette.textMuted} size={18} />
        </Pressable> : null}
      </View>
      <View style={styles.rangeRow}>
        <Text style={[styles.rangeLabel, { color: palette.textMuted }]}>{labels.range}</Text>
        {pill(criterion, 'min')}
        <Text style={[styles.rangeLabel, { color: palette.textMuted }]}>{labels.to}</Text>
        {pill(criterion, 'max')}
      </View>
      {active ? <View style={styles.panel}>
        {renderWheel ? renderWheel({
          value: Number(criterion[active]), min: -1000, max: 1000, step: 1, label: `${criterion.name} ${active}`, palette,
          onChange: next => edit(criterion.id, { [active]: Number(next) }),
        }) : <NumberStepper value={criterion[active]} min={-1000} max={1000} step={1}
          label={`${criterion.name || labels.criterionName} ${active === 'min' ? 'minimum' : 'maximum'}`} palette={palette}
          onChange={next => edit(criterion.id, { [active]: next === '' ? '' : Number(next) })} />}
      </View> : null}
      {message ? <Text accessibilityLiveRegion="polite" style={[styles.error, { color: palette.danger }]}>{message}</Text> : null}
    </View>;
  };

  return <RatingSheet open={open} palette={palette} onClose={onClose} closeLabel={labels.close}
    title={draft.id ? labels.editTitle : labels.newTitle} subtitle={labels.subtitle}
    primaryLabel={busy ? labels.saving : labels.save} onPrimary={save} primaryBusy={busy} cancelLabel={labels.cancel}
    danger={draft.id && onDelete ? <View style={styles.deleteBlock}>
      <CollectionGroup palette={palette}>
        <CollectionRow key="delete" label={labels.delete} tone="danger" palette={palette} onPress={busy ? undefined : onDelete} />
      </CollectionGroup>
      <Text style={[styles.hint, { color: palette.textMuted }]}>{labels.deleteHint}</Text>
    </View> : null}>
    <CollectionGroup palette={palette}>
      <CollectionTextRow key="name" label={labels.name} value={draft.name} placeholder={labels.namePlaceholder}
        error={errors.name} palette={palette} onChangeText={name => onChange({ ...draft, name })} />
    </CollectionGroup>
    {error ? <Text accessibilityRole="alert" style={[styles.error, { color: palette.danger, paddingHorizontal: 0 }]}>{error}</Text> : null}
    {errors.criteria ? <Text accessibilityLiveRegion="polite" style={[styles.error, { color: palette.danger, paddingHorizontal: 0 }]}>{errors.criteria}</Text> : null}
    {tiers.map(tier => <CollectionGroup key={tier.weight} palette={palette} title={`${labels.weight} ${tier.weight}`}>
      {tier.items.length ? <View key="items">
        <ReorderList items={tier.items} keyForItem={item => item.id} labelForItem={item => item.name || labels.criterionName}
          icon={actionIcons.grip} palette={palette} gap={0}
          onMove={(from, to) => onChange(moveInTier(draft, tier.weight, from, to))}
          renderItem={(item, index, handle) => <View>
            {index ? <View style={separatorStyle(palette)} /> : null}
            {criterionBlock(item, handle)}
          </View>} />
      </View> : null}
      {draft.criteria.length < MAX_CRITERIA ? <CollectionRow key="add" icon={actionIcons.plus} tone="accent"
        label={labels.addCriterion} palette={palette}
        onPress={() => onChange(addCriterion(draft, tier.weight))} /> : null}
    </CollectionGroup>)}
    {draft.tiers < MAX_TIERS ? <CollectionGroup palette={palette}>
      <CollectionRow key="tier" icon={actionIcons.plus} tone="accent" label={labels.addTier} palette={palette}
        onPress={() => onChange(addTier(draft))} />
    </CollectionGroup> : null}
  </RatingSheet>;
}

const styles = StyleSheet.create({
  nameRow: { flexDirection: 'row', alignItems: 'center', gap: 10, minHeight: 50, paddingTop: 4 },
  nameInput: { flex: 1, minWidth: 80, fontSize: 17, paddingVertical: 8 },
  iconButton: { width: 28, height: 28, alignItems: 'center', justifyContent: 'center' },
  rangeRow: { flexDirection: 'row', alignItems: 'center', gap: 10, paddingBottom: 10, paddingLeft: 26 },
  rangeLabel: { fontSize: 14 },
  pill: { borderRadius: 17, borderWidth: 1, paddingHorizontal: 12, paddingVertical: 5, minWidth: 48, alignItems: 'center' },
  pillText: { fontSize: 16 },
  panel: { alignItems: 'center', paddingBottom: 14 },
  error: { fontSize: 13, lineHeight: 18, paddingHorizontal: 16, paddingBottom: 10 },
  deleteBlock: { gap: 8 },
  hint: { fontSize: 13, lineHeight: 18, paddingHorizontal: 4 },
});
