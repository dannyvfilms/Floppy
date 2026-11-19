import assert from 'node:assert/strict';
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';
import test from 'node:test';

// A component that draws a poster with its own title gradient is a second media card. Build the card
// from a model (frontend/ui/cardModels.js) instead; MediaCard owns the gradient (CardScrim).
const root = new URL('../../', import.meta.url).pathname;
const SCAN = ['frontend', 'expo/app'];

// Pieces that are deliberately not the media card, each with its reason. Anything else that draws its
// own card gradient fails here. Add to this list only by decision, never to silence the test.
const FOLLOW_UPS = {
  'frontend/ui/DetailPage.jsx': 'episode cards: a separate component by decision, built on part of the card later',
};

function sources(dir) {
  const found = [];
  for (const name of readdirSync(dir)) {
    if (name === 'node_modules' || name.startsWith('.')) continue;
    const path = join(dir, name);
    if (statSync(path).isDirectory()) found.push(...sources(path));
    else if (/\.(jsx|js)$/.test(name) && !/\.test\./.test(name)) found.push(path);
  }
  return found;
}

const files = SCAN.flatMap(dir => sources(join(root, dir))).map(path => [relative(root, path), path]);

test('only the media card imports the card gradient', () => {
  const offenders = files.filter(([name, path]) => !/MediaCard|CardScrim/.test(name)
    && /from '\.\/CardScrim'|from '.*\/CardScrim'/.test(readFileSync(path, 'utf8'))).map(([name]) => name);
  assert.deepEqual(offenders, []);
});

test('no component draws its own card gradient', () => {
  const drawn = /\b(episode|overlay|highlight|card|poster|person)Shade\b/;
  const offenders = files
    .filter(([name, path]) => !/MediaCard|CardScrim|DetailBackdrop/.test(name) && drawn.test(readFileSync(path, 'utf8')))
    .map(([name]) => name)
    .filter(name => !(name in FOLLOW_UPS));
  assert.deepEqual(offenders, []);
});

test('the follow-up list only names files that still draw a gradient', () => {
  const drawn = /\b(episode|overlay|highlight|card|poster|person)Shade\b/;
  const stale = Object.keys(FOLLOW_UPS).filter(name => !drawn.test(readFileSync(join(root, name), 'utf8')));
  assert.deepEqual(stale, []);
});
