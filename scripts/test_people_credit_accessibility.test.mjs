import assert from 'node:assert/strict';
import { build } from 'esbuild';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { createRequire } from 'node:module';
import { test } from 'node:test';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';

const require = createRequire(import.meta.url);

test('CreditCard accessible name includes the visible age and death label', async () => {
  const dir = await mkdtemp(join(process.cwd(), '.people-credit-accessibility-'));
  try {
    const outfile = join(dir, 'People.cjs');
    await build({
      entryPoints: ['frontend/ui/People.jsx'], outfile, bundle: true,
      platform: 'node', format: 'cjs', jsx: 'automatic',
      external: ['react', 'react-dom'], alias: { 'react-native': 'react-native-web' },
    });
    const { CreditCard } = createRequire(join(process.cwd(), 'package.json'))(outfile);
    const markup = renderToStaticMarkup(React.createElement(CreditCard, {
      entry: { title: 'Posthumous Release', role: 'Rae of Light', ageLabel: '85 yo at release\nDied 2010' },
      onOpen() {},
    }));
    assert.match(markup, /aria-label="Posthumous Release, Rae of Light, 85 yo at release, Died 2010"/);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});
