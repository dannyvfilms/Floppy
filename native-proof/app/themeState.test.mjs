import assert from 'node:assert/strict';
import test from 'node:test';
import {
  DARK, LIGHT, LIVE_KEYS, PRESETS, getTheme, remountSignature, resolveTheme,
  setSystemScheme, setThemeSetting, subscribeTheme,
} from './themeState.js';

test('system follows the operating system and nothing else does', () => {
  assert.equal(resolveTheme({ theme: 'system' }, 'light').tokens, LIGHT);
  assert.equal(resolveTheme({ theme: 'system' }, 'dark').tokens, DARK);
  assert.equal(resolveTheme({ theme: 'system' }, 'light').override, null);
  assert.equal(resolveTheme({ theme: 'dark' }, 'light').tokens, DARK);
  assert.equal(resolveTheme({ theme: 'light' }, 'dark').tokens, LIGHT);
  assert.equal(resolveTheme({ theme: 'dracula' }, 'light').scheme, 'dark');
});

test('every preset resolves with the full token set', () => {
  Object.keys(PRESETS).forEach(theme => {
    const resolved = resolveTheme({ theme }, 'light');
    Object.keys(DARK).forEach(key => assert.ok(resolved.tokens[key], `${theme}.${key}`));
    assert.notEqual(resolved.tokens.accent, DARK.accent === resolved.tokens.accent ? null : DARK.accent);
  });
  assert.equal(resolveTheme({ theme: 'nord' }).tokens.background, '#2e3440');
});

test('custom palette overrides tokens and ignores invalid colours', () => {
  const { tokens } = resolveTheme({ theme: 'custom', custom: { page_bg: '#101010', accent: 'red', accent_text: '#FFFFFF', muted: '#abcdef' } });
  assert.equal(tokens.background, '#101010');
  assert.equal(tokens.accent, DARK.accent);
  assert.equal(tokens.accentContrast, '#ffffff');
  assert.equal(tokens.textMuted, '#abcdef');
});

test('surface borders follow the web scheme and preset tokens', () => {
  assert.equal(resolveTheme({ theme: 'dark' }).tokens.surfaceBorder, '#454d59');
  assert.equal(resolveTheme({ theme: 'system' }, 'light').tokens.surfaceBorder, '#ced4da');
  assert.equal(resolveTheme({ theme: 'dracula' }).tokens.surfaceBorder, '#6272a4');
  assert.equal(resolveTheme({ theme: 'custom', custom: {} }).tokens.surfaceBorder, '#454d59');
  const custom = resolveTheme({ theme: 'custom', custom: { panel: '#123456' } }).tokens;
  assert.equal(custom.panel, 'rgba(18, 52, 86, 0.82)');
  assert.equal(custom.surfaceStrong, DARK.surfaceStrong);
  assert.equal(resolveTheme({ theme: 'glass' }).tokens.surfaceDim, '#0c1122');
});

test('custom effects validate like the server and apply opacity to surfaces only', () => {
  const custom = resolveTheme({ theme: 'custom', custom: {
    surface: '#102030', panel: '#405060', radius: 0, blur: 24, surface_opacity: 40,
  } });
  assert.deepEqual(custom.effects, { radius: 0, blur: 24, surfaceOpacity: 40 });
  assert.equal(custom.tokens.surface, 'rgba(16, 32, 48, 0.4)');
  assert.equal(custom.tokens.panel, 'rgba(64, 80, 96, 0.4)');
  assert.equal(custom.tokens.surfaceStrong, DARK.surfaceStrong);
  const opaque = resolveTheme({ theme: 'custom', custom: { surface: '#102030', surface_opacity: 100 } });
  assert.equal(opaque.tokens.surface, '#102030');
  const invalid = resolveTheme({ theme: 'custom', custom: { radius: -2, blur: 3, surface_opacity: true } });
  assert.deepEqual(invalid.effects, { radius: 12, blur: 12, surfaceOpacity: 82 });
  assert.equal(resolveTheme({ theme: 'dark' }).tokens, DARK);
  assert.notEqual(remountSignature(custom, LIVE_KEYS), remountSignature(opaque, LIVE_KEYS));
});

test('unknown theme falls back to system', () => {
  assert.equal(resolveTheme({ theme: 'neon' }, 'dark').theme, 'system');
  assert.equal(resolveTheme(null, 'dark').theme, 'system');
});

test('store notifies only when the resolved theme changes', () => {
  let calls = 0;
  const off = subscribeTheme(() => { calls += 1; });
  setThemeSetting({ theme: 'system' });
  assert.equal(calls, 0);
  setThemeSetting({ theme: 'oled' });
  assert.equal(calls, 1);
  assert.equal(getTheme().tokens.background, '#000000');
  setSystemScheme('light');
  assert.equal(calls, 1);
  setThemeSetting({ theme: 'system' });
  assert.equal(getTheme().tokens, LIGHT);
  off();
});

test('remount signature ignores live tokens and tracks literal ones', () => {
  const a = resolveTheme({ theme: 'dark' });
  const b = resolveTheme({ theme: 'light' });
  assert.equal(remountSignature(a, LIVE_KEYS), remountSignature(b, LIVE_KEYS));
  assert.notEqual(remountSignature(a, []), remountSignature(b, []));
  assert.notEqual(remountSignature(resolveTheme({ theme: 'dracula' }), LIVE_KEYS), remountSignature(a, LIVE_KEYS));
});

test('surfaceMutedSoft follows the web surface-muted at 0.4 per theme', async () => {
  const { resolveTheme, surfaceMutedSoft } = await import('./themeState.js');
  assert.equal(surfaceMutedSoft(resolveTheme({ theme: 'dark' })), 'rgba(52, 58, 64, 0.4)');
  assert.equal(surfaceMutedSoft(resolveTheme({ theme: 'system' }, 'light')), 'rgba(233, 236, 239, 0.4)');
  assert.equal(surfaceMutedSoft(resolveTheme({ theme: 'nord' })), 'rgba(76, 86, 106, 0.4)');
});
