import React from 'react';
import { StyleSheet, View } from 'react-native';
import { PageHeading, PageState } from './PageChrome';

// One library/media-list composition for web and native.
//
// The server table and Alpine filter form remain the web platform
// implementation of `content`/`filterForm`; native passes the shared
// `MediaTable` and filter slots. The page owns the order of the heading,
// filters, selection toolbar, grouping banner, table/grid area and bulk bar,
// plus the loading, empty and error states.
export function LibraryPageView({
  title = 'Library',
  subtitle,
  count,
  countLabel,
  labels = {},
  palette = {},
  search,
  heading,
  headerActions,
  filterForm,
  filters,
  selection,
  groupBanner,
  content,
  footer,
  bulkBar,
  state = 'ready',
  empty,
  error,
  onRetry,
  onEmptyAction,
  style,
  testID,
}) {
  return <View style={[styles.root, style]} testID={testID}>
    {search || null}
    {heading || <PageHeading
      title={title}
      subtitle={subtitle}
      count={count}
      countLabel={countLabel}
      actions={headerActions}
      palette={palette} />}
    {filterForm || null}
    {filters || null}
    {selection || null}
    {groupBanner || null}
    <PageState
      state={state}
      labels={labels}
      palette={palette}
      empty={empty}
      error={error}
      onRetry={onRetry}
      onEmptyAction={onEmptyAction} />
    {state === 'ready' ? content : null}
    {bulkBar || null}
    {footer || null}
  </View>;
}

const styles = StyleSheet.create({
  root: { gap: 16, minWidth: 0 },
});
