import { Appearance } from 'react-native';
import { LIVE_KEYS } from './themeState';

const PREFIX = '--floppy-';

// Live tokens are CSS variables on the document root, so a theme change repaints
// every already-rendered component, including module-level styles.
export function liveKeysFor() {
  return LIVE_KEYS;
}

export function themeColor(key, resolved) {
  if (LIVE_KEYS.includes(key)) return `var(${PREFIX}${key}, ${resolved.tokens[key]})`;
  return resolved.tokens[key];
}

export function applyPlatformTheme(resolved) {
  if (typeof document !== 'undefined') {
    const root = document.documentElement;
    LIVE_KEYS.forEach(key => root.style.setProperty(`${PREFIX}${key}`, resolved.tokens[key]));
    root.style.setProperty('color-scheme', resolved.scheme);
    root.style.setProperty('background-color', resolved.tokens.background);
  }
  if (typeof Appearance.setColorScheme === 'function') Appearance.setColorScheme(resolved.override);
}
