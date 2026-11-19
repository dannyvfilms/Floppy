// Real server answers recorded by src/api/tests/test_native_recordings.py.
// The transport tests feed them through the real readers, so a server change
// that renames, moves or drops a field a native screen reads fails here.
// Refresh with: FLOPPY_RECORD_NATIVE=1 scripts/test.sh api.tests.test_native_recordings
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

export function recorded(name) {
  return JSON.parse(readFileSync(new URL(`./__recorded__/${name}.json`, import.meta.url), 'utf8'));
}

function typeOf(value) {
  if (value === null) return 'null';
  return Array.isArray(value) ? 'array' : typeof value;
}

/**
 * Assert each field the screen reads is present with one of the allowed
 * types. `spec` maps a field name to a type ("string", "number", "boolean",
 * "array", "object", "null") or a list of them, e.g. { score: ['number', 'null'] }.
 */
export function assertFields(object, spec, where) {
  assert.equal(typeOf(object), 'object', `${where} is not an object`);
  for (const [field, expected] of Object.entries(spec)) {
    const allowed = Array.isArray(expected) ? expected : [expected];
    assert.ok(field in object, `${where}.${field} is missing from the server answer`);
    assert.ok(
      allowed.includes(typeOf(object[field])),
      `${where}.${field} is ${typeOf(object[field])}, the reader expects ${allowed.join(' or ')}`,
    );
  }
}
