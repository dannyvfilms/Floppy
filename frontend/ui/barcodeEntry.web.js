export function requestBarcode({ labels = {} } = {}) {
  return new Promise((resolve, reject) => {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = 'image/*';
    input.style.display = 'none';
    document.body.appendChild(input);
    let settled = false;
    const finish = (callback) => {
      if (settled) return;
      settled = true;
      input.remove();
      callback();
    };
    input.addEventListener('change', async () => {
      const file = input.files?.[0];
      if (!file) {
        finish(() => resolve({ status: 'cancelled' }));
        return;
      }
      try {
        if (!window.barcodeScannerUtils) throw new Error(labels.barcodeNotLoaded);
        const isbn = await window.barcodeScannerUtils.decodeBarcodeFromFile(file);
        finish(() => resolve(isbn ? { status: 'decoded', isbn } : { status: 'unreadable' }));
      } catch (error) {
        finish(() => reject(error));
      }
    });
    input.addEventListener('cancel', () => finish(() => resolve({ status: 'cancelled' })));
    input.click();
  });
}
