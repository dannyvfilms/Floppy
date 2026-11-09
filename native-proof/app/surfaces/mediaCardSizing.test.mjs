import test from 'node:test';
import assert from 'node:assert/strict';
import { playbackCardWidth } from '../../../frontend/ui/mediaCardSizing.js';

test('mobile playback spans the configured number of regular cards and fits content width', () => {
  assert.equal(playbackCardWidth(390, 'compact'), 358);
  assert.equal(playbackCardWidth(390, 'comfortable'), 348);
  assert.equal(playbackCardWidth(320, 'compact'), 288);
  assert.equal(playbackCardWidth(320, 'comfortable'), 288);
});

test('desktop playback spans two regular cards', () => {
  assert.equal(playbackCardWidth(1200, 'compact'), 380);
});
