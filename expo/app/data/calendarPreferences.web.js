const storageKey = userId => `floppy:calendar-preferences:v1:${userId || 'device'}`;

export async function readCalendarPreferences(userId) {
  try {
    const stored = localStorage.getItem(storageKey(userId));
    if (!stored) {
      return null;
    }
    const parsed = JSON.parse(stored);
    return parsed && typeof parsed === 'object' ? parsed : null;
  } catch (error) {
    return null;
  }
}

export async function writeCalendarPreferences(preferences, userId) {
  try {
    localStorage.setItem(storageKey(userId), JSON.stringify(preferences));
  } catch (error) {
    // Storage is optional; the screen keeps working without it.
  }
}
