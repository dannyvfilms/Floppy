import { Clipboard } from 'react-native';

/** Native clipboard adapter. Expo and React Native keep the same copy intent;
 * physical-device clipboard behavior remains unverified by the export check. */
export async function copyText(text) {
  await Clipboard.setString(text ?? '');
  return true;
}
