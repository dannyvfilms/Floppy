import React, { useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { CollectionGroup, CollectionRow } from './CollectionCopies';
import { Icon } from './Icon';
import { actionIcons } from './actionIcons';
import { NumberPickerRow } from './NumberPickerRow';
import { RatingSheet } from './RatingSheet';
import { systemFillColor } from './separatorColor';
import {
  CRITERION_PREFIX, criterionStep, formatScore, groupByTier, isFilled, overallSummary,
} from './ratingScaleModel';

const DEFAULT_LABELS = {
  title: 'Rating',
  overall: 'Overall',
  calculated: 'Calculated',
  manual: 'Manual',
  override: 'Override score',
  useCalculated: 'Use calculated score',
  overrideHint: 'Your own score replaces the calculated one until you switch back.',
  weight: 'Weight',
  notRated: 'Not rated',
  addRating: 'Add Rating',
  done: 'Done',
  cancel: 'Cancel',
  close: 'Close',
};

/**
 * The button that replaces the score field when a custom rating scale is on. It keeps the field's shape: a
 * grouped row with a value pill and chevron where the form is grouped, the bordered input everywhere else.
 */
export function RatingScaleButton({
  label, value, icon, grouped = false, palette, onPress, error, placeholder = DEFAULT_LABELS.addRating, manual = false,
}) {
  const shown = isFilled(value) ? `${formatScore(value)}${manual ? ' (manual)' : ''}` : '';
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
 * Scores each criterion of the active custom scale and shows the overall result as it changes. `values` is the
 * track form's flat values (`criterion:<id>`, `score`, `score_is_manual`); `onChange(name, value)` writes one.
 * The overall is calculated unless a score is typed over it; switching back restores the calculation.
 */
export function RatingCriteriaSheet({
  open, scale, values, onChange, onClose, onCancel, palette, labels: suppliedLabels, renderWheel, subtitle,
}) {
  const labels = { ...DEFAULT_LABELS, ...suppliedLabels };
  const [openRow, setOpenRow] = useState(null);
  if (!scale) return null;
  const summary = overallSummary(scale, values);
  const tiers = groupByTier(scale.criteria).filter(tier => tier.items.length);
  const fill = systemFillColor() || palette.surfaceStrong;
  const setValue = (criterion, next) => onChange(`${CRITERION_PREFIX}${criterion.id}`, next);
  const follow = summary.computed === null ? '' : String(summary.computed);

  // Typing criteria values never touches a manual score; only the override row and the switch-back row do.
  const overall = <CollectionGroup palette={palette}>
    <CollectionRow key="overall" icon={actionIcons.star} label={labels.overall} palette={palette}>
      <View style={styles.rowEnd}>
        <View style={[styles.score, { backgroundColor: fill }]}>
          <Text accessibilityLiveRegion="polite" style={[styles.scoreText, { color: summary.shown === null ? palette.textMuted : palette.text }]}>
            {summary.shown === null ? labels.notRated : formatScore(summary.shown)}</Text>
        </View>
      </View>
    </CollectionRow>
    {summary.manual ? <CollectionRow key="calc" label={labels.calculated} palette={palette}
      value={summary.computed === null ? labels.notRated : formatScore(summary.computed)} /> : null}
    <NumberPickerRow key="override" label={labels.override} min={0} max={10} step={0.1} palette={palette}
      startAt={summary.computed ?? 5}
      value={summary.manual ? values.score : ''} open={openRow === 'override'} renderWheel={renderWheel}
      onOpenChange={next => setOpenRow(next ? 'override' : null)}
      placeholder={labels.calculated}
      onChange={next => { onChange('score', next); onChange('score_is_manual', '1'); }} />
    {summary.manual ? <CollectionRow key="reset" tone="accent" label={labels.useCalculated} palette={palette}
      onPress={() => { onChange('score_is_manual', ''); onChange('score', follow); setOpenRow(null); }} /> : null}
  </CollectionGroup>;

  // Done keeps what was entered; Cancel, the close button and a tap outside put the earlier values back (`onCancel`).
  return <RatingSheet open={open} palette={palette} onClose={onCancel || onClose} closeLabel={labels.close}
    title={labels.title} subtitle={subtitle || scale.name} primaryLabel={labels.done} onPrimary={onClose}
    cancelLabel={labels.cancel}>
    {overall}
    {summary.manual ? <Text style={[styles.hint, { color: palette.textMuted }]}>{labels.overrideHint}</Text> : null}
    {tiers.map(tier => <CollectionGroup key={tier.weight} palette={palette}
      title={tiers.length > 1 ? `${labels.weight} ${tier.weight}` : undefined}>
      {tier.items.map(criterion => <NumberPickerRow key={criterion.id} label={criterion.name}
        min={criterion.min} max={criterion.max} step={criterionStep(criterion)} palette={palette}
        value={values[`${CRITERION_PREFIX}${criterion.id}`]} renderWheel={renderWheel}
        open={openRow === criterion.id} onOpenChange={next => setOpenRow(next ? criterion.id : null)}
        onChange={next => setValue(criterion, next)} onClear={() => setValue(criterion, '')} />)}
    </CollectionGroup>)}
  </RatingSheet>;
}

const styles = StyleSheet.create({
  rowEnd: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  rowValue: { fontSize: 16 },
  score: { borderRadius: 17, paddingHorizontal: 14, paddingVertical: 5, minWidth: 56, alignItems: 'center' },
  scoreText: { fontSize: 18, fontWeight: '600' },
  hint: { fontSize: 13, lineHeight: 18, paddingHorizontal: 4, marginTop: -8 },
  error: { fontSize: 13, lineHeight: 18, paddingHorizontal: 16, paddingBottom: 10 },
  field: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 8, borderWidth: 1,
    borderRadius: 6, paddingHorizontal: 12, minHeight: 40 },
  fieldText: { fontSize: 15 },
});
