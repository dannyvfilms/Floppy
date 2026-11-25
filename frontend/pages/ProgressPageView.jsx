import React from 'react';
import { StyleSheet, View } from 'react-native';
import { Button } from '../ui/Button';
import { FilterBar } from '../ui/FilterBar';
import { ProgressDialog } from '../ui/ProgressDialog';
import { ProgressShowCard } from '../ui/ProgressShowCard';
import { PageHeading, PageState } from './PageChrome';
import { progressSorts, progressStatuses } from './useProgressPage';

export const progressPageLabels = {
  title: 'Progress',
  loadMore: 'Load more',
  loading: 'Loading your shows…',
  emptyTitle: 'Nothing left to watch',
  emptyBody: 'Shows you are watching, with episodes left, appear here.',
  errorTitle: 'Progress could not be loaded',
  errorBody: 'Please try again.',
};

// Same labels the media list passes its toolbar, so the controls read alike.
const filterLabels = { filters: 'Filters', status: 'Status', allStatuses: 'Status', statuses: 'Statuses', sort: 'Sort' };
const filterOptions = { filters: false, statuses: progressStatuses, sorts: progressSorts };

// One Progress page for web and native. It follows the media list's order: the
// heading with its count, the filter toolbar, then the results. `page` is the
// useProgressPage state; the adapter supplies the transport, theme and navigation.
export function ProgressPageView({
  page,
  labels,
  palette = {},
  chrome = true,
  onOpenShow,
  onOpenEpisode,
  onOpenSeasonOrEpisode,
  style,
  testID,
}) {
  const text = { ...progressPageLabels, ...labels };
  const { dialog, summary } = page;
  const shows = summary?.shows;
  return <View style={[styles.root, style]} testID={testID}>
    {chrome ? <PageHeading title={text.title} subtitle={summary?.text}
      count={page.status === 'ready' || page.status === 'empty' ? shows : undefined}
      countLabel={shows === 1 ? 'show' : 'shows'} palette={palette} /> : null}
    <FilterBar variant="toolbar" showClear={false} filters={page.filters} options={filterOptions}
      labels={filterLabels} palette={palette} busy={page.status === 'loading'} onChange={page.changeFilter} />
    <PageState state={page.status === 'ready' ? 'ready' : page.status} labels={text} palette={palette}
      empty={{ title: text.emptyTitle, body: text.emptyBody }}
      error={{ title: text.errorTitle, body: text.errorBody }}
      onRetry={page.retry} />
    {page.status === 'ready' ? <View style={styles.list}>
      {page.rows.map(row => <ProgressShowCard key={row.id} row={row} palette={palette}
        seasons={page.seasons[row.id]} expanded={Boolean(page.expanded[row.id])}
        onOpen={page.openDialog} onOpenShow={onOpenShow} onOpenEpisode={onOpenEpisode}
        onToggleSeasons={page.toggleSeasons} />)}
      {page.hasMore ? <View style={styles.more}>
        <Button label={text.loadMore} tone="surface" palette={palette} busy={page.loadingMore} onPress={page.loadMore} />
      </View> : null}
    </View> : null}
    {dialog && dialog.status === 'ready' ? <ProgressDialog visible title={dialog.row.title}
      model={dialog.model} labels={dialog.model?.labels} palette={palette}
      onClose={page.closeDialog}
      onOpenSeason={href => { page.closeDialog(); onOpenSeasonOrEpisode?.(href); }}
      onOpenEpisode={href => { page.closeDialog(); onOpenSeasonOrEpisode?.(href); }} /> : null}
  </View>;
}

const styles = StyleSheet.create({
  root: { gap: 16, minWidth: 0 },
  list: { gap: 16 },
  more: { alignItems: 'center' },
});
