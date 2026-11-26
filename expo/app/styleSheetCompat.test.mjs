import assert from 'node:assert/strict';
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';
import test from 'node:test';

// React Native 0.88 no longer exports StyleSheet.absoluteFillObject (react-native-web still
// does). Spreading it gives an empty style on Android and iOS, so an overlay, scrim or backdrop
// silently loses its position and size and is never drawn. Write the five values out, or pass
// StyleSheet.absoluteFill as a style.
const root = new URL('../../', import.meta.url).pathname;

function sources(dir) {
  const found = [];
  for (const name of readdirSync(dir)) {
    if (name === 'node_modules' || name.startsWith('.') || name === 'android' || name === 'ios') continue;
    const path = join(dir, name);
    if (statSync(path).isDirectory()) found.push(...sources(path));
    else if (/\.(jsx|js|mjs)$/.test(name) && !/\.test\./.test(name)) found.push(path);
  }
  return found;
}

test('no shared or native component uses StyleSheet.absoluteFillObject', () => {
  const offenders = ['frontend', 'expo/app', 'expo/App.js']
    .flatMap(entry => (statSync(join(root, entry)).isDirectory() ? sources(join(root, entry)) : [join(root, entry)]))
    .filter(path => readFileSync(path, 'utf8').includes('StyleSheet.absoluteFillObject'))
    .map(path => relative(root, path));
  assert.deepEqual(offenders, []);
});

// Android throws on an `accessibilityRole` it does not know ("Invalid accessibility role value"),
// and the app crashes as soon as the view mounts. Web ARIA roles such as table, row, status or
// navigation go in the `role` prop instead: React Native maps the ones Android has and ignores the
// rest, and react-native-web renders both props as the same `role` attribute. This list is
// ReactAccessibilityDelegate.AccessibilityRole in React Native 0.88.
const ANDROID_ROLES = new Set([
  'adjustable', 'alert', 'button', 'checkbox', 'combobox', 'drawerlayout', 'dropdownlist', 'grid',
  'header', 'horizontalscrollview', 'iconmenu', 'image', 'imagebutton', 'keyboardkey', 'link', 'list',
  'menu', 'menubar', 'menuitem', 'none', 'pager', 'progressbar', 'radio', 'radiogroup', 'scrollbar',
  'scrollview', 'search', 'slidingdrawer', 'spinbutton', 'summary', 'switch', 'tab', 'tabbar', 'tablist',
  'text', 'timer', 'togglebutton', 'toolbar', 'viewgroup', 'webview',
]);

test('every literal accessibilityRole outside web-only files is one Android knows', () => {
  const offenders = [];
  for (const path of ['frontend', 'expo/app', 'expo/App.js']
    .flatMap(entry => (statSync(join(root, entry)).isDirectory() ? sources(join(root, entry)) : [join(root, entry)]))) {
    if (/\.web\.(jsx|js)$/.test(path)) continue;
    const text = readFileSync(path, 'utf8');
    for (const match of text.matchAll(/accessibilityRole(?:=\{([^}]*)\}|="([^"]*)"|:\s*('[^']*'|"[^"]*"))/g)) {
      const expression = match[1] ?? match[2] ?? match[3];
      // Only the values the expression can produce: a bare string, or one after `?`, `:` or `||`.
      const values = match[2] !== undefined ? [match[2]]
        : [...expression.trim().matchAll(/(?:^|\?|:|\|\|)\s*['"]([a-zA-Z_]+)['"]/g)].map(m => m[1]);
      for (const value of values) {
        if (!ANDROID_ROLES.has(value.toLowerCase())) offenders.push(`${relative(root, path)}: ${value}`);
      }
    }
  }
  assert.deepEqual(offenders, []);
});
