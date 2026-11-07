import React from 'react';
import { StyleSheet, View } from 'react-native';

// One list-detail composition for web and native. The page owns the order of
// the list header, notices, smart-rule editor, search/filter controls, the
// tier board or item results and the membership dialogs. Callers supply those
// regions as slots so transport, editing state and the server-owned table stay
// in the platform adapter while the hierarchy stays shared.
export function ListDetailPageView({
  header,
  notice,
  smart,
  controls,
  content,
  dialogs,
  footer,
  style,
  testID,
}) {
  return <View style={[styles.root, style]} testID={testID}>
    {header || null}
    {notice || null}
    {smart || null}
    {controls || null}
    {content || null}
    {dialogs || null}
    {footer || null}
  </View>;
}

const styles = StyleSheet.create({
  root: { gap: 16, minWidth: 0 },
});
