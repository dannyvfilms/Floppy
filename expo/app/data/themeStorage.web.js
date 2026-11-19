const KEY = 'floppy-theme';

export function readStoredThemeSync() {
  try {
    const parsed = JSON.parse(globalThis.localStorage?.getItem(KEY) || 'null');
    return parsed && typeof parsed === 'object' ? parsed : null;
  } catch {
    return null;
  }
}

export async function readStoredTheme() {
  return readStoredThemeSync();
}

export async function writeStoredTheme(setting) {
  try {
    globalThis.localStorage?.setItem(KEY, JSON.stringify(setting));
  } catch {
    // Storage can be unavailable (private windows); the theme still applies.
  }
}
