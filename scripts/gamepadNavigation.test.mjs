import assert from 'node:assert/strict';
import test from 'node:test';

// The script is a browser file; give it the few globals it touches at load.
globalThis.window = globalThis;
Object.defineProperty(globalThis, 'navigator', { value: { getGamepads: () => [] }, configurable: true });
const noop = () => {};
globalThis.document = {
  head: { appendChild: noop },
  documentElement: { classList: { toggle: noop } },
  addEventListener: noop,
  createElement: () => ({}),
};
window.addEventListener = noop;
await import('../src/static/js/gamepadNavigation.js');
const { directionFrom, pickNext } = window.FloppyGamepadNav;

const pad = (overrides = {}) => {
  const buttons = Array.from({ length: 17 }, () => ({ pressed: false }));
  for (const [index, pressed] of Object.entries(overrides)) buttons[index] = { pressed };
  return buttons;
};
const box = (left, top, width = 100, height = 40) => ({ left, top, width, height });
const item = (name, rect) => ({ name, rect });

test('D-pad buttons and the left stick both give a direction', () => {
  assert.equal(directionFrom([0, 0], pad({ 12: true })), 'up');
  assert.equal(directionFrom([0, 0], pad({ 13: true })), 'down');
  assert.equal(directionFrom([0, 0], pad({ 14: true })), 'left');
  assert.equal(directionFrom([0, 0], pad({ 15: true })), 'right');
  assert.equal(directionFrom([0.9, 0.2], pad()), 'right');
  assert.equal(directionFrom([-0.2, -0.8], pad()), 'up');
});

test('a resting or lightly touched stick does nothing', () => {
  assert.equal(directionFrom([0, 0], pad()), null);
  assert.equal(directionFrom([0.3, -0.4], pad()), null);
});

test('focus moves to the control straight ahead, not a nearer one off to the side', () => {
  const from = box(0, 0);
  const aligned = item('aligned', box(0, 200));
  const sideways = item('sideways', box(160, 60));
  assert.equal(pickNext(from, [sideways, aligned], 'down').name, 'aligned');
});

test('only controls in the pressed direction are chosen', () => {
  const from = box(300, 300);
  const all = [item('up', box(300, 100)), item('left', box(100, 300)), item('right', box(500, 300))];
  assert.equal(pickNext(from, all, 'up').name, 'up');
  assert.equal(pickNext(from, all, 'left').name, 'left');
  assert.equal(pickNext(from, all, 'right').name, 'right');
  assert.equal(pickNext(from, all, 'down'), null);
});

test('a control that overlaps the current one is not ahead of it', () => {
  assert.equal(pickNext(box(0, 0), [item('overlap', box(10, 10))], 'right'), null);
});
