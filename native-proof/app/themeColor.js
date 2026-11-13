import { Appearance } from 'react-native';

// Android and any platform without a dynamic colour: values are literals, so
// ThemeRoot remounts the tree when the resolved theme changes.
export function liveKeysFor() {
  return [];
}

export function themeColor(key, resolved) {
  return resolved.tokens[key];
}

// Keeps native chrome (status bar, keyboards, alerts) in the chosen scheme.
export function applyPlatformTheme(resolved) {
  if (typeof Appearance.setColorScheme === 'function') Appearance.setColorScheme(resolved.override);
}
