// Pure rules for importing a picked file, shared by the native and web pickers
// and mirrored by the server (api.fork_views_providers: 100 MiB, extension list).
export const MAX_IMPORT_BYTES = 100 * 1024 * 1024;

const extensionOf = name => {
  const match = /\.[^./\\]+$/.exec(String(name || '').toLowerCase());
  return match ? match[0] : '';
};

export const isBinaryImport = name => extensionOf(name) === '.zip';

// Returns an error message, or '' when the file may be sent.
export function importPickError({ name, size }, accept = '') {
  const allowed = String(accept || '').split(',').map(part => part.trim().toLowerCase()).filter(part => part.startsWith('.'));
  if (!name) return 'Choose a file to import.';
  if (allowed.length && !allowed.includes(extensionOf(name))) return `Choose a ${allowed.join(', ')} file.`;
  if (!size) return 'That file is empty.';
  if (size > MAX_IMPORT_BYTES) {
    return `That file is ${(size / (1024 * 1024)).toFixed(0)} MB. The limit is ${MAX_IMPORT_BYTES / (1024 * 1024)} MB.`;
  }
  return '';
}

export function formatBytes(size) {
  if (!Number.isFinite(size) || size < 0) return '';
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / (1024 * 1024)).toFixed(1)} MB`;
}

const ALPHABET = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/';

// Base64 without btoa or Buffer so it runs on Hermes and in tests alike.
export function bytesToBase64(bytes) {
  let out = '';
  for (let index = 0; index < bytes.length; index += 3) {
    const a = bytes[index];
    const b = bytes[index + 1];
    const c = bytes[index + 2];
    const triple = (a << 16) | ((b ?? 0) << 8) | (c ?? 0);
    out += ALPHABET[(triple >> 18) & 63] + ALPHABET[(triple >> 12) & 63]
      + (b === undefined ? '=' : ALPHABET[(triple >> 6) & 63])
      + (c === undefined ? '=' : ALPHABET[triple & 63]);
  }
  return out;
}
