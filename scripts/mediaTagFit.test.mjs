import assert from 'node:assert/strict';
import test from 'node:test';
import { visibleTagCount } from '../frontend/providers/mediaTagFit.js';

const widths = [60, 70, 50, 60];
const plusWidths = { 1: 28, 2: 28, 3: 28 };

test('every tag is shown when they all fit', () => {
  assert.equal(visibleTagCount({ widths, plusWidths, available: 400 }), 4);
});

test('tags that do not fit collapse behind a +N chip with room kept for it', () => {
  // 60 + 8 + 70 = 138, then +2 chip: 138 + 8 + 28 = 174.
  assert.equal(visibleTagCount({ widths, plusWidths, available: 180 }), 2);
  assert.equal(visibleTagCount({ widths, plusWidths, available: 173 }), 1);
});

test('the last tag needs no +N chip', () => {
  // All four: 60+8+70+8+50+8+60 = 264.
  assert.equal(visibleTagCount({ widths, plusWidths, available: 264 }), 4);
  assert.equal(visibleTagCount({ widths, plusWidths, available: 263 }), 3);
});

test('an unmeasured or empty row shows everything', () => {
  assert.equal(visibleTagCount({ widths, plusWidths, available: 0 }), 4);
  assert.equal(visibleTagCount({ widths: [], plusWidths, available: 100 }), 0);
});
