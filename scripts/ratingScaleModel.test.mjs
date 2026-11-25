import assert from 'node:assert/strict';
import test from 'node:test';
import {
  addCriterion, addTier, criterionStep, formatResult, compactTiers, computeScore, criteriaBody, draftPayload,
  moveInTier, moveToTier, newDraft, overallSummary, ratingFormValues, validateDraft,
} from '../frontend/ui/ratingScaleModel.js';

const anime = [
  { id: 'v', name: 'Visuals', min: 0, max: 10, weight: 1 },
  { id: 'a', name: 'Audio', min: 0, max: 10, weight: 1 },
  { id: 's', name: 'Story', min: 0, max: 10, weight: 2 },
  { id: 'c', name: 'Characters', min: 0, max: 10, weight: 2 },
  { id: 'e', name: 'Enjoyment', min: 0, max: 10, weight: 3 },
  { id: 'b', name: 'Bonus', min: 0, max: 10, weight: 1 },
];

test('the issue example weighs to 8.4, not the plain 8.5', () => {
  assert.equal(computeScore(anime, { v: 8, a: 9, s: 7, c: 8, e: 9, b: 10 }), 8.4);
});

test('an empty criterion leaves the average and a zero stays in it', () => {
  assert.equal(computeScore(anime, { v: 10, s: 10, a: '' }), 10);
  assert.ok(computeScore(anime, { v: 10, s: 10, a: 0 }) < 10);
  assert.equal(computeScore(anime, {}), null);
});

test('ranges are normalised before weighting', () => {
  const mixed = [{ id: 'p', min: 0, max: 100, weight: 1 }, { id: 's', min: 1, max: 5, weight: 1 }];
  assert.equal(computeScore(mixed, { p: 100, s: 1 }), 5);
});

test('draft tier moves keep weights 1..n and compact empty tiers', () => {
  let draft = newDraft();
  draft = { ...draft, criteria: [{ ...draft.criteria[0], id: 'x', name: 'X' }] };
  draft = addTier(draft);
  draft = addTier(draft);
  assert.equal(draft.tiers, 3);
  draft = moveToTier(draft, 'x', 3);
  assert.equal(draft.criteria.find(item => item.id === 'x').weight, 3);
  const compact = compactTiers({ ...draft, criteria: draft.criteria.filter(item => item.id === 'x') });
  assert.equal(compact.criteria[0].weight, 1);
  assert.equal(compact.tiers, 1);
});

test('reordering inside a tier and validation', () => {
  let draft = { name: 'S', tiers: 1, criteria: [
    { id: '1', name: 'a', min: 1, max: 5, weight: 1 }, { id: '2', name: 'b', min: 1, max: 5, weight: 1 }] };
  draft = moveInTier(draft, 1, 0, 1);
  assert.deepEqual(draft.criteria.map(item => item.id), ['2', '1']);
  assert.deepEqual(validateDraft(draft), {});
  draft = addCriterion(draft, 1);
  assert.ok(Object.keys(validateDraft(draft)).length > 0);
  assert.equal(draftPayload({ ...draft, criteria: draft.criteria.slice(0, 2) }).criteria[0].id, '2');
});

test('form values and the manual override summary', () => {
  const scale = { criteria: anime, values: { v: 8 }, manual: false };
  const values = ratingFormValues(scale);
  assert.equal(values['criterion:v'], '8');
  assert.equal(values['criterion:a'], '');
  assert.deepEqual(criteriaBody(scale, values).criteria.a, null);
  assert.equal(overallSummary(scale, values).shown, 8);
  const manual = overallSummary(scale, { ...values, score_is_manual: '1', score: '9' });
  assert.equal(manual.manual, true);
  assert.equal(manual.shown, 9);
  assert.equal(manual.computed, 8);
});

test('wheels step by halves up to a maximum of 10 and by whole numbers above', () => {
  assert.equal(criterionStep({ min: 1, max: 10 }), 0.5);
  assert.equal(criterionStep({ min: 0, max: 100 }), 1);
  assert.equal(formatResult(8.4), '8.4');
  assert.equal(formatResult(9), '9.0');
  assert.equal(formatResult(''), '');
});
