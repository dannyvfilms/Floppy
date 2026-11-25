import React from 'react';
import { ActivityIndicator, Pressable, Text, View } from 'react-native';
import { palette } from '../theme';

// Loading, signed-out and error (with Retry) states shared by every settings
// page. `state` is one of 'loading', 'signedOut', 'error'.
export default function SettingsLoadState({ state, message, onRetry }) {
  if (state === 'loading') {
    return <View accessibilityRole="progressbar" style={{ padding: 24, alignItems: 'center', gap: 8 }}>
      <ActivityIndicator color={palette.accent} />
      <Text style={{ color: palette.textMuted, fontSize: 13 }}>Loading settings</Text>
    </View>;
  }
  const signedOut = state === 'signedOut';
  return <View accessibilityRole="alert" style={{
    padding: 16, gap: 10, borderRadius: 8, borderWidth: 1,
    borderColor: signedOut ? palette.border : palette.danger, backgroundColor: palette.surface,
  }}>
    <Text style={{ color: signedOut ? palette.textSecondary : palette.danger, fontSize: 13, lineHeight: 19 }}>
      {signedOut ? 'Sign in to your Floppy server to manage settings.' : (message || 'Settings could not be loaded.')}
    </Text>
    {!signedOut && onRetry ? <Pressable accessibilityRole="button" onPress={onRetry}
      style={{
        alignSelf: 'flex-start', paddingVertical: 8, paddingHorizontal: 14, borderRadius: 6,
        backgroundColor: palette.accentStrong,
      }}>
      <Text style={{ color: palette.onAccentStrong, fontSize: 13, fontWeight: '600' }}>Retry</Text>
    </Pressable> : null}
  </View>;
}

// Maps a transport failure to the state a page shows.
export function loadFailure(error) {
  return error?.code === 'signed_out'
    ? { state: 'signedOut', message: '' }
    : { state: 'error', message: error?.message || '' };
}
