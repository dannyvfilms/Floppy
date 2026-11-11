import { readStoredTheme, writeStoredTheme } from './data/themeStorage';
import { getThemeSetting, setThemeSetting } from './themeState';

// Applies a theme the user just chose (or the server reported) to the running
// app and remembers it for the next launch.
export function applyThemeSetting(setting) {
  setThemeSetting(setting);
  return writeStoredTheme(getThemeSetting());
}

// Appearance payload from /api/v1/user/appearance/ or a preferences save.
export function applyServerTheme({ theme, palette } = {}) {
  return applyThemeSetting({ theme, custom: palette });
}

export async function restoreStoredTheme() {
  const stored = await readStoredTheme();
  if (stored?.theme) setThemeSetting(stored);
}
