import { test } from 'node:test';
import { deepStrictEqual } from 'node:assert';
import { menuGeometry } from './menuGeometry.mjs';

test('folded and compact windows use the available content width', () => {
  deepStrictEqual(menuGeometry(360, 'closed'), { full: true, menuWidth: 360, gap: 0 });
  deepStrictEqual(menuGeometry(390, undefined), { full: true, menuWidth: 390, gap: 0 });
});

test('partially open uses the measured division, not a guessed midpoint', () => {
  deepStrictEqual(menuGeometry(900, 'partiallyOpen', { x: 410, width: 18 }),
    { full: false, menuWidth: 410, gap: 18 });
});

test('open and missing geometry fall back to a bounded sidebar', () => {
  deepStrictEqual(menuGeometry(900, 'fullyOpen'), { full: false, menuWidth: 288, gap: 0 });
  deepStrictEqual(menuGeometry(900, 'partiallyOpen'), { full: false, menuWidth: 288, gap: 0 });
});
