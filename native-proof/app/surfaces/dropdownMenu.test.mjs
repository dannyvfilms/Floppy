import test from 'node:test';
import assert from 'node:assert/strict';
import { dropdownPlacement, toggleDropdownSelection } from '../../../frontend/ui/dropdownMetrics.js';

test('positions the menu relative to its sheet and flips near the bottom', () => {
  const bounds = { x: 100, y: 300, width: 400, height: 500 };
  assert.deepEqual(dropdownPlacement({ x: 130, y: 350, width: 250, height: 40 }, bounds, 100), { right: 120, top: 94 });
  assert.deepEqual(dropdownPlacement({ x: 130, y: 730, width: 250, height: 40 }, bounds, 100), { right: 120, bottom: 74 });
});

test('keeps a menu opened from a trigger near the left edge on screen', () => {
  const bounds = { x: 0, y: 0, width: 400, height: 800 };
  // A 60pt trigger at the left: right-aligning a 208pt menu would start at -100.
  assert.deepEqual(dropdownPlacement({ x: 24, y: 100, width: 60, height: 36 }, bounds, 100), { left: 24, top: 140 });
  // Near the right edge the left-aligned menu is pulled back so it ends inside the screen.
  assert.deepEqual(dropdownPlacement({ x: 380, y: 100, width: 10, height: 36 }, { ...bounds, width: 300 }, 100), { right: 8, top: 140 });
  assert.deepEqual(dropdownPlacement({ x: 150, y: 100, width: 60, height: 36 }, { ...bounds, width: 300 }, 100), { left: 84, top: 140 });
});

test('multi-select adds and removes choices without mutating the original', () => {
  const selected = ['one'];
  assert.deepEqual(toggleDropdownSelection(selected, 'two'), ['one', 'two']);
  assert.deepEqual(toggleDropdownSelection(selected, 'one'), []);
  assert.deepEqual(selected, ['one']);
});
