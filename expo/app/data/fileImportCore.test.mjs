import assert from 'node:assert/strict';
import test from 'node:test';
import { bytesToBase64, formatBytes, importPickError, isBinaryImport, MAX_IMPORT_BYTES } from './fileImportCore.js';

test('import pick rules check type, emptiness and the upper bound', () => {
  assert.equal(importPickError({ name: 'a.csv', size: 10 }, '.csv'), '');
  assert.match(importPickError({ name: 'a.zip', size: 10 }, '.csv'), /\.csv/);
  assert.match(importPickError({ name: 'a.csv', size: 0 }, '.csv'), /empty/);
  assert.match(importPickError({ name: 'a.csv', size: MAX_IMPORT_BYTES + 1 }, '.csv'), /limit is 100 MB/);
  assert.equal(importPickError({ name: 'A.ZIP', size: 5 }, '.zip,.json'), '');
  assert.equal(importPickError({ name: 'x', size: 5 }, ''), '');
  assert.match(importPickError({ name: '', size: 5 }, ''), /Choose a file/);
});

test('zip files travel as base64 and formats read like the web', () => {
  assert.equal(isBinaryImport('Export.ZIP'), true);
  assert.equal(isBinaryImport('a.csv'), false);
  assert.equal(formatBytes(512), '512 B');
  assert.equal(formatBytes(2048), '2.0 KB');
  assert.equal(formatBytes(5 * 1024 * 1024), '5.0 MB');
});

test('base64 encoder matches Buffer for every padding length', () => {
  for (const length of [0, 1, 2, 3, 4, 5, 255]) {
    const bytes = Uint8Array.from({ length }, (_, index) => (index * 37) % 256);
    assert.equal(bytesToBase64(bytes), Buffer.from(bytes).toString('base64'));
  }
});
