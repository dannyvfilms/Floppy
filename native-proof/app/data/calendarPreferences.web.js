const STORAGE_KEY = 'floppy:calendar-preferences:v1';

export async function readCalendarPreferences() {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (!stored) {
      return null;
    }
    const parsed = JSON.parse(stored);
    return parsed && typeof parsed === 'object' ? parsed : null;
  } catch (error) {
    return null;
  }
}

export async function writeCalendarPreferences(preferences) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(preferences));
  } catch (error) {
    // Storage is optional; the screen keeps working without it.
  }
}
