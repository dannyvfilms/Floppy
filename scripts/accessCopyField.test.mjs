// Access & Tokens credential copy fields: the browser adapter mounts the shared
// CopyField (inline variant) over the server input, copies the token from that
// node through the browser clipboard adapter, and restores the server fallback
// on unmount. The credential never appears in the mount props. Renders the real
// mountCopyField, CopyField and clipboard.web with react-dom over a minimal DOM.
// This is adapter logic only: the browser lifecycle (copy-item.js fallback,
// htmx cleanup, boosted navigation) is covered by
// users.tests.test_access_copy_browser.
import assert from 'node:assert/strict';
import { mkdtemp, readFile, writeFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import test from 'node:test';
import { pathToFileURL } from 'node:url';
import { build } from 'esbuild';
import { installFakeDom } from './test-support/fakeDom.mjs';

const root = resolve(import.meta.dirname, '..');
const support = join(root, 'scripts', 'test-support');

// The react-native stub drops onPress, so Button and Pressable record their
// handlers: Button by label, Pressable by accessible name.
const recordButtons = {
  name: 'record-button-presses',
  setup(b) {
    b.onLoad({ filter: /test-support\/reactNativeStub\.mjs$/ }, async args => {
      const source = await readFile(args.path, 'utf8');
      const stub = "export const Pressable = host('button');";
      assert.ok(source.includes(stub), 'react-native stub defines Pressable');
      return {
        contents: source.replace(stub, `export const Pressable = React.forwardRef(function Pressable({ children, onPress, disabled, accessibilityLabel }, ref) {
          globalThis.__buttons[accessibilityLabel] = { onPress, disabled };
          return React.createElement('button', { ref, 'aria-label': accessibilityLabel }, typeof children === 'function' ? children({ pressed: false, hovered: false }) : children);
        });`),
        loader: 'js',
      };
    });
    // `.web.jsx` resolves first here, as in the web bundle, so './Button' loads
    // Button.web.jsx; stub whichever Button file resolves.
    b.onLoad({ filter: /frontend\/ui\/Button(\.web|\.native)?\.jsx$/ }, () => ({
      contents: `
        import React from 'react';
        export function Button({ label, onPress, disabled, busy }) {
          globalThis.__buttons[label] = { onPress, disabled };
          return React.createElement('button', null, busy ? '…' : label);
        }`,
      loader: 'jsx',
    }));
  },
};

async function load() {
  const dir = await mkdtemp(join(tmpdir(), 'access-copy-field-'));
  const entry = join(dir, 'entry.jsx');
  await writeFile(entry, `
    export { act } from 'react';
    export { mountCopyField } from ${JSON.stringify(join(root, 'frontend/ui/mountCopyField.jsx'))};
  `);
  const outfile = join(dir, 'out.mjs');
  await build({
    entryPoints: [entry], bundle: true, format: 'esm', platform: 'node', outfile, jsx: 'automatic',
    nodePaths: [join(root, 'node_modules')],
    resolveExtensions: ['.web.jsx', '.web.js', '.jsx', '.js', '.mjs'],
    alias: {
      'react-native': join(support, 'reactNativeStub.mjs'),
      'react-native-svg': join(support, 'reactNativeSvgStub.mjs'),
    },
    define: { 'process.env.NODE_ENV': '"development"' },
    plugins: [recordButtons],
    logLevel: 'error',
  });
  const mod = await import(pathToFileURL(outfile).href);
  await rm(dir, { recursive: true, force: true });
  return mod;
}

const doc = installFakeDom();
// The few DOM calls mountRoot, the adapter and the clipboard fallback make
// beyond what react-dom needs.
const proto = globalThis.HTMLElement.prototype;
doc.getElementById = () => null;
doc.execCommand = () => false;
proto.select = function select() {};
proto.setSelectionRange = function setSelectionRange() {};
// Supports `tag` and `tag[attribute]`, which is all these tests query.
proto.querySelector = function querySelector(selector) {
  const [, tag, attribute] = selector.match(/^(\w+)(?:\[([\w-]+)\])?$/);
  for (const child of this.childNodes) {
    if (child.nodeType !== 1) continue;
    if (child.tagName === tag.toUpperCase() && (!attribute || child.hasAttribute(attribute))) return child;
    const found = child.querySelector(selector);
    if (found) return found;
  }
  return null;
};
proto.cloneNode = function cloneNode() {
  const copy = doc.createElement(this.tagName);
  Object.assign(copy.attributes, this.attributes);
  if ('value' in this) copy.value = this.value;
  this.childNodes.forEach(child => copy.appendChild(child.nodeType === 1 ? child.cloneNode(true) : doc.createTextNode(child.nodeValue)));
  return copy;
};
proto.replaceChildren = function replaceChildren(...nodes) {
  [...this.childNodes].forEach(child => this.removeChild(child));
  nodes.forEach(node => this.appendChild(node));
};

const { act, mountCopyField } = await load();
const tick = () => new Promise(done => setTimeout(done, 10));
const SECRET = 'flp_0123456789abcdef';
const props = { credential: true, variant: 'inline', label: 'API token', copyLabel: 'Copy', copiedLabel: 'Copied!' };
const COPY = 'Copy API token';

function setClipboard(writeText) {
  globalThis.isSecureContext = true;
  const userAgent = globalThis.navigator?.userAgent ?? 'node';
  Object.defineProperty(globalThis, 'navigator', { value: { userAgent, clipboard: { writeText } }, configurable: true });
}

// The server fallback: the readonly input and the legacy copy-item.js control.
function serverHost(value = SECRET) {
  const host = doc.createElement('div');
  host.dataset = {};
  const row = doc.createElement('div');
  const input = doc.createElement('input');
  input.setAttribute('id', 'token');
  input.setAttribute('value', value);
  input.value = value;
  const legacy = doc.createElement('span');
  legacy.setAttribute('data-copy-target', '#token');
  row.appendChild(input);
  row.appendChild(legacy);
  host.appendChild(row);
  doc.body.appendChild(host);
  return { host, input };
}

async function mount(host, mountProps = props) {
  globalThis.__buttons = {};
  let dispose;
  await act(async () => { dispose = mountCopyField(host, mountProps); await tick(); });
  return dispose;
}

const press = async label => {
  await act(async () => { await globalThis.__buttons[label].onPress(); await tick(); });
};

test('mounting keeps the server input as the value and drops the legacy control', async () => {
  const { host, input } = serverHost();
  const dispose = await mount(host);

  assert.equal(host.dataset.reactMounted, 'true');
  assert.equal(host.querySelector('input'), input, 'the original input node is moved into the field');
  assert.equal(host.querySelector('span[data-copy-target]'), null);
  assert.equal(JSON.stringify(props).includes(SECRET), false, 'props never carry the credential');
  assert.equal(globalThis.__buttons[COPY].disabled, false);
  // Inline keeps the server look: no visible label or text button.
  assert.equal(globalThis.__buttons.Copy, undefined);
  assert.doesNotMatch(host.textContent, /API token/);
  await act(async () => dispose());
});

test('the stacked variant (provider URL consumers) keeps its label and Copy button', async () => {
  const host = doc.createElement('div');
  host.dataset = {};
  doc.body.appendChild(host);
  const dispose = await mount(host, { label: 'ListenBrainz URL', value: 'https://example.test/apis/listenbrainz/1/' });
  assert.match(host.textContent, /ListenBrainz URL/);
  assert.equal(globalThis.__buttons.Copy.disabled, false);
  await act(async () => dispose());
});

test('Copy writes the token from the input through the Clipboard API', async () => {
  const written = [];
  setClipboard(async text => { written.push(text); });
  const { host, input } = serverHost();
  const dispose = await mount(host);

  const announcement = host.querySelector('span[aria-live]');
  assert.equal(announcement.getAttribute('aria-live'), 'polite');
  assert.equal(announcement.textContent, '');
  await press(COPY);
  assert.deepEqual(written, [SECRET]);
  // The icon button now announces the copied state.
  assert.ok(globalThis.__buttons['Copied!'], 'copied state is exposed on the icon button');
  assert.equal(announcement.textContent, 'Copied!');

  // The value is read at copy time from the adapter-owned node.
  input.value = 'flp_rotated';
  await press('Copied!');
  assert.deepEqual(written, [SECRET, 'flp_rotated']);
  await act(async () => dispose());
});

test('inline Copy is disabled until the pending clipboard write settles', async () => {
  let finishWrite;
  const pendingWrite = new Promise(resolve => { finishWrite = resolve; });
  setClipboard(() => pendingWrite);
  const { host } = serverHost();
  const dispose = await mount(host);

  let copy;
  await act(async () => { copy = globalThis.__buttons[COPY].onPress(); });
  assert.equal(globalThis.__buttons[COPY].disabled, true);
  assert.equal(globalThis.__buttons[COPY].onPress, undefined);

  await act(async () => { finishWrite(); await copy; });
  assert.equal(globalThis.__buttons['Copied!'].disabled, false);
  await act(async () => dispose());
});

test('a failed copy keeps the token visible and offers manual recovery', async () => {
  setClipboard(async () => { throw new Error('denied'); });
  const { host, input } = serverHost();
  const dispose = await mount(host);

  await press(COPY);
  assert.match(host.textContent, /Could not copy automatically\./);
  assert.equal(host.querySelector('input'), input);
  assert.equal(input.value, SECRET);
  await act(async () => dispose());
});

test('an empty account token disables Copy', async () => {
  const { host } = serverHost('');
  const dispose = await mount(host);
  assert.equal(globalThis.__buttons[COPY].disabled, true);
  await act(async () => dispose());
});

test('unmounting (htmx cleanup) restores the server fallback', async () => {
  const { host } = serverHost();
  const dispose = await mount(host);
  await act(async () => dispose());

  assert.equal(host.dataset.reactMounted, undefined);
  const restored = host.querySelector('input');
  assert.equal(restored.getAttribute('value'), SECRET);
  assert.ok(host.querySelector('span'), 'legacy copy control is back for the fallback');
});
