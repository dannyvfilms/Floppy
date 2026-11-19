import React, { useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { Badge } from '../ui/Badge';
import { ListCard } from '../ui/ListCard';
import { TextField } from '../ui/TextField';
import { PageHeading, PageState } from './PageChrome';

// One Lists hub composition for web and native. The heading and list actions,
// search, tag filter, list-card grid and the empty/loading/error states keep one
// order. Platform slots carry the create/import flows (web modals, native
// dialogs) and per-card tools whose transport differs by platform.
export function ListsPageView({
  title = 'Lists',
  subtitle,
  labels = {},
  palette = {},
  actions,
  heading,
  search,
  searchValue = '',
  searchPlaceholder,
  onSearchChange,
  tags = [],
  activeTag = 'All',
  onSelectTag,
  lists = [],
  renderListTools,
  onOpenList,
  onListAction,
  hideCardMetadata = false,
  state = 'ready',
  empty,
  error,
  onRetry,
  onEmptyAction,
  dialogs,
  content,
  footer,
  style,
  testID,
}) {
  // A list card fills the row on a phone and stops growing on wide screens.
  const [blockWidth, setBlockWidth] = useState(0);
  const cardWidth = blockWidth ? Math.min(blockWidth, 480) : 240;
  const chipPalette = {
    ...palette,
    tagActive: { color: '#ffffff', backgroundColor: palette.accentStrong || palette.accent || '#4f46e5' },
    tagIdle: {
      color: palette.textSecondary || '#d4d4d8',
      borderColor: palette.surfaceMuted || '#52525b',
      borderWidth: 1,
    },
  };
  return <View style={[styles.root, style]} testID={testID}>
    {heading || <PageHeading title={title} subtitle={subtitle} actions={actions} palette={palette} />}
    {search || (onSearchChange ? <TextField
      label={labels.search || 'Search lists'}
      labelHidden
      value={searchValue}
      placeholder={searchPlaceholder || labels.searchPlaceholder || 'Search lists...'}
      onChangeText={onSearchChange}
      palette={palette} /> : null)}
    {tags.length ? <View style={styles.tags}>
      {tags.map(tag => <Badge
        key={tag}
        label={tag}
        tone={tag === activeTag ? 'tagActive' : 'tagIdle'}
        palette={chipPalette}
        onPress={() => onSelectTag?.(tag)} />)}
    </View> : null}
    <PageState
      state={state}
      labels={labels}
      palette={palette}
      empty={empty}
      error={error}
      onRetry={onRetry}
      onEmptyAction={onEmptyAction} />
    {state === 'ready' ? (content || (lists.length ? <View style={styles.grid}>
      {lists.map(list => <View key={list.id} style={styles.cardBlock}
        onLayout={event => setBlockWidth(Math.floor(event.nativeEvent.layout.width))}>
        <ListCard
          list={list}
          palette={palette}
          width={cardWidth}
          hideMetadata={hideCardMetadata}
          onOpen={() => onOpenList?.(list)}
          onAction={action => onListAction?.(action, list)} />
        {renderListTools ? renderListTools(list) : null}
      </View>)}
    </View> : null)) : null}
    {dialogs || null}
    {footer || null}
  </View>;
}

const styles = StyleSheet.create({
  root: { gap: 16, minWidth: 0 },
  tags: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  grid: { flexDirection: 'row', flexWrap: 'wrap', gap: 16 },
  cardBlock: { gap: 8, flexGrow: 1, flexShrink: 0, flexBasis: 280, maxWidth: 480 },
});
