import assert from 'node:assert/strict';
import test from 'node:test';
import { horizontalContentPadding } from './safeAreaSpacing.mjs';

test('content margins mirror as the system rail changes sides', () => {
  for (const minimum of [16, 22]) {
    const leftRail = { left: 84, right: 0 };
    const rightRail = { left: 0, right: 84 };
    const left = horizontalContentPadding(leftRail, minimum);
    const right = horizontalContentPadding(rightRail, minimum);
    assert.deepEqual(left, { paddingLeft: 0, paddingRight: minimum });
    assert.deepEqual(right, { paddingLeft: minimum, paddingRight: 0 });
    assert.equal(horizontalContentPadding({ left: 0, right: 0 }, minimum).paddingLeft, minimum);
    assert.equal(horizontalContentPadding({ left: 0, right: 0 }, minimum).paddingRight, minimum);
    assert.deepEqual(horizontalContentPadding({ left: 10, right: 4 }, minimum),
      { paddingLeft: minimum - 10, paddingRight: minimum - 4 });
  }
});
