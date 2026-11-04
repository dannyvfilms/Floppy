import { strict as assert } from 'node:assert';
import { readFile } from 'node:fs/promises';
import { test } from 'node:test';

const source = await readFile(new URL('../native-proof/mediaClient.js', import.meta.url), 'utf8');
const { loadMedia } = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);

test('requests the authenticated media endpoint and maps real API shape', async () => {
  const original = globalThis.fetch;
  globalThis.fetch = async (url, options) => {
    assert.equal(url, 'https://floppy.example.test/subpath/api/v1/media?limit=12');
    assert.equal(options.headers.Authorization, 'Bearer temporary-test-token');
    return { ok: true, json: async () => ({ results: [{ id: 12, item: { title: 'Example', image: '/poster.jpg' } }] }) };
  };
  try {
    assert.deepEqual(await loadMedia('https://floppy.example.test/subpath/', 'temporary-test-token'), [{ key: '12', title: 'Example', image: 'https://floppy.example.test/poster.jpg' }]);
  } finally { globalThis.fetch = original; }
});

test('only allows cleartext HTTP for loopback and reports authentication errors', async () => {
  await assert.rejects(loadMedia('http://example.test', 'token'), /HTTPS/);
  await assert.rejects(loadMedia('https://user:password@example.test', 'token'), /without credentials/);
  const original = globalThis.fetch;
  globalThis.fetch = async () => ({ ok: false, status: 403 });
  try { await assert.rejects(loadMedia('http://localhost:8000', 'bad-token'), /403/); }
  finally { globalThis.fetch = original; }
});
