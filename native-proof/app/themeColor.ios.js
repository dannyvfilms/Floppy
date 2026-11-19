import { Appearance, DynamicColorIOS } from 'react-native';
import { BASIC_THEMES, DARK, LIGHT, LIVE_KEYS } from './themeState';

// System, light and dark use dynamic colours, so they follow the interface
// style without a re-render. Presets and the custom palette are literals.
export function liveKeysFor(resolved) {
  return BASIC_THEMES.includes(resolved.theme) ? LIVE_KEYS : [];
}

const dynamic = {};

export function themeColor(key, resolved) {
  if (!liveKeysFor(resolved).includes(key)) return resolved.tokens[key];
  // One object per token keeps identity stable across reads.
  if (!dynamic[key]) dynamic[key] = DynamicColorIOS({ light: LIGHT[key], dark: DARK[key] });
  return dynamic[key];
}

export function applyPlatformTheme(resolved) {
  if (typeof Appearance.setColorScheme === 'function') Appearance.setColorScheme(resolved.override);
}
