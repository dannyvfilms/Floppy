import React from 'react';
import { StyleSheet, View } from 'react-native';

// One Search page composition for web and native.
//
// `search` is the platform search field (web uses the global search chrome and
// passes nothing; native passes its shared search field). `results` is the
// shared `SearchResults` surface, which owns the title, scope and layout
// controls, notes, sections, paging and the empty/loading/error states. The
// page order therefore stays identical on both platforms.
export function SearchPageView({
  search,
  results,
  footer,
  testID,
}) {
  return <View style={styles.root} testID={testID}>
    {search || null}
    {results || null}
    {footer || null}
  </View>;
}

const styles = StyleSheet.create({
  root: { gap: 16, minWidth: 0 },
});
