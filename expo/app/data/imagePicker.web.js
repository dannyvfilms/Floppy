// Browser file chooser for a cover (see imagePicker.js for the native version).
export function pickCoverImage() {
  return new Promise((resolve, reject) => {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = 'image/jpeg,image/png,image/webp';
    input.onchange = () => {
      const file = input.files && input.files[0];
      if (!file) { resolve(null); return; }
      const reader = new FileReader();
      reader.onload = () => {
        const text = String(reader.result || '');
        resolve({ uri: text, base64: text.split(',')[1] || '' });
      };
      reader.onerror = () => reject(reader.error);
      reader.readAsDataURL(file);
    };
    input.oncancel = () => resolve(null);
    input.click();
  });
}
