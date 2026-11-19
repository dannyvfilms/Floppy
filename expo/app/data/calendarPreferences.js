import { File, Paths } from 'expo-file-system';

// One file per account so two people on a device keep their own filters.
function preferencesFile(userId) {
  return new File(Paths.document, `floppy-calendar-preferences-${userId || 'device'}.json`);
}

export async function readCalendarPreferences(userId) {
  try {
    const file = preferencesFile(userId);
    if (!file.exists) {
      return null;
    }
    const parsed = JSON.parse(await file.text());
    return parsed && typeof parsed === 'object' ? parsed : null;
  } catch (error) {
    return null;
  }
}

export async function writeCalendarPreferences(preferences, userId) {
  try {
    const file = preferencesFile(userId);
    if (!file.exists) {
      file.create({ intermediates: true });
    }
    await file.write(JSON.stringify(preferences));
  } catch (error) {
    // Storage is optional; the screen keeps working without it.
  }
}
