import test from 'node:test';
import assert from 'node:assert/strict';
import { dropdownPlacement, toggleDropdownSelection } from '../../../frontend/ui/dropdownMetrics.js';

test('positions the menu relative to its sheet and flips near the bottom', () => {
  const bounds = { x: 100, y: 300, width: 400, height: 500 };
  assert.deepEqual(dropdownPlacement({ x: 130, y: 350, width: 250, height: 40 }, bounds, 100), { right: 120, top: 94 });
  assert.deepEqual(dropdownPlacement({ x: 130, y: 730, width: 250, height: 40 }, bounds, 100), { right: 120, bottom: 74 });
});

test('multi-select adds and removes choices without mutating the original', () => {
  const selected = ['one'];
  assert.deepEqual(toggleDropdownSelection(selected, 'two'), ['one', 'two']);
  assert.deepEqual(toggleDropdownSelection(selected, 'one'), []);
  assert.deepEqual(selected, ['one']);
});
