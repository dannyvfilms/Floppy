import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const directory = path.dirname(fileURLToPath(import.meta.url));
const listeners = new Map();
const windowListeners = new Map();

globalThis.window = globalThis;
window.matchMedia = () => ({ matches: false });
window.addEventListener = (type, handler) => windowListeners.set(type, handler);
globalThis.document = {
  addEventListener(type, handler, options) {
    listeners.set(`${type}:${options === true ? "capture" : "bubble"}`, handler);
  },
};

const classes = new Set();
const surface = {
  classList: {
    add(value) { classes.add(value); },
    remove(value) { classes.delete(value); },
  },
  clientWidth: 400,
  scrollLeft: 100,
  capturedPointer: null,
  hasPointerCapture(pointerId) { return this.capturedPointer === pointerId; },
  releasePointerCapture(pointerId) {
    if (this.capturedPointer === pointerId) this.capturedPointer = null;
  },
  scrollBy(options) { this.lastScroll = options; },
  setPointerCapture(pointerId) { this.capturedPointer = pointerId; },
};
const otherSurface = { ...surface, scrollLeft: 0 };

const card = {
  closest(selector) {
    if (selector === '[data-horizontal-drag="true"]') return surface;
    if (selector.includes("button")) return null;
    return null;
  },
};
const otherCard = {
  closest(selector) {
    return selector === '[data-horizontal-drag="true"]' ? otherSurface : null;
  },
};
surface.closest = selector => (
  selector === '[data-horizontal-drag="true"]' ? surface : null
);

const source = fs.readFileSync(path.join(directory, "horizontal-scroll.js"), "utf8");
new Function(source)();

const pointerDown = listeners.get("pointerdown:bubble");
const pointerMove = listeners.get("pointermove:bubble");
const pointerUp = listeners.get("pointerup:bubble");
const pointerCancel = listeners.get("pointercancel:bubble");
const dragStart = listeners.get("dragstart:bubble");
const click = listeners.get("click:capture");
const keyDown = listeners.get("keydown:bubble");
const windowBlur = windowListeners.get("blur");

assert.ok(pointerDown && pointerMove && pointerUp && pointerCancel && dragStart && click && keyDown && windowBlur);

let nativeDragPrevented = false;
dragStart({
  target: card,
  preventDefault() { nativeDragPrevented = true; },
});
assert.equal(nativeDragPrevented, true);

let ordinaryClickPrevented = false;
click({
  target: card,
  preventDefault() { ordinaryClickPrevented = true; },
  stopImmediatePropagation() {},
});
assert.equal(ordinaryClickPrevented, false);

pointerDown({
  button: 0,
  clientX: 200,
  isPrimary: true,
  pointerId: 7,
  pointerType: "mouse",
  target: card,
});

let movePrevented = false;
pointerMove({
  clientX: 196,
  pointerId: 7,
  preventDefault() { movePrevented = true; },
});
assert.equal(surface.scrollLeft, 100);
assert.equal(movePrevented, false);

pointerMove({
  clientX: 150,
  pointerId: 7,
  preventDefault() { movePrevented = true; },
});
assert.equal(surface.scrollLeft, 150);
assert.equal(surface.capturedPointer, 7);
assert.equal(classes.has("is-horizontal-dragging"), true);
assert.equal(movePrevented, true);

pointerUp({ pointerId: 7 });
assert.equal(surface.capturedPointer, null);
assert.equal(classes.has("is-horizontal-dragging"), false);

let clickPrevented = false;
let clickStopped = false;
let unrelatedClickPrevented = false;
click({
  target: otherCard,
  preventDefault() { unrelatedClickPrevented = true; },
  stopImmediatePropagation() {},
});
assert.equal(unrelatedClickPrevented, false);
click({
  target: card,
  preventDefault() { clickPrevented = true; },
  stopImmediatePropagation() { clickStopped = true; },
});
assert.equal(clickPrevented, true);
assert.equal(clickStopped, true);

let keyPrevented = false;
keyDown({
  key: "ArrowRight",
  target: surface,
  preventDefault() { keyPrevented = true; },
});
assert.deepEqual(surface.lastScroll, { left: 340, behavior: "smooth" });
assert.equal(keyPrevented, true);

surface.lastScroll = null;
keyDown({
  key: "ArrowRight",
  target: card,
  preventDefault() {},
});
assert.equal(surface.lastScroll, null);

keyDown({
  altKey: true,
  key: "ArrowLeft",
  target: surface,
  preventDefault() { throw new Error("modified arrow shortcut was intercepted"); },
});
assert.equal(surface.lastScroll, null);

surface.capturedPointer = null;
pointerDown({
  button: 0,
  clientX: 200,
  isPrimary: true,
  pointerId: 8,
  pointerType: "touch",
  target: card,
});
pointerMove({
  clientX: 100,
  pointerId: 8,
  preventDefault() {},
});
assert.equal(surface.capturedPointer, null);

pointerDown({
  button: 0,
  clientX: 200,
  isPrimary: true,
  pointerId: 9,
  pointerType: "mouse",
  target: card,
});
pointerMove({
  buttons: 0,
  clientX: 100,
  pointerId: 9,
  preventDefault() { throw new Error("buttonless move was treated as a drag"); },
});
assert.equal(surface.scrollLeft, 150);

pointerDown({
  button: 0,
  clientX: 200,
  isPrimary: true,
  pointerId: 10,
  pointerType: "mouse",
  target: card,
});
pointerMove({ buttons: 1, clientX: 100, pointerId: 10, preventDefault() {} });
assert.equal(classes.has("is-horizontal-dragging"), true);
windowBlur({});
assert.equal(classes.has("is-horizontal-dragging"), false);

console.log("horizontal scroll self-check passed");
