const PREFIX = 'floppy_';

export async function readLocalSetting(key) {
  try {
    return globalThis.localStorage?.getItem(`${PREFIX}${key}`) ?? null;
  } catch {
    return null;
  }
}

export async function writeLocalSetting(key, value) {
  try {
    globalThis.localStorage?.setItem(`${PREFIX}${key}`, String(value));
  } catch {
    // Storage can be unavailable (private windows).
  }
}
