import React from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { actionIcons } from '../ui/actionIcons';
import { Button } from '../ui/Button';
import { FilterBar } from '../ui/FilterBar';
import { PageHeading, PageState } from './PageChrome';

// English fallbacks; the server's page model sends the translated copy.
export const animeSeasonsLabels = {
  title: 'Anime Seasons',
  subtitle: 'Seasonal anime from MyAnimeList.',
  countLabel: 'anime',
  previous: 'Previous season',
  next: 'Next season',
  openSettings: 'Open MyAnimeList settings',
  loading: 'Loading the season…',
  errorTitle: 'This season could not be loaded',
  errorBody: 'Please try again.',
};

// One Anime Seasons page for web and native, in the media list's order: the
// heading with its count and the season stepper, the filter toolbar, the
// states, then the cards. `page` is the server's page model (app.anime_seasons);
// the adapter supplies the cards as `content`, the theme and the navigation.
export function AnimeSeasonsPageView({
  page,
  status,
  labels,
  palette = {},
  content,
  busy = false,
  onChange,
  onStep,
  onOpenSettings,
  onRetry,
  style,
  testID,
}) {
  const text = { ...animeSeasonsLabels, ...(page?.labels || {}), ...(labels || {}) };
  const state = status || page?.state || 'loading';
  const settled = state === 'ready' || state === 'empty';
  const error = state === 'error' ? page?.error : null;
  // The shared Button reads a tone as an object; the page palette holds plain colours.
  const buttons = {
    surface: {
      background: palette.surface, pressed: palette.surfaceStrong, hovered: palette.surfaceStrong,
      text: palette.text, border: palette.border,
    },
    primary: {
      background: palette.accent, pressed: palette.accentStrong || palette.accent,
      hovered: palette.accentStrong || palette.accent, text: palette.accentText, border: 'transparent',
    },
  };
  const step = (target, label, icon) => <Button tone="surface" icon={icon} palette={buttons}
    accessibilityLabel={target ? `${label}: ${target.label}` : label}
    disabled={!target || busy} onPress={() => onStep?.(target)} />;
  return <View style={[styles.root, style]} testID={testID}>
    <PageHeading title={text.title} subtitle={text.subtitle} palette={palette}
      count={settled ? page?.count : undefined} countLabel={text.countLabel}
      actions={page ? <View style={styles.stepper}>
        {step(page.previous, text.previous, actionIcons.chevronLeft)}
        <Text role="heading" aria-level={2} style={[styles.season, { color: palette.text }]}>
          {page.season?.label}
        </Text>
        {step(page.next, text.next, actionIcons.chevronRight)}
      </View> : null} />
    {page ? <FilterBar variant="toolbar" filters={page.filters} options={page.options} labels={text}
      palette={palette} busy={busy} onChange={onChange} /> : null}
    <PageState state={state} labels={text} palette={palette} empty={page?.empty}
      error={error ? { title: error.title, body: error.body } : undefined}
      onRetry={error?.settingsUrl ? undefined : onRetry} />
    {error?.settingsUrl ? <Button label={text.openSettings} palette={buttons}
      onPress={() => onOpenSettings?.(error.settingsUrl)} /> : null}
    {state === 'ready' ? content : null}
  </View>;
}

const styles = StyleSheet.create({
  root: { gap: 16, minWidth: 0 },
  stepper: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  season: { minWidth: 112, textAlign: 'center', fontSize: 18, lineHeight: 24, fontWeight: '600' },
});
