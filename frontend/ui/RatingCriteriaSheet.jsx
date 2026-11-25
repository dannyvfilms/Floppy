import React, { useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { CollectionGroup, CollectionRow } from './CollectionCopies';
import { Icon } from './Icon';
import { actionIcons } from './actionIcons';
import { NumberPickerRow } from './NumberPickerRow';
import { useInlineNumbers } from './inlineNumbers';
import { RatingSheet } from './RatingSheet';
import {
  CRITERION_PREFIX, criterionStep, formatResult, groupByTier, isFilled, overallSummary,
} from './ratingScaleModel';

const DEFAULT_LABELS = {
  title: 'Rating',
  rating: 'Rating',
  weight: 'Weight',
  notRated: 'Not rated',
  addRating: 'Add Rating',
  done: 'Done',
  cancel: 'Cancel',
  close: 'Close',
};

/**
 * The button that replaces the score field when a custom rating scale is on. It keeps the field's shape: a
 * grouped row with a value and chevron where the form is grouped, the bordered input everywhere else.
 */
export function RatingScaleButton({
  label, value, icon, grouped = false, palette, onPress, error, placeholder = DEFAULT_LABELS.addRating,
}) {
  const shown = formatResult(value);
  if (grouped) {
    return <View>
      <CollectionRow icon={icon} label={label} palette={palette} onPress={onPress} accessibilityLabel={`${label}: ${shown || placeholder}`}>
        <View style={styles.rowEnd}>
          <Text style={[styles.rowValue, { color: shown ? palette.textSecondary : palette.textMuted }]}>{shown || placeholder}</Text>
          <Icon spec={actionIcons.chevronRight} color={palette.textMuted} size={16} />
        </View>
      </CollectionRow>
      {error ? <Text accessibilityLiveRegion="polite" style={[styles.error, { color: palette.danger }]}>{error}</Text> : null}
    </View>;
  }
  return <Pressable accessibilityRole="button" accessibilityLabel={`${label}: ${shown || placeholder}`} onPress={onPress}
    style={({ pressed, hovered }) => [styles.field, { backgroundColor: palette.surfaceStrong,
      borderColor: error ? palette.danger : (palette.inputBorder || palette.border), opacity: pressed ? 0.8 : 1 },
    hovered && { backgroundColor: palette.surfaceMuted }]}>
    <Text style={[styles.fieldText, { color: shown ? palette.text : palette.textMuted }]}>{shown || placeholder}</Text>
    <Icon spec={actionIcons.chevronRight} color={palette.textMuted} size={16} />
  </Pressable>;
}

/**
 * Scores each criterion of the active custom scale. One Rating row shows the result and follows the criteria;
 * typing or picking a value there replaces it, and clearing it returns to the calculation. `values` is the track
 * form's flat values (`criterion:<id>`, `score`, `score_is_manual`); `onChange(name, value)` writes one.
 * Desktop web uses whole-number inputs; phones and native use pills that open a wheel (halves up to 10).
 */
export function RatingCriteriaSheet({
  open, scale, values, onChange, onClose, onCancel, palette, labels: suppliedLabels, renderWheel, subtitle,
}) {
  const labels = { ...DEFAULT_LABELS, ...suppliedLabels };
  const [openRow, setOpenRow] = useState(null);
  const inline = useInlineNumbers();
  if (!scale) return null;
  const summary = overallSummary(scale, values);
  const tiers = groupByTier(scale.criteria).filter(tier => tier.items.length);
  const setValue = (criterion, next) => onChange(`${CRITERION_PREFIX}${criterion.id}`, next);
  const backToCalculated = () => { onChange('score_is_manual', ''); onChange('score', summary.computed === null ? '' : String(summary.computed)); };

  const rating = <CollectionGroup palette={palette}>
    <NumberPickerRow key="rating" label={labels.rating} min={0} max={10} step={0.5} palette={palette} inline={inline} decimal
      value={summary.shown === null ? '' : summary.shown} display={summary.shown === null ? '' : formatResult(summary.shown)}
      startAt={summary.computed ?? 5} renderWheel={renderWheel} placeholder={labels.notRated}
      open={openRow === 'rating'} onOpenChange={next => setOpenRow(next ? 'rating' : null)}
      onChange={next => { onChange('score', next); onChange('score_is_manual', '1'); }}
      onClear={backToCalculated} />
  </CollectionGroup>;

  // Done keeps what was entered; Cancel, the close button and a tap outside put the earlier values back (`onCancel`).
  return <RatingSheet open={open} palette={palette} onClose={onCancel || onClose} closeLabel={labels.close}
    title={labels.title} subtitle={subtitle || scale.name} primaryLabel={labels.done} onPrimary={onClose}
    cancelLabel={labels.cancel}>
    {rating}
    {tiers.map(tier => <CollectionGroup key={tier.weight} palette={palette}
      title={tiers.length > 1 ? `${labels.weight} ${tier.weight}` : undefined}>
      {tier.items.map(criterion => <NumberPickerRow key={criterion.id} label={criterion.name}
        min={criterion.min} max={criterion.max} step={inline ? 1 : criterionStep(criterion)} palette={palette}
        inline={inline} value={values[`${CRITERION_PREFIX}${criterion.id}`]} renderWheel={renderWheel}
        open={openRow === criterion.id} onOpenChange={next => setOpenRow(next ? criterion.id : null)}
        onChange={next => setValue(criterion, next)} onClear={() => setValue(criterion, '')} />)}
    </CollectionGroup>)}
  </RatingSheet>;
}

const styles = StyleSheet.create({
  rowEnd: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  rowValue: { fontSize: 16 },
  error: { fontSize: 13, lineHeight: 18, paddingHorizontal: 16, paddingBottom: 10 },
  field: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 8, borderWidth: 1,
    borderRadius: 6, paddingHorizontal: 12, minHeight: 40 },
  fieldText: { fontSize: 15 },
});
