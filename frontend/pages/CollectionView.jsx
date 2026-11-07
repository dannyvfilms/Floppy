import React from 'react';
import { ActivityIndicator, StyleSheet, Text, View } from 'react-native';
import { Button } from '../ui/Button';
import { CollectionBrowser } from '../ui/CollectionBrowser';

// One collection composition for web and native. It owns the page heading,
// loading/error/retry and notice order; the existing CollectionBrowser keeps
// the search, filters, grid/rows/table and bounded load-more controls. Server
// copy dialogs and Django forms arrive through the `children` slot so the web
// adapter never has to duplicate presentation.

export const collectionLabels = {
  title: 'Collection',
  subtitle: 'Every copy you own, grouped and labelled',
  loading: 'Loading collection…',
  retry: 'Try again',
  error: 'The collection could not be loaded.',
  notice: '',
};

export function CollectionView({
  title,
  subtitle,
  items = [],
  groups = null,
  filters = {},
  options = {},
  labels = {},
  palette = {},
  busy = false,
  chrome = true,
  resultCount,
  hasMore = false,
  loadingMore = false,
  tableColumns,
  loading = false,
  error = '',
  notice = '',
  onRetry,
  onFilterChange,
  onOpenCopy,
  onLoadMore,
  onLoadMoreGroup,
  renderCard,
  header,
  footer,
  children,
}) {
  const copy = { ...collectionLabels, ...(labels || {}) };
  const heading = title === undefined ? copy.title : title;
  const subheading = subtitle === undefined ? copy.subtitle : subtitle;
  return <View style={styles.root}>
    {header || null}
    {heading ? <Text accessibilityRole="header" style={[styles.title, { color: palette.text || '#fafafa' }]}>{heading}</Text> : null}
    {subheading ? <Text style={[styles.subtitle, { color: palette.textMuted || '#a1a1aa' }]}>{subheading}</Text> : null}
    {error ? <View style={[styles.notice, { borderColor: palette.danger || '#ef4444' }]}>
      <Text accessibilityLiveRegion="polite" style={[styles.noticeText, { color: palette.danger || '#ef4444' }]}>{error || copy.error}</Text>
      {onRetry ? <Button label={copy.retry} tone="surface" palette={palette} onPress={onRetry} /> : null}
    </View> : null}
    {loading ? <View accessibilityLiveRegion="polite" style={styles.loading}>
      <ActivityIndicator color={palette.accent || '#6366f1'} />
      <Text style={[styles.loadingText, { color: palette.textMuted || '#a1a1aa' }]}>{copy.loading}</Text>
    </View> : <CollectionBrowser
      items={items}
      groups={groups}
      filters={filters}
      options={options}
      labels={labels}
      palette={palette}
      busy={busy}
      chrome={chrome}
      resultCount={resultCount}
      hasMore={hasMore}
      loadingMore={loadingMore}
      tableColumns={tableColumns}
      onFilterChange={onFilterChange}
      onOpenCopy={onOpenCopy}
      onLoadMore={onLoadMore}
      onLoadMoreGroup={onLoadMoreGroup}
      renderCard={renderCard} />}
    {notice ? <Text accessibilityLiveRegion="polite" style={[styles.noticeText, { color: palette.textMuted || '#a1a1aa' }]}>{notice}</Text> : null}
    {footer || null}
    {children || null}
  </View>;
}

const styles = StyleSheet.create({
  root: { gap: 12, minWidth: 0 },
  title: { fontSize: 28, lineHeight: 34, fontWeight: '700' },
  subtitle: { fontSize: 13, lineHeight: 19 },
  notice: { gap: 8, borderWidth: 1, borderRadius: 8, padding: 12, alignItems: 'flex-start' },
  noticeText: { fontSize: 13, lineHeight: 18 },
  loading: { alignItems: 'center', justifyContent: 'center', gap: 10, paddingVertical: 48 },
  loadingText: { fontSize: 13 },
});
