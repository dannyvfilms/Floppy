import React from 'react';
import { ActivityIndicator, StyleSheet, Text, View } from 'react-native';
import { Button } from '../ui/Button';
import { Rail } from '../ui/Rail';
import {
  CreditCard,
  MediaGallery,
  MediumExtras,
  PersonCard,
  PersonHero,
  StudioHero,
} from '../ui/People';

// One People/studio composition for web and native. Section order is shared:
// hero, watched credits, filmography/bibliography, cast, crew, gallery and
// medium extras. The web page mounts the same view in `hero`, `cast` and
// `extras` parts over its server fallback; the native screen mounts `full`.
// Demo profile selection and the lightbox overlay stay in the native adapter.

export const peopleLabels = {
  loading: 'Loading profile…',
  retry: 'Try again',
  error: 'The profile could not be loaded.',
  watchedContent: 'Watched Content',
  readContent: 'Read Content',
  filmography: 'Filmography',
  bibliography: 'Bibliography',
  cast: 'Cast',
  crew: 'Crew',
  trailers: 'Trailers and photos',
  mediumExtras: 'Medium extras',
  noWatched: 'No watched titles yet.',
  noRead: 'No read titles yet.',
  noFilmography: 'No filmography available.',
  noBibliography: 'No bibliography available.',
  noCast: 'No cast available.',
  noCrew: 'No crew available.',
  noTitles: 'No titles available.',
};

function countLabel(count, singular, plural) {
  return count === 1 ? `1 ${singular}` : `${count} ${plural}`;
}

export function PeopleView({
  part = 'full',
  kind = 'person',
  person = {},
  studio = {},
  counts = [],
  labels = {},
  palette = {},
  watched = [],
  filmography = [],
  cast = [],
  crew = [],
  gallery = [],
  galleryTitle = '',
  watchedTitle,
  creditsTitle,
  gameLengths,
  youtubeWatch,
  reading,
  isAuthor = false,
  showBiography = true,
  canViewHistory = true,
  headingLevel = 1,
  sourcePlacement = 'facts',
  actionPalette,
  web = false,
  title,
  items = [],
  collapsed,
  onCollapsedChange,
  collapsible = false,
  viewAll,
  railWidth = 176,
  castWidth = 132,
  loading = false,
  error = '',
  onRetry,
  onOpenSource,
  onOpenWebsite,
  onViewHistory,
  onOpenCredit,
  onOpenPerson,
  onPlayGallery,
  onOpenLightbox,
  onOpenExtra,
  children,
}) {
  const copy = { ...peopleLabels, ...(labels || {}) };
  const colors = palette || {};
  const showHero = part === 'full' || part === 'hero';
  const showCredits = part === 'full';
  const showCast = part === 'full' || part === 'cast';
  const showExtras = part === 'full' || part === 'extras';

  const hero = kind === 'studio'
    ? <StudioHero
      studio={studio}
      counts={counts}
      labels={labels}
      palette={colors}
      headingLevel={headingLevel}
      sourcePlacement={sourcePlacement}
      showBiography={showBiography}
      onOpenWebsite={onOpenWebsite} />
    : <PersonHero
      person={person}
      counts={counts}
      labels={labels}
      palette={colors}
      headingLevel={headingLevel}
      showBiography={showBiography}
      canViewHistory={canViewHistory}
      actionPalette={actionPalette}
      onOpenSource={onOpenSource}
      onViewHistory={onViewHistory} />;

  const watchedHeading = watchedTitle || (isAuthor ? copy.readContent : copy.watchedContent);
  const creditsHeading = creditsTitle || (isAuthor ? copy.bibliography : copy.filmography);
  const railPalette = {
    ...colors,
    surfaceHover: colors.surfaceStrong || colors.surfaceHover,
    arrow: colors.textSecondary,
    arrowDisabled: colors.surfaceMuted,
    loading: colors.accent,
  };

  return <View style={styles.root}>
    {error ? <View style={[styles.notice, { borderColor: colors.danger || '#ef4444' }]}>
      <Text accessibilityLiveRegion="polite" style={[styles.noticeText, { color: colors.danger || '#ef4444' }]}>{error || copy.error}</Text>
      {onRetry ? <Button label={copy.retry} tone="surface" palette={colors} onPress={onRetry} /> : null}
    </View> : null}
    {loading ? <View accessibilityLiveRegion="polite" style={styles.loading}>
      <ActivityIndicator color={colors.accent || '#6366f1'} />
      <Text style={[styles.loadingText, { color: colors.textMuted || '#a1a1aa' }]}>{copy.loading}</Text>
    </View> : null}
    {!loading && showHero ? hero : null}
    {!loading && showCredits && watched.length ? <Rail items={watched}
      renderItem={entry => <CreditCard entry={entry} labels={labels} palette={colors} onOpen={onOpenCredit} />}
      title={`${watchedHeading}${title ? ` · ${title}` : ''}`}
      summary={countLabel(watched.length, 'title', 'titles')}
      itemWidth={railWidth}
      emptyLabel={isAuthor ? copy.noRead : copy.noWatched}
      palette={railPalette} /> : null}
    {!loading && showCredits && filmography.length ? <Rail items={filmography}
      renderItem={entry => <CreditCard entry={entry} labels={labels} palette={colors} onOpen={onOpenCredit} />}
      title={`${creditsHeading}${title ? ` · ${title}` : ''}`}
      summary={countLabel(filmography.length, 'title', 'titles')}
      summaryInline="Most recent" itemWidth={railWidth}
      emptyLabel={isAuthor ? copy.noBibliography : copy.noFilmography}
      palette={railPalette} /> : null}
    {!loading && showCredits && cast.length ? <Rail items={cast}
      renderItem={member => <PersonCard person={member} labels={labels} palette={colors} onOpen={onOpenPerson} />}
      title={`${copy.cast}${title ? ` · ${title}` : ''}`}
      summary={countLabel(cast.length, 'person', 'people')}
      itemWidth={castWidth}
      emptyLabel={copy.noCast}
      palette={railPalette} /> : null}
    {!loading && showCredits && crew.length ? <Rail items={crew}
      renderItem={member => <PersonCard person={member} labels={labels} palette={colors} onOpen={onOpenPerson} />}
      title={`${copy.crew}${title ? ` · ${title}` : ''}`}
      summary={countLabel(crew.length, 'person', 'people')}
      itemWidth={castWidth}
      emptyLabel={copy.noCrew}
      palette={railPalette} /> : null}
    {!loading && showCast && !showCredits ? <Rail items={items}
      renderItem={entry => <PersonCard person={entry} web={web} labels={labels} palette={colors}
        onOpen={onOpenPerson} />}
      title={title || copy.cast}
      itemWidth={castWidth}
      viewAll={viewAll}
      collapsible={collapsible}
      collapsed={collapsed}
      onCollapsedChange={onCollapsedChange}
      palette={railPalette} /> : null}
    {!loading && showExtras && gallery.length ? <View style={styles.section}>
      <Text accessibilityRole="header" style={[styles.sectionTitle, { color: colors.text || '#fafafa' }]}>{copy.trailers}</Text>
      {galleryTitle ? <Text style={[styles.sectionCopy, { color: colors.textMuted || '#a1a1aa' }]}>{galleryTitle}</Text> : null}
      <MediaGallery items={gallery} labels={labels} palette={colors}
        onPlay={onPlayGallery} onOpenLightbox={onOpenLightbox} />
    </View> : null}
    {!loading && showExtras && (gameLengths || youtubeWatch || reading) ? <View style={styles.section}>
      <Text accessibilityRole="header" style={[styles.sectionTitle, { color: colors.text || '#fafafa' }]}>{copy.mediumExtras}</Text>
      <MediumExtras gameLengths={gameLengths} youtubeWatch={youtubeWatch} reading={reading}
        labels={labels} palette={colors}
        onOpenSource={onOpenSource} onOpenItem={onOpenExtra} />
    </View> : null}
    {children || null}
  </View>;
}

const styles = StyleSheet.create({
  root: { gap: 24, minWidth: 0 },
  section: { gap: 10 },
  sectionTitle: { fontSize: 20, lineHeight: 26, fontWeight: '700' },
  sectionCopy: { fontSize: 13, lineHeight: 19 },
  notice: { gap: 8, borderWidth: 1, borderRadius: 8, padding: 12, alignItems: 'flex-start' },
  noticeText: { fontSize: 13, lineHeight: 18 },
  loading: { alignItems: 'center', justifyContent: 'center', gap: 10, paddingVertical: 48 },
  loadingText: { fontSize: 13 },
});
