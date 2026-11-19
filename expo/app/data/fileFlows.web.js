import { bytesToBase64, importPickError, isBinaryImport } from './fileImportCore';

// Browser file flows for settings (see fileFlows.js for the native versions).

export async function saveTextFile({ name, text, mimeType = 'text/plain' }) {
  const blob = new Blob([text], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = name;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
  return { name, uri: '' };
}

export function pickTextFile({ accept = '.csv,text/csv,text/plain' } = {}) {
  return new Promise((resolve, reject) => {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = accept;
    input.hidden = true;
    document.body.appendChild(input);
    input.onchange = async () => {
      const file = input.files && input.files[0];
      try {
        if (!file) { resolve(null); return; }
        resolve({ name: file.name, text: await file.text() });
      } catch (error) {
        reject(error);
      } finally {
        input.remove();
      }
    };
    input.oncancel = () => { input.remove(); resolve(null); };
    try { input.click(); }
    catch (error) { input.remove(); reject(error); }
  });
}

export function pickImportFile({ accept = '' } = {}) {
  return new Promise((resolve, reject) => {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = accept;
    input.hidden = true;
    document.body.appendChild(input);
    input.onchange = async () => {
      const file = input.files && input.files[0];
      try {
        if (!file) { resolve(null); return; }
        const info = { name: file.name, size: file.size };
        const refused = importPickError(info, accept);
        if (refused) throw new Error(refused);
        resolve(isBinaryImport(file.name)
          ? { ...info, base64: bytesToBase64(new Uint8Array(await file.arrayBuffer())) }
          : { ...info, text: await file.text() });
      } catch (error) {
        reject(error);
      } finally {
        input.remove();
      }
    };
    input.oncancel = () => { input.remove(); resolve(null); };
    try { input.click(); }
    catch (error) { input.remove(); reject(error); }
  });
}

export async function copyText(text) {
  await navigator.clipboard.writeText(String(text));
  return true;
}
