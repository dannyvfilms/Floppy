import { File, Paths } from 'expo-file-system';

const PREFERENCES_FILE = 'floppy-calendar-preferences.json';

function preferencesFile() {
  return new File(Paths.document, PREFERENCES_FILE);
}

export async function readCalendarPreferences() {
  try {
    const file = preferencesFile();
    if (!file.exists) {
      return null;
    }
    const parsed = JSON.parse(await file.text());
    return parsed && typeof parsed === 'object' ? parsed : null;
  } catch (error) {
    return null;
  }
}

export async function writeCalendarPreferences(preferences) {
  try {
    const file = preferencesFile();
    if (!file.exists) {
      file.create({ intermediates: true });
    }
    await file.write(JSON.stringify(preferences));
  } catch (error) {
    // Storage is optional; the screen keeps working without it.
  }
}
