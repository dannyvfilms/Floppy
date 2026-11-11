import { File, Paths } from 'expo-file-system';

const FILE = 'floppy-local-settings.json';

// Per-device state that is not account data, such as the last release notice
// the person dismissed (the browser keeps it in localStorage).
async function readAll() {
  try {
    const file = new File(Paths.document, FILE);
    if (!file.exists) return {};
    const parsed = JSON.parse(await file.text());
    return parsed && typeof parsed === 'object' ? parsed : {};
  } catch {
    return {};
  }
}

export async function readLocalSetting(key) {
  const all = await readAll();
  return key in all ? all[key] : null;
}

export async function writeLocalSetting(key, value) {
  try {
    const file = new File(Paths.document, FILE);
    if (!file.exists) file.create({ intermediates: true });
    await file.write(JSON.stringify({ ...(await readAll()), [key]: value }));
  } catch {
    // Optional state; the notice simply shows again next time.
  }
}
