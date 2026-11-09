import { scanFromURLAsync } from 'expo-camera';
import * as ImagePicker from 'expo-image-picker';

// Retail and book barcodes use EAN-13/UPC-A. A book can also carry a two- or
// five-digit price supplement, which scanFromURLAsync returns as extra text.
export const BARCODE_TYPES = ['ean13', 'ean8', 'upc_a', 'upc_e'];

function computeIsbn13CheckDigit(isbn12) {
  let sum = 0;
  for (let i = 0; i < isbn12.length; i += 1) {
    const digit = Number.parseInt(isbn12[i], 10);
    if (Number.isNaN(digit)) return null;
    sum += digit * (i % 2 === 0 ? 1 : 3);
  }
  return (10 - (sum % 10)) % 10;
}

function computeIsbn10CheckDigit(isbn9) {
  let sum = 0;
  for (let i = 0; i < 9; i += 1) {
    const digit = Number.parseInt(isbn9[i], 10);
    if (Number.isNaN(digit)) return null;
    sum += digit * (10 - i);
  }
  return (11 - (sum % 11)) % 11;
}

export function normalizeIsbn(code) {
  if (!code) return null;

  const cleaned = String(code).replace(/[^0-9X]/gi, '').toUpperCase();

  if (cleaned.length === 10) {
    const isbn9 = cleaned.slice(0, 9);
    if (!/^\d{9}$/.test(isbn9)) return null;
    const provided = cleaned[9] === 'X' ? 10 : Number.parseInt(cleaned[9], 10);
    if (provided !== computeIsbn10CheckDigit(isbn9)) return null;
    const isbn12 = `978${isbn9}`;
    const checkDigit = computeIsbn13CheckDigit(isbn12);
    return checkDigit === null ? null : `${isbn12}${checkDigit}`;
  }

  if (cleaned.length > 13) {
    const candidate = cleaned.slice(0, 13);
    return candidate.startsWith('978') || candidate.startsWith('979') ? candidate : null;
  }

  if (cleaned.length === 13) {
    return cleaned.startsWith('978') || cleaned.startsWith('979') ? cleaned : null;
  }

  return null;
}

function isbnFromResults(results) {
  for (const result of results || []) {
    const isbn = normalizeIsbn(result?.data);
    if (isbn) return isbn;
  }
  return null;
}

export async function scanBarcodeImage(uri) {
  const results = await scanFromURLAsync(uri, BARCODE_TYPES);
  return isbnFromResults(results);
}

export async function pickBarcodePhoto() {
  const result = await ImagePicker.launchImageLibraryAsync({
    mediaTypes: ['images'],
    allowsMultipleSelection: false,
    quality: 1,
  });
  if (result.canceled || !result.assets?.length) {
    return { status: 'cancelled' };
  }
  try {
    const isbn = await scanBarcodeImage(result.assets[0].uri);
    return isbn ? { status: 'decoded', isbn } : { status: 'unreadable' };
  } catch (error) {
    return { status: 'unreadable' };
  }
}

// The shared contract used by the search field. On native, requestBarcode is
// the photo-library path; the live camera sheet calls scanBarcodeImage and
// normalizeIsbn directly so it can show permission, error and manual states.
export async function requestBarcode() {
  try {
    return await pickBarcodePhoto();
  } catch (error) {
    if (error?.message?.includes('permission')) {
      return { status: 'unavailable' };
    }
    throw error;
  }
}
