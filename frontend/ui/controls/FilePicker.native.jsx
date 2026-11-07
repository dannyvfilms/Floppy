import React from 'react';
import { View } from 'react-native';
import { FilePicker as SharedFilePicker } from './FilePicker.jsx';

/**
 * iOS and Android slot. The host app owns the platform picker and passes it as
 * the `pickFiles` adapter; the shared pressable never touches a file input.
 */
export function FilePicker(props) {
  return <View><SharedFilePicker {...props} /></View>;
}
