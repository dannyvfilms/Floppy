import { Appearance, DynamicColorIOS, Platform } from 'react-native';

// The accent for small text and arrows on a dark card, where a deep accent (indigo, purple) is hard to read:
// the same colour mixed 45% toward white in dark mode, unchanged in light mode. iOS follows the appearance
// by itself; elsewhere it reads the system appearance when the app starts, as themeColor does.
export function brightAccent(accent) {
  const hex = /^#([0-9a-f]{6})$/i.exec(accent || '');
  if (!hex) return accent;
  const bright = `#${[0, 2, 4].map(at => {
    const channel = parseInt(hex[1].slice(at, at + 2), 16);
    return Math.round(channel + (255 - channel) * 0.45).toString(16).padStart(2, '0');
  }).join('')}`;
  if (Platform.OS === 'ios') return DynamicColorIOS({ light: accent, dark: bright });
  return Appearance.getColorScheme?.() === 'dark' ? bright : accent;
}
