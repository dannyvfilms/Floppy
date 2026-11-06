import React from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { Badge } from '../../../frontend/ui/Badge';
import { palette, spacing } from '../theme';
import { getActiveAuthSession } from '../data/authSession';

export const surface = {
  id: 'DETAIL',
  status: 'ported',
  title: 'Detail composition and metadata',
  where: 'Film, show, game, book, music and podcast detail pages',
  note: 'Hero artwork, title facts, synopsis, primary actions, configurable sections and public/read-only states use the shared DetailComposition through the shared DetailView section order. Rating, progress, children rows, tracking dialogs and the provider graph stay separate.',
};

const labels = {
  altTitle: 'Show alternative title',
  publicView: 'Public view',
  readMore: 'Read more',
  showLess: 'Show less',
  noSynopsis: 'No synopsis available.',
};

const detailPalette = {
  background: palette.background,
  surface: palette.surface,
  surfaceStrong: palette.surfaceStrong,
  border: palette.border,
  text: palette.text,
  textSecondary: palette.textSecondary,
  textMuted: palette.textMuted,
  accent: palette.accent,
  accentStrong: palette.accentStrong,
  accentContrast: '#ffffff',
  link: '#818cf8',
  danger: palette.danger,
  placeholder: palette.surfaceStrong,
};

const genres = ['Science fiction', 'Drama', 'Mystery'];
const providers = ['Northline', 'Cinder+', 'Rent or buy'];

const synopsis = 'After the relay at Halcyon Station goes dark, Mira Chen returns to the outer ring to find the crew she left behind. The signal she follows is not a distress call but a recording of her own voice, dated six years in the future. As the station’s orbit decays, the crew must decide whether to trust the message or the woman who delivered it.';

function GenreBadges() {
  return <View style={styles.badgeRow}>
    {genres.map(genre => <Badge key={genre} label={genre} tone="outline"
      palette={{ outline: { color: palette.textSecondary, borderColor: palette.surfaceMuted, borderWidth: 1 } }} />)}
  </View>;
}

function ProviderList() {
  return <View style={styles.providerList}>
    {providers.map(provider => <Text key={provider} style={styles.provider}>{provider}</Text>)}
  </View>;
}

// Production-shaped detail model for the native proof. The shared DetailView
// owns section order, labels and states; this factory only supplies values.
function createDetailModel() {
  return {
    title: 'The Quiet Orbit',
    altTitle: 'La órbita silenciosa',
    subtitle: 'Season 2',
    publicView: false,
    readOnly: false,
    artwork: {
      src: 'https://picsum.photos/seed/floppy-orbit-detail/400/600',
      alt: 'The Quiet Orbit',
      aspect: 'poster',
    },
    facts: [
      { label: 'Year', value: '2024' },
      { label: 'Runtime', value: '52m' },
      { label: 'Episodes', value: '10' },
      { label: 'Status', value: 'Returning series' },
    ],
    synopsis: { text: synopsis, previewLines: 3 },
    labels,
    palette: detailPalette,
    actions: {
      primary: { label: 'Continue watching', tone: 'primary' },
      items: [{ label: 'Add to library', tone: 'surface' }],
    },
    sections: [
      { id: 'genres', title: 'Genres', body: <GenreBadges /> },
      { id: 'providers', title: 'Where to watch', body: <ProviderList /> },
    ],
  };
}


function identityFromItem(item) {
  if (item?.identity?.mediaId) {
    return {
      mediaType: item.identity.mediaType,
      source: item.identity.source,
      mediaId: item.identity.mediaId,
    };
  }
  const match = String(item?.href || '').match(/^\/details\/([^/]+)\/([^/]+)\/([^/]+)/);
  return match ? { source: match[1], mediaType: match[2], mediaId: match[3] } : null;
}

function factList(fields) {
  const facts = [];
  const year = String(fields.release_datetime || '').slice(0, 4);
  if (year) facts.push({ label: 'Year', value: year });
  if (fields.runtime_minutes) facts.push({ label: 'Runtime', value: `${fields.runtime_minutes}m` });
  if (fields.status) facts.push({ label: 'Status', value: fields.status });
  if (fields.format) facts.push({ label: 'Format', value: fields.format });
  return facts;
}

function genreNames(fields) {
  if (Array.isArray(fields.genres)) return fields.genres.filter(Boolean);
  return fields.genres ? [String(fields.genres)] : [];
}

// A card-only model is still real data from the row the viewer tapped; it is
// what the detail page shows while metadata loads or when the item is untracked.
export function createDetailModelForItem(item) {
  return {
    title: item?.title || 'Detail',
    subtitle: '',
    publicView: false,
    readOnly: false,
    artwork: {
      src: item?.image?.src || '',
      alt: item?.title || 'Detail',
      aspect: 'poster',
    },
    facts: [],
    synopsis: null,
    labels,
    palette: detailPalette,
    actions: null,
    sections: [],
  };
}

export async function loadDetailModel(item) {
  const identity = identityFromItem(item);
  const auth = getActiveAuthSession();
  if (!identity || typeof auth?.request !== 'function') return createDetailModelForItem(item);
  const payload = await auth.request(
    `/api/v1/media/${encodeURIComponent(identity.mediaType)}/${encodeURIComponent(identity.source)}/${encodeURIComponent(identity.mediaId)}/metadata/`,
  );
  const fields = payload?.fields || {};
  const genres = genreNames(fields);
  const studios = Array.isArray(fields.studios) ? fields.studios.filter(Boolean) : [];
  return {
    title: fields.title || item?.title || 'Detail',
    subtitle: fields.original_title && fields.original_title !== fields.title ? fields.original_title : '',
    publicView: false,
    readOnly: false,
    artwork: {
      src: fields.image || item?.image?.src || '',
      alt: fields.title || item?.title || 'Detail',
      aspect: 'poster',
    },
    facts: factList(fields),
    synopsis: fields.synopsis ? { text: fields.synopsis, previewLines: 3 } : null,
    labels,
    palette: detailPalette,
    actions: null,
    sections: [
      genres.length ? {
        id: 'genres',
        title: 'Genres',
        body: <View style={styles.badgeRow}>
          {genres.map(genre => <Badge key={genre} label={genre} tone="outline"
            palette={{ outline: { color: palette.textSecondary, borderColor: palette.surfaceMuted, borderWidth: 1 } }} />)}
        </View>,
      } : null,
      studios.length ? {
        id: 'providers',
        title: 'Studios',
        body: <View style={styles.providerList}>
          {studios.map(studio => <Text key={studio} style={styles.provider}>{studio}</Text>)}
        </View>,
      } : null,
    ].filter(Boolean),
  };
}

const styles = StyleSheet.create({
  badgeRow: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm },
  providerList: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.md },
  provider: { color: palette.textSecondary, fontSize: 13, fontWeight: '500' },
});
