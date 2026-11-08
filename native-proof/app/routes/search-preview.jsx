import React from 'react';
import { Platform, Text, View } from 'react-native';
import SearchSlot from '../surfaces/SearchSlot';
import { palette } from '../theme';

// Review-only route (EXPO_PUBLIC_SEARCH_PREVIEW=1): the real SearchSlot without a
// signed-in session, so scope and barcode behavior can be captured in a browser
// export or Expo Go. `?type=manga` (web) picks the starting scope.
function startingType() {
  if (Platform.OS !== 'web' || typeof window === 'undefined') return 'all';
  return new URLSearchParams(window.location.search).get('type') || 'all';
}

export default function SearchPreview() {
  const type = startingType();
  return <View style={{ flex: 1, backgroundColor: palette.background, padding: 16, paddingTop: 64 }}>
    <Text style={{ color: palette.textMuted, marginBottom: 8 }}>Search preview: {type}</Text>
    <SearchSlot expanded initialMediaType={type} />
  </View>;
}
