import test from 'node:test';
import assert from 'node:assert/strict';
import { shouldRevealMediaCardActions, shouldShowMediaCardCorner, shouldShowMediaCardLine } from '../../../frontend/ui/mediaCardBehavior.js';

test('touch actions reveal before opening when the server preference allows them', () => {
  const actions = { clickable: false, items: [{ title: 'Edit tracking' }] };
  assert.equal(shouldRevealMediaCardActions(actions, false), true);
  assert.equal(shouldRevealMediaCardActions(actions, true), false);
});

test('touch actions do not reveal when the server preference hides them', () => {
  const actions = { clickable: true, items: [{ title: 'Edit tracking' }] };
  assert.equal(shouldRevealMediaCardActions(actions, false), false);
});

test('cards without action buttons open directly', () => {
  assert.equal(shouldRevealMediaCardActions(null, false), false);
  assert.equal(shouldRevealMediaCardActions({ clickable: false, items: [] }, false), false);
});

test('credit metadata follows rest, reveal and dormant preferences', () => {
  const model = { hoverMetadata: true };
  assert.equal(shouldShowMediaCardLine(model, { dormant: false }, false), false);
  assert.equal(shouldShowMediaCardLine(model, { dormant: false }, true), true);
  assert.equal(shouldShowMediaCardLine(model, { dormant: true }, false), true);
  assert.equal(shouldShowMediaCardLine({}, { dormant: false }, false), true);
});

test('credit runtime waits for reveal without hiding other badges or changing default cards', () => {
  assert.equal(shouldShowMediaCardCorner({ hoverMetadata: true }, { kind: 'runtime' }, false), false);
  assert.equal(shouldShowMediaCardCorner({ hoverMetadata: true }, { kind: 'runtime' }, true), true);
  assert.equal(shouldShowMediaCardCorner({ hoverMetadata: true }, { kind: 'collected' }, false), true);
  assert.equal(shouldShowMediaCardCorner({}, { kind: 'runtime' }, false), true);
});
