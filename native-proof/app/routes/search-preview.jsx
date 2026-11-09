import React from 'react';
import { Text, View } from 'react-native';
import { useLocalSearchParams } from 'expo-router';
import SearchSlot from '../surfaces/SearchSlot';
import { palette } from '../theme';

// Review-only route (EXPO_PUBLIC_SEARCH_PREVIEW=1): the real SearchSlot without a
// signed-in session, so scope and barcode behavior can be captured in a browser
// export or Expo Go. `?type=manga` picks the starting scope.
export default function SearchPreview() {
  const params = useLocalSearchParams();
  const type = (Array.isArray(params.type) ? params.type[0] : params.type) || 'all';
  return <View style={{ flex: 1, backgroundColor: palette.background, padding: 16, paddingTop: 64 }}>
    <Text style={{ color: palette.textMuted, marginBottom: 8 }}>Search preview: {type}</Text>
    <SearchSlot expanded initialMediaType={type} />
  </View>;
}
