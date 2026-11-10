import assert from 'node:assert/strict';
import test from 'node:test';
import { createFetchGate } from '../frontend/ui/fetchGate.js';

test('never runs more than the limit at once, and runs every task', async () => {
  const run = createFetchGate(3);
  let active = 0;
  let peak = 0;
  const task = async () => {
    active += 1;
    peak = Math.max(peak, active);
    await new Promise(resolve => setTimeout(resolve, 5));
    active -= 1;
    return 'ok';
  };
  const results = await Promise.all(Array.from({ length: 12 }, () => run(task)));
  assert.equal(results.length, 12);
  assert.equal(peak, 3);
});

test('a failing task frees its slot', async () => {
  const run = createFetchGate(1);
  await assert.rejects(run(async () => { throw new Error('boom'); }), /boom/);
  assert.equal(await run(async () => 'next'), 'next');
});
