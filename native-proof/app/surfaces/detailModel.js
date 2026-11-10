import { badgePalette, mediaCardPalette, palette, ratingPalette } from '../theme';
import {
  detailModelFromPayloads,
  identityFromItem,
  mediaPath,
} from '../data/detailTransportCore';
import { loadDetailPage } from '../data/detailTransport';

export const surface = {
  id: 'DETAIL',
  status: 'ported',
  title: 'Detail composition and metadata',
  where: 'Film, show, season, episode, game, book, music and podcast detail pages',
  note: 'The phone-width detail page (poster hero, track and quick actions, rating and provider scores, synopsis, history, Details, Genres, Where to watch, Collection, notes, seasons and episodes, cast, crew, recommendations) runs on the media detail, metadata, state, history, collection and Seerr endpoints. Native runtime on iOS and Android is not verified.',
};

export { detailModelFromPayloads, identityFromItem, loadDetailPage, mediaPath };

const accentContrast = badgePalette.indigo.color;

const buttonTones = {
  primary: {
    background: palette.accentStrong,
    pressed: palette.accent,
    hovered: palette.accent,
    text: accentContrast,
    border: palette.accentStrong,
  },
  surface: {
    background: palette.surfaceStrong,
    pressed: palette.surfaceMuted,
    hovered: palette.surfaceMuted,
    text: palette.text,
    border: palette.border,
  },
  'danger-solid': {
    background: palette.danger,
    pressed: palette.danger,
    hovered: palette.danger,
    text: accentContrast,
    border: palette.danger,
  },
  'ghost-danger': {
    background: 'transparent',
    pressed: palette.surfaceStrong,
    hovered: palette.surfaceStrong,
    text: palette.danger,
    border: 'transparent',
  },
  radius: 8,
};

// One palette for every shared detail component. Each color comes from the
// theme tokens, so the iOS appearance and the web theme states still apply.
export const detailPagePalette = {
  ...palette,
  accentContrast,
  heroText: accentContrast,
  // The web score cards tint their fill and border with one accent per source.
  scoreAccents: {
    provider: { fill: 'rgba(34, 211, 238, 0.10)', border: 'rgba(34, 211, 238, 0.26)' },
    trakt: { fill: 'rgba(251, 113, 133, 0.10)', border: 'rgba(251, 113, 133, 0.26)' },
    imdb: { fill: 'rgba(251, 191, 36, 0.10)', border: 'rgba(251, 191, 36, 0.26)' },
    mal: { fill: 'rgba(129, 140, 248, 0.10)', border: 'rgba(129, 140, 248, 0.26)' },
    opencritic: { fill: 'rgba(251, 146, 60, 0.10)', border: 'rgba(251, 146, 60, 0.26)' },
  },
  surfaceBorder: palette.border,
  placeholder: palette.surfaceStrong,
  mediaCard: mediaCardPalette,
  rating: { ...ratingPalette, focusStyle: {} },
  progress: {
    surface: palette.surface,
    surfaceMuted: palette.surfaceMuted,
    fill: palette.success,
    text: palette.text,
    textMuted: palette.textMuted,
  },
  button: buttonTones,
};

export const detailSlotPalette = detailPagePalette;

// A card-only model is still real data from the row the viewer tapped; it is
// what the page shows while the detail loads or if the load fails.
export function createDetailModelForItem(item) {
  return detailModelFromPayloads({ item, identity: identityFromItem(item) });
}
