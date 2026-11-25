// Pure rules for custom rating scales, shared by the web and native editors and rating sheets.
// The server (`users/rating_scales.py`) is the source of truth; these mirror it so the overall
// score updates as a person types, with no round trip.

export const MAX_CRITERIA = 30;
export const MAX_TIERS = 10;

const round1 = number => Math.round((number + Number.EPSILON) * 10) / 10;

/** A criterion value mapped onto the internal 0-10 range, so wide ranges gain no extra influence. */
export function scaleToTen(value, min, max) {
  const span = Number(max) - Number(min);
  if (!(span > 0)) return 0;
  return ((Number(value) - Number(min)) / span) * 10;
}

export function isFilled(value) {
  return value !== '' && value !== null && value !== undefined && Number.isFinite(Number(value));
}

/** Weighted average on 0-10. Empty criteria are skipped; a real 0 counts. Null when nothing is filled in. */
export function computeScore(criteria, values) {
  let total = 0;
  let weights = 0;
  for (const criterion of criteria || []) {
    const raw = values?.[criterion.id];
    if (!isFilled(raw)) continue;
    total += criterion.weight * scaleToTen(raw, criterion.min, criterion.max);
    weights += criterion.weight;
  }
  return weights ? round1(total / weights) : null;
}

/** Criteria grouped into weight tiers 1..n (tier count may exceed the used ones in a draft). */
export function groupByTier(criteria, tiers = 0) {
  const highest = Math.max(tiers, ...(criteria || []).map(item => item.weight), 1);
  return Array.from({ length: highest }, (_, index) => ({
    weight: index + 1,
    items: (criteria || []).filter(item => item.weight === index + 1),
  }));
}

/** Step a value picker moves in: tenths on a short range, whole numbers on a wide one. */
export function criterionStep(criterion) {
  return Number(criterion.max) - Number(criterion.min) <= 10 ? 0.1 : 1;
}

export function clampValue(criterion, value) {
  const number = Math.min(Number(criterion.max), Math.max(Number(criterion.min), Number(value)));
  return round1(number);
}

export function formatScore(value) {
  if (!isFilled(value)) return '';
  const number = Number(value);
  return Number.isInteger(number) ? String(number) : number.toFixed(1);
}

/** Star rows suit a criterion that counts 1..N whole steps, up to 10, and only a few of them. */
export function starRow(criterion) {
  const { min, max } = criterion;
  return Number(min) === 1 && Number.isInteger(Number(max)) && Number(max) <= 10 ? Number(max) : 0;
}

/** The chip popup lists a line per criterion when each is a star row and they fit; otherwise open the sheet. */
export function chipFitsLines(scale, limit = 4) {
  const criteria = scale?.criteria || [];
  return criteria.length > 0 && criteria.length <= limit && criteria.every(item => starRow(item) > 0);
}

// ----- form fields (shared by the web track form and the native API body) -----

export const CRITERION_PREFIX = 'criterion:';

/** The form's flat values for a rating scale: one `criterion:<id>` per criterion, plus the override flag. */
export function ratingFormValues(scale) {
  const values = { criteria_submitted: '1', score_is_manual: scale?.manual ? '1' : '' };
  for (const criterion of scale?.criteria || []) {
    const stored = scale.values?.[criterion.id];
    values[CRITERION_PREFIX + criterion.id] = isFilled(stored) ? String(stored) : '';
  }
  return values;
}

export function criteriaValues(scale, formValues) {
  const values = {};
  for (const criterion of scale?.criteria || []) {
    values[criterion.id] = formValues?.[CRITERION_PREFIX + criterion.id] ?? '';
  }
  return values;
}

/** API body fragment for a native save: `{ criteria: {id: number|null}, score_is_manual }`. */
export function criteriaBody(scale, formValues) {
  const values = criteriaValues(scale, formValues);
  const criteria = {};
  for (const criterion of scale.criteria) {
    criteria[criterion.id] = isFilled(values[criterion.id]) ? Number(values[criterion.id]) : null;
  }
  return { criteria, score_is_manual: Boolean(formValues.score_is_manual) };
}

// ----- editor draft -----

let counter = 0;
const tempId = () => `new-${Date.now().toString(36)}-${counter++}`;

export function newCriterion(weight = 1, name = '') {
  return { id: tempId(), name, min: 1, max: 10, weight };
}

export function newDraft() {
  return { id: null, name: '', tiers: 1, criteria: [newCriterion(1)] };
}

export function draftFromScale(scale) {
  const criteria = [...scale.criteria].sort((a, b) => a.weight - b.weight || a.position - b.position)
    .map(item => ({ id: item.id, name: item.name, min: item.min, max: item.max, weight: item.weight }));
  return { id: scale.id, name: scale.name, tiers: Math.max(1, ...criteria.map(item => item.weight)), criteria };
}

function ordered(criteria) {
  return [...criteria].sort((a, b) => a.weight - b.weight);
}

export function addCriterion(draft, weight) {
  if (draft.criteria.length >= MAX_CRITERIA) return draft;
  return { ...draft, criteria: ordered([...draft.criteria, newCriterion(weight)]) };
}

export function updateCriterion(draft, id, changes) {
  return { ...draft, criteria: draft.criteria.map(item => item.id === id ? { ...item, ...changes } : item) };
}

export function removeCriterion(draft, id) {
  return { ...draft, criteria: draft.criteria.filter(item => item.id !== id) };
}

export function addTier(draft) {
  if (draft.tiers >= MAX_TIERS) return draft;
  const tiers = draft.tiers + 1;
  return { ...draft, tiers, criteria: ordered([...draft.criteria, newCriterion(tiers)]) };
}

/** Move a criterion within its tier, from one position to another (drag or the move actions). */
export function moveInTier(draft, weight, from, to) {
  const tier = draft.criteria.filter(item => item.weight === weight);
  if (to < 0 || to >= tier.length || from === to) return draft;
  const [moved] = tier.splice(from, 1);
  tier.splice(to, 0, moved);
  const rest = draft.criteria.filter(item => item.weight !== weight);
  return { ...draft, criteria: ordered([...rest, ...tier]) };
}

/** Move a criterion to the end of another tier; its weight is the tier it lands in. */
export function moveToTier(draft, id, weight) {
  if (weight < 1 || weight > draft.tiers) return draft;
  const moving = draft.criteria.find(item => item.id === id);
  if (!moving || moving.weight === weight) return draft;
  const rest = draft.criteria.filter(item => item.id !== id);
  return { ...draft, criteria: ordered([...rest, { ...moving, weight }]) };
}

/** Empty tiers are dropped on save so weights stay 1..n with no gaps. */
export function compactTiers(draft) {
  const used = [...new Set(draft.criteria.map(item => item.weight))].sort((a, b) => a - b);
  const remap = new Map(used.map((weight, index) => [weight, index + 1]));
  return { ...draft, tiers: used.length || 1,
    criteria: draft.criteria.map(item => ({ ...item, weight: remap.get(item.weight) })) };
}

export function validateDraft(draft) {
  const errors = {};
  if (!draft.name.trim()) errors.name = 'Give the rating scale a name.';
  if (!draft.criteria.length) errors.criteria = 'Add at least one criterion.';
  draft.criteria.forEach(item => {
    if (!item.name.trim()) errors[item.id] = 'Name this criterion.';
    else if (!(Number(item.max) > Number(item.min))) errors[item.id] = 'Maximum must be above the minimum.';
  });
  return errors;
}

export function draftPayload(draft) {
  const compact = compactTiers(draft);
  return {
    name: compact.name.trim(),
    criteria: compact.criteria.map(item => ({
      ...(String(item.id).startsWith('new-') ? {} : { id: item.id }),
      name: item.name.trim(), min: Number(item.min), max: Number(item.max), weight: item.weight,
    })),
  };
}

/** The overall line under the criteria: calculated, or the manual score with the calculated one beside it. */
export function overallSummary(scale, formValues) {
  const computed = computeScore(scale.criteria, criteriaValues(scale, formValues));
  const manual = Boolean(formValues.score_is_manual) && isFilled(formValues.score);
  // A score from before the custom scale shows until criteria replace it.
  const kept = isFilled(formValues.score) && !(scale.criteria || []).some(item => isFilled(formValues[CRITERION_PREFIX + item.id]));
  const shown = manual ? round1(Number(formValues.score)) : computed ?? (kept ? round1(Number(formValues.score)) : null);
  return { computed, manual, shown };
}
