import { strict as assert } from 'node:assert';
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import { inspectUniversal, inspectWebAdapter, isNativeAppShellPresentation, legacyStatements, validateRegistry } from './check_ui_architecture.mjs';

const native = "import React from 'react'; import {View, Text} from 'react-native'; export function Card(){ return <View><Text>ok</Text></View>; }";
const evidence = Object.fromEntries(['web', 'ios', 'android'].map(p => [p, { status: 'unverified', evidence: 'Not exercised.' }]));

test('accepts native primitives, component state and comments mentioning web concepts', () => {
  assert.deepEqual(inspectUniversal(`${native}\n// document and fetch are not executable here`), []);
  assert.deepEqual(inspectUniversal("import React, {useState} from 'react'; import {Text} from 'react-native'; export function A(){const [n,setN]=useState(0);return <Text onPress={()=>setN(n+1)}>{n}</Text>}"), []);
});

test('data layers may fetch but cannot render or access browser globals', () => {
  assert.deepEqual(inspectUniversal('export function load(){return fetch("/api")}', 'client.js', { logic: true, dataLayer: true }), []);
  assert.ok(inspectUniversal('export function load(){return document.body}', 'client.js', { logic: true, dataLayer: true }).length);
  assert.ok(inspectUniversal('export function load(){return <div/>}', 'client.js', { logic: true, dataLayer: true }).length);
});

test('rejects DOM, browser APIs, transport, CSS and web dependencies', () => {
  for (const fragment of ['<div/>', '<View className="p-2"/>', '<View href="/"/>', 'document.title', 'window.location', 'fetch("/api")', 'React.createElement("div")', 'require("axios")', '<Text style={{fontSize: "1rem"}}/>', '"{% csrf_token %}"']) {
    assert.ok(inspectUniversal(`${native}\n${fragment};`).length, fragment);
  }
  for (const declaration of ["import x from 'react-dom';", "import x from './x.css';", "export {x} from 'react-native-webview';"]) assert.ok(inspectUniversal(`${native}\n${declaration}`).length, declaration);
  assert.ok(inspectUniversal("import {View} from 'react-native'; export const Placeholder = () => null;").some(e => e.includes('empty placeholders')));
  assert.ok(inspectUniversal(`'use dom'; ${native}`).some(e => e.includes('Expo DOM')));
});

test('requires registration and prohibits expanding or changing a frozen baseline', () => {
  const path = 'frontend/Old.jsx';
  const old = 'const one = 1; const two = 2;';
  const baseline = { sha256: createHash('sha256').update(old).digest('hex'), statements: legacyStatements(old) };
  const base = { legacy: { [path]: baseline }, universal: {} };
  assert.deepEqual(validateRegistry(base, base, [path], () => old), []);
  assert.deepEqual(validateRegistry(base, base, [path], () => 'const two = 2;'), []);
  assert.match(validateRegistry(base, base, [path], () => old, undefined, () => 'const two = 2;').join(), /legacy declaration changed/);
  assert.match(validateRegistry(base, base, [path], () => 'const one = 3; const two = 2;').join(), /legacy declaration changed/);
  assert.match(validateRegistry({ legacy: { [path]: 'new' } }, base, [path], () => old).join(), /adding or changing/);
  assert.match(validateRegistry({ legacy: {} }, base, [path], () => native).join(), /register universal/);
  assert.match(validateRegistry({ legacy: {} }, null, ['frontend/New.mjs'], () => native).join(), /register universal/);
});

test('accepts an explicitly registered platform pair and rejects missing native counterpart', () => {
  const web = 'frontend/Camera.web.jsx';
  const ios = 'frontend/Camera.native.jsx';
  const entry = { kind: 'presentation', register: 'ARTWORK', components: ['Camera'], purpose: 'Camera uses platform APIs', verification: evidence };
  const registry = { legacy: {}, universal: {}, platform: { [web]: entry, [ios]: entry } };
  const docs = { register: '### ARTWORK — Camera', map: `\`${web}\` \`${ios}\`` };
  const camera = "import React from 'react'; import {View} from 'react-native'; export function Camera(){return <View/>}";
  assert.deepEqual(validateRegistry(registry, null, [web, ios], path => path === web ? 'export function Camera(){return <div />}' : camera, docs), []);
  assert.match(validateRegistry({ ...registry, platform: { [web]: entry } }, null, [web], () => '', docs).join(), /requires web and native/);
  assert.match(validateRegistry(registry, null, [web, ios], path => path === ios ? `${camera}; <div />` : '', docs).join(), /HTML element/);
});

test('accepts non-rendering platform service adapters', () => {
  const web = 'frontend/Camera.web.js';
  const nativeFile = 'frontend/Camera.native.js';
  const entry = { kind: 'adapter', register: 'ARTWORK', components: ['Camera'], purpose: 'Camera APIs', verification: evidence };
  const registry = { legacy: {}, universal: {}, platform: { [web]: entry, [nativeFile]: entry } };
  const docs = { register: '### ARTWORK — Camera', map: `\`${web}\` \`${nativeFile}\`` };
  const sources = { [web]: 'export function Camera(){return navigator.mediaDevices}', [nativeFile]: "import * as CameraModule from 'expo-camera'; export function Camera(){return CameraModule}" };
  assert.deepEqual(validateRegistry(registry, null, [web, nativeFile], path => sources[path], docs), []);
  assert.match(validateRegistry(registry, null, [web, nativeFile], path => path === web ? 'export function Camera(){return <div/>}' : sources[path], docs).join(), /cannot render JSX/);
});

test('web mount adapters may integrate DOM but cannot introduce HTML presentation', () => {
  assert.deepEqual(inspectWebAdapter("import React from 'react'; export function mount(host){ return <Card host={host}/> }", 'mountCard.jsx'), []);
  for (const code of ['<div/>', 'host.innerHTML = "<b>hello</b>"', 'document.createElement("div")']) {
    assert.ok(inspectWebAdapter(code, 'mountCard.jsx').length, code);
  }
  assert.deepEqual(inspectWebAdapter('const x = <a href="/genres"><SharedBadge /></a>;', 'BadgeTheme.web.jsx', ['SharedBadge']), []);
  assert.deepEqual(inspectWebAdapter('const x = <a href="/genres" style={{textDecoration:"none"}}><SharedBadge /></a>;', 'BadgeTheme.web.jsx', ['SharedBadge']), []);
  assert.ok(inspectWebAdapter('const x = <a href="/genres" style={{color:"red"}}><SharedBadge /></a>;', 'BadgeTheme.web.jsx', ['SharedBadge']).length);
  assert.ok(inspectWebAdapter('const x = <a href="/genres">text</a>;', 'BadgeTheme.web.jsx', ['SharedBadge']).length);
  assert.ok(inspectWebAdapter('const x = <a href="/genres"><Unregistered /></a>;', 'BadgeTheme.web.jsx', ['SharedBadge']).length);
});

test('cannot reclassify a universal component as platform-specific', () => {
  const path = 'frontend/Camera.web.jsx';
  const registry = { legacy: {}, universal: {}, platform: { [path]: { kind: 'presentation', register: 'ARTWORK', components: ['Camera'], purpose: 'camera', verification: evidence } } };
  assert.match(validateRegistry(registry, { legacy: {}, universal: { [path]: {} } }, [path], () => '').join(), /cannot be downgraded/);
});

test('each registered presentation export must render, even beside a real component', () => {
  const path = 'frontend/ui/ExampleCard.jsx';
  const source = "import {View} from 'react-native'; export function ExampleCard(){return null} export function ExampleLabel(){return <View/>}";
  const registry = { legacy: {}, universal: { [path]: { register: 'MEDIA-CARD', components: ['ExampleCard', 'ExampleLabel'], verification: evidence } } };
  assert.match(validateRegistry(registry, null, [path], () => source).join(), /ExampleCard.*renders an element/);
});

test('a legacy export may redirect only its existing component to registered shared presentation', () => {
  const oldPath = 'frontend/Old.jsx';
  const sharedPath = 'frontend/Shared.jsx';
  const old = 'export function Spinner(){ return <span/> }; export function Other(){ return <div/> }';
  const shared = 'import {View} from "react-native"; export function Spinner(){return <View/>}';
  const baseline = { sha256: createHash('sha256').update(old).digest('hex'), statements: legacyStatements(old) };
  const base = { legacy: { [oldPath]: baseline }, universal: {} };
  const registry = { legacy: base.legacy, universal: { [sharedPath]: { register: 'SPINNER', components: ['Spinner'], verification: evidence } } };
  const docs = { register: '### SPINNER — Spinner', map: `\`${sharedPath}\`` };
  const run = source => validateRegistry(registry, base, [oldPath, sharedPath], path => path === oldPath ? source : shared, docs, path => path === oldPath ? old : undefined).join();
  assert.equal(run('export { Spinner } from "./Shared"; export function Other(){ return <div/> }'), '');
  for (const source of [
    'export { Other } from "./Shared"; export function Spinner(){ return <span/> }',
    'export { Spinner } from "./Shared"; export function Other(){ return <button/> }',
    'export { Spinner } from "./Unregistered"; export function Other(){ return <div/> }',
    'export { Spinner as Other } from "./Shared"; export function Spinner(){ return <span/> }',
    'export { Spinner } from "./Shared"; export function Other(){ return <div/> }; const added = 1',
  ]) assert.match(run(source), /legacy declaration changed/);
});

test('a legacy re-export through a web adapter must lead to the registered component', () => {
  const oldPath = 'frontend/Old.jsx', adapterPath = 'frontend/Spinner.web.jsx', sharedPath = 'frontend/Shared.jsx';
  const old = 'export function Spinner(){return <span/>}';
  const baseline = { sha256: createHash('sha256').update(old).digest('hex'), statements: legacyStatements(old) };
  const base = { legacy: { [oldPath]: baseline }, universal: {} };
  const registry = { legacy: base.legacy, universal: { [sharedPath]: { register: 'SPINNER', components: ['Spinner'], verification: evidence } }, web_adapters: { [adapterPath]: { register: 'SPINNER', purpose: 'Resolve colors' } } };
  const docs = { register: '### SPINNER — Spinner', map: `\`${sharedPath}\` \`${adapterPath}\`` };
  const shared = 'import {View} from "react-native"; export function Spinner(){return <View/>}';
  const run = adapter => validateRegistry(registry, base, [oldPath, adapterPath, sharedPath], path => path === oldPath ? 'export {Spinner} from "./Spinner.web"' : path === adapterPath ? adapter : shared, docs, path => path === oldPath ? old : undefined).join();
  assert.equal(run('import {Spinner as Shared} from "./Shared"; export function Spinner(){return <Shared/>}'), '');
  assert.match(run('export function Spinner(){return <Other/>}'), /legacy declaration changed/);
  assert.match(run('import {Spinner as Shared} from "./Shared"; export function Spinner(){return <div/>}'), /cannot define HTML/);
});


test('native application shell screens are allowed outside frontend but still checked', () => {
  assert.equal(isNativeAppShellPresentation('native-proof/app/screens/HomeScreen.jsx'), true);
  assert.equal(isNativeAppShellPresentation('native-proof/app/components/Note.tsx'), true);
  assert.equal(isNativeAppShellPresentation('native-proof/App.js'), false);
  assert.equal(isNativeAppShellPresentation('src/HomeScreen.jsx'), false);
  assert.deepEqual(inspectUniversal(native, 'native-proof/app/screens/HomeScreen.jsx', { nativeAdapter: true, shell: true }), []);
  assert.deepEqual(inspectUniversal("import React from 'react'; import {Screen} from './Screen'; export default function Home(){return <Screen/>}", 'native-proof/app/screens/HomeScreen.jsx', { nativeAdapter: true, shell: true }), []);
  assert.ok(inspectUniversal(`${native}; <div/>`, 'native-proof/app/screens/HomeScreen.jsx', { nativeAdapter: true, shell: true }).length);
});

// The island dispatch already supports these roots; a missing host selector
// leaves server fallbacks mounted forever and browser interactions time out.
test('every island renderer branch is discoverable by the host selector', () => {
  const source = readFileSync(new URL('../frontend/settings/index.js', import.meta.url), 'utf8');
  const selector = source.match(/const selector = '([^']+)'/)?.[1];
  const dispatch = source.split('const kind = host.matches(')[1]?.split('    try {')[0];
  assert.ok(selector, 'missing browser island host selector');
  assert.ok(dispatch, 'missing browser island renderer dispatch');
  const roots = new Set(selector.split(',').map(item => item.trim()));
  const dispatched = [...dispatch.matchAll(/host\\.matches\\('([^']+)'\\)/g)]
    .flatMap(([, selectors]) => selectors.split(',').map(item => item.trim()));
  assert.ok(dispatched.length > 60, 'expected the full island dispatcher');
  for (const root of dispatched) {
    assert.ok(roots.has(root), `island renderer cannot discover ${root}`);
  }
});
