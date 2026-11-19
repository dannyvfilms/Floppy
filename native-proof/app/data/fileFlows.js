import { File, Paths } from 'expo-file-system';
import * as Linking from 'expo-linking';
import { Share } from 'react-native';
import { bytesToBase64, importPickError, isBinaryImport } from './fileImportCore';

// Platform file flows for settings: export download, log download, backup
// import. Browser equivalents live in fileFlows.web.js.

// Writes text into the app cache and hands the file to the system viewer so the
// person can save or share it. Resolves with where it was written.
export async function saveTextFile({ name, text }) {
  const file = new File(Paths.cache, name);
  if (!file.exists) file.create({ intermediates: true });
  await file.write(text);
  try {
    await file.preview();
  } catch {
    try { await Linking.openURL(file.uri); } catch { /* the file is still on disk */ }
  }
  return { name, uri: file.uri };
}

// Lets the person choose a text file (CSV backup). Resolves null when cancelled.
export async function pickTextFile({ mimeTypes = ['text/csv', 'text/plain', '*/*'] } = {}) {
  const picked = await File.pickFileAsync({ mimeTypes });
  if (!picked || picked.canceled || !picked.result) return null;
  const file = picked.result;
  return { name: file.name, text: await file.text() };
}

// Lets the person choose a file to import (CSV, JSON or a zip). Checks the type and
// the 100 MB bound before reading; a zip is read as base64, text files as text.
// Resolves null when cancelled and throws a readable message when refused.
export async function pickImportFile({ accept = '' } = {}) {
  const picked = await File.pickFileAsync({ mimeTypes: ['*/*'] });
  if (!picked || picked.canceled || !picked.result) return null;
  const file = picked.result;
  const info = { name: file.name, size: file.size ?? 0 };
  const refused = importPickError(info, accept);
  if (refused) throw new Error(refused);
  if (isBinaryImport(file.name)) return { ...info, base64: bytesToBase64(await file.bytes()) };
  return { ...info, text: await file.text() };
}

// Copies through the system share sheet: no clipboard module ships with the app.
export async function copyText(text) {
  const result = await Share.share({ message: String(text) });
  return result?.action !== Share.dismissedAction;
}
