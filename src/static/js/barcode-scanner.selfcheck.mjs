// Self-check for normalizeIsbn(). No test framework in this project for
// browser JS, so this is a plain assert script: `node barcode-scanner.selfcheck.mjs`.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const dir = path.dirname(fileURLToPath(import.meta.url));
globalThis.window = globalThis;
const src = fs.readFileSync(path.join(dir, 'barcode-scanner.js'), 'utf8');
new Function(src)();

const { normalizeIsbn } = window.barcodeScannerUtils;

// A valid ISBN-10 (the canonical 0-306-40615-2 example) converts to the
// matching ISBN-13.
assert.equal(normalizeIsbn('0306406152'), '9780306406157');
// Dashes and spaces are stripped before checking.
assert.equal(normalizeIsbn('0-306-40615-2'), '9780306406157');
// A misread check digit (2 -> 3) must be rejected, not silently "corrected"
// into a different, wrong-but-valid-looking ISBN-13.
assert.equal(normalizeIsbn('0306406153'), null);
// An already-formed ISBN-13 passes through unchanged.
assert.equal(normalizeIsbn('9780306406157'), '9780306406157');
// Non-ISBN input is rejected.
assert.equal(normalizeIsbn('not-a-barcode'), null);

console.log('barcode-scanner self-check passed');
