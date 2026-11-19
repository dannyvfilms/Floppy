import * as ImagePicker from 'expo-image-picker';

// Lets the person choose a picture for a cover. Resolves { uri, base64 } or
// null when cancelled or access is denied. Browser version: imagePicker.web.js.
export async function pickCoverImage() {
  const permission = await ImagePicker.requestMediaLibraryPermissionsAsync();
  if (!permission.granted) return null;
  const result = await ImagePicker.launchImageLibraryAsync({
    mediaTypes: ['images'],
    base64: true,
    quality: 0.9,
  });
  const asset = !result.canceled && result.assets && result.assets[0];
  if (!asset || !asset.base64) return null;
  return { uri: asset.uri, base64: asset.base64 };
}
