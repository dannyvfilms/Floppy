import { File, Paths } from 'expo-file-system';

const THEME_FILE = 'floppy-theme.json';

// The last theme the signed-in user chose, kept so the app opens in it before
// the server answers. The server stays the source of truth.
export async function readStoredTheme() {
  try {
    const file = new File(Paths.document, THEME_FILE);
    if (!file.exists) return null;
    const parsed = JSON.parse(await file.text());
    return parsed && typeof parsed === 'object' ? parsed : null;
  } catch {
    return null;
  }
}

export async function writeStoredTheme(setting) {
  try {
    const file = new File(Paths.document, THEME_FILE);
    if (!file.exists) file.create({ intermediates: true });
    await file.write(JSON.stringify(setting));
  } catch {
    // Storage is optional; the theme still applies for this run.
  }
}
