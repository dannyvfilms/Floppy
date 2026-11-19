import test from 'node:test';
import assert from 'node:assert/strict';
import { libraryGridLayout, playbackCardWidth } from '../../../frontend/ui/mediaCardSizing.js';

test('mobile playback spans the configured number of regular cards and fits content width', () => {
  assert.equal(playbackCardWidth(390, 'compact'), 358);
  assert.equal(playbackCardWidth(390, 'comfortable'), 348);
  assert.equal(playbackCardWidth(320, 'compact'), 288);
  assert.equal(playbackCardWidth(320, 'comfortable'), 288);
});

test('desktop playback spans two regular cards', () => {
  assert.equal(playbackCardWidth(1200, 'compact'), 380);
});

test('library grid fits three compact columns at phone width', () => {
  const phone = libraryGridLayout(390, 'compact');
  assert.equal(phone.gap, 12);
  assert.ok(phone.width * 3 + phone.gap * 2 <= 390 - 32 + 0.001);
  const narrowPhone = libraryGridLayout(375, 'compact');
  assert.ok(Math.abs(narrowPhone.width * 3 + narrowPhone.gap * 2 - (375 - 32)) < 0.001);
  const comfortable = libraryGridLayout(390, 'comfortable');
  assert.ok(comfortable.width * 2 + comfortable.gap <= 390 - 32 + 0.001);
  assert.ok(libraryGridLayout(1200).width >= 128);
});
