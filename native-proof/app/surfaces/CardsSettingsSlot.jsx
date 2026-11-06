import React, { useState } from 'react';
import { StyleSheet, View } from 'react-native';
import { CardsEditor } from '../../../frontend/settings/CardsEditor';
import { SettingsCard } from '../../../frontend/settings/SettingsCard';
import { palette, radius, spacing } from '../theme';

export const surface = {
  id: 'SET-CARDS',
  title: 'Media card layout editor',
  where: 'Settings media cards per-type line selection, order and preview',
  status: 'in_progress',
  note: 'Every media type in users.card_metadata.editor_catalog() renders from the shared React Native CardsEditor with per-type line visibility, field and line ordering, add/remove, type copy/reset/defaults, title and rating options, a profile-driven card preview and the shared dirty/saving/error save bar. Saved profiles mirror the server defaults plus tuned types so the demo opens clean and the preview changes with each type. Demo saves stay local: native credential transport and on-device interaction remain unverified.',
};

const settingsPalette = {
  text: palette.text,
  textSecondary: palette.textSecondary,
  textMuted: palette.textMuted,
  border: palette.border,
  background: palette.surface,
  surface: palette.surface,
  surfaceStrong: palette.surfaceStrong,
  surfaceMuted: palette.surfaceMuted,
  accent: palette.accent,
  accentStrong: palette.accentStrong,
  accentText: '#ffffff',
  warning: palette.warning,
  danger: palette.danger,
  badgeBorder: palette.surfaceMuted,
  badgeBackground: palette.surfaceStrong,
  badgeText: palette.textSecondary,
  badgeHover: palette.surfaceMuted,
  focusStyle: {},
};

const buttonPalette = {
  primary: { background: palette.accentStrong, pressed: '#4338ca', hovered: '#4338ca', text: '#ffffff', border: 'transparent' },
  surface: { background: palette.surfaceStrong, pressed: palette.surfaceMuted, hovered: palette.surfaceMuted, text: palette.text, border: palette.border },
  radius: radius.sm,
  focusStyle: {},
};

// Mirrors the labels in users.card_metadata.CARD_FIELDS.
const fieldLabels = {
  release_year: 'Release year',
  episode_code: 'Season and episode',
  genres: 'Genres',
  platforms: 'Platform',
  runtime: 'Runtime',
  progress: 'Progress',
  series_position: 'Series position',
  status: 'Status',
  rating: 'Score',
  last_played: 'Last played',
  date_added: 'Date added',
  start_date: 'Start date',
  end_date: 'End date',
  synopsis: 'Synopsis',
  artist: 'Artist',
  album: 'Album',
  track_number: 'Track number',
  show_name: 'Show',
  author: 'Author',
  role: 'Role',
};

// Mirrors editor_catalog(): media types in server order, each with the fields
// users.card_metadata.field_types() allows, in registry order.
const typeFields = {
  tv: ['release_year', 'episode_code', 'genres', 'runtime', 'progress', 'status', 'rating', 'last_played', 'date_added', 'start_date', 'end_date', 'synopsis'],
  season: ['release_year', 'episode_code', 'genres', 'runtime', 'progress', 'status', 'rating', 'last_played', 'date_added', 'start_date', 'end_date', 'synopsis', 'show_name'],
  episode: ['release_year', 'episode_code', 'genres', 'runtime', 'progress', 'status', 'rating', 'last_played', 'date_added', 'start_date', 'end_date', 'synopsis', 'show_name'],
  movie: ['release_year', 'genres', 'runtime', 'progress', 'status', 'rating', 'last_played', 'date_added', 'start_date', 'end_date', 'synopsis'],
  anime: ['release_year', 'genres', 'runtime', 'progress', 'status', 'rating', 'last_played', 'date_added', 'start_date', 'end_date', 'synopsis'],
  manga: ['release_year', 'genres', 'runtime', 'progress', 'status', 'rating', 'last_played', 'date_added', 'start_date', 'end_date', 'synopsis', 'author'],
  game: ['release_year', 'genres', 'platforms', 'runtime', 'progress', 'status', 'rating', 'last_played', 'date_added', 'start_date', 'end_date', 'synopsis'],
  book: ['release_year', 'genres', 'runtime', 'progress', 'series_position', 'status', 'rating', 'last_played', 'date_added', 'start_date', 'end_date', 'synopsis', 'author'],
  comic: ['release_year', 'genres', 'runtime', 'progress', 'status', 'rating', 'last_played', 'date_added', 'start_date', 'end_date', 'synopsis', 'author'],
  comicissue: ['release_year', 'genres', 'runtime', 'progress', 'status', 'rating', 'last_played', 'date_added', 'start_date', 'end_date', 'synopsis', 'author'],
  boardgame: ['release_year', 'genres', 'runtime', 'progress', 'status', 'rating', 'last_played', 'date_added', 'start_date', 'end_date', 'synopsis'],
  music: ['release_year', 'genres', 'runtime', 'progress', 'status', 'rating', 'last_played', 'date_added', 'start_date', 'end_date', 'synopsis', 'artist', 'album', 'track_number'],
  podcast: ['release_year', 'genres', 'runtime', 'progress', 'status', 'rating', 'last_played', 'date_added', 'start_date', 'end_date', 'synopsis'],
  video: ['release_year', 'genres', 'runtime', 'progress', 'status', 'rating', 'last_played', 'date_added', 'start_date', 'end_date', 'synopsis'],
  person: ['role'],
};

// Mirrors users.card_metadata.type_label().
const typeLabels = {
  tv: 'TV Show',
  season: 'TV Season',
  episode: 'Episode',
  movie: 'Movie',
  anime: 'Anime',
  manga: 'Manga',
  game: 'Game',
  book: 'Book',
  comic: 'Comic',
  comicissue: 'Comic Issue',
  boardgame: 'Board Game',
  music: 'Music',
  podcast: 'Podcast',
  video: 'Video',
  person: 'Person',
};

const catalog = Object.keys(typeFields).map(id => ({
  id,
  label: typeLabels[id],
  fields: typeFields[id].map(fieldId => ({ id: fieldId, label: fieldLabels[fieldId] })),
}));

const defaultRating = { hide_zero: false, show: true };
const defaultTitle = { overflow: 'ellipsis', lines: 1, hover: 'bleed', hover_lines: 3 };

// Mirrors users.card_metadata.default_profile(): each default field gets its own
// hover line; episodes and the global preference columns start empty.
const defaultTypeFields = {
  tv: ['release_year', 'progress'],
  season: ['release_year', 'progress'],
  episode: [],
  movie: ['release_year', 'progress'],
  anime: ['release_year', 'progress'],
  manga: ['release_year', 'progress'],
  game: ['release_year', 'progress'],
  book: ['release_year', 'series_position', 'progress'],
  comic: ['release_year', 'progress'],
  comicissue: ['release_year', 'progress'],
  boardgame: ['release_year', 'progress'],
  music: ['artist', 'release_year'],
  podcast: ['release_year', 'progress'],
  video: ['release_year', 'progress'],
  person: ['role'],
};

// A saved account that already tuned a few types: multi-property lines, one
// always-visible progress line, a wrapped title, hidden ratings and a bare card.
const tunedProfiles = {
  movie: {
    lines: [
      { fields: ['genres', 'runtime'], display: 'hover' },
      { fields: ['progress'], display: 'dormant' },
      { fields: ['release_year', 'status'], display: 'hover' },
    ],
    rating: { hide_zero: true },
    title: { lines: 2, hover_lines: 3 },
  },
  tv: {
    lines: [
      { fields: ['episode_code'], display: 'hover' },
      { fields: ['progress'], display: 'dormant' },
      { fields: ['status', 'rating'], display: 'hover' },
    ],
    title: { hover_lines: 2 },
  },
  episode: {
    lines: [
      { fields: ['show_name', 'episode_code'], display: 'hover' },
      { fields: ['last_played'], display: 'hover' },
    ],
  },
  game: {
    lines: [
      { fields: ['platforms'], display: 'hover' },
      { fields: ['progress'], display: 'dormant' },
      { fields: ['release_year', 'rating'], display: 'hover' },
    ],
  },
  book: {
    lines: [
      { fields: ['release_year', 'series_position'], display: 'hover' },
      { fields: ['progress'], display: 'dormant' },
      { fields: ['author'], display: 'hover' },
    ],
    rating: { hide_zero: true },
  },
  music: {
    lines: [
      { fields: ['artist', 'album'], display: 'hover' },
      { fields: ['track_number', 'release_year'], display: 'hover' },
    ],
    rating: { show: false },
    title: { hover: 'stay', hover_lines: 1 },
  },
  video: {
    lines: [],
    title: { overflow: 'wrap', lines: 2, hover_lines: 3 },
  },
};

function buildProfile(typeId) {
  const tuned = tunedProfiles[typeId] || {};
  const lines = tuned.lines
    ? tuned.lines.map(line => ({ fields: [...line.fields], display: line.display }))
    : (defaultTypeFields[typeId] || []).map(fieldId => ({ fields: [fieldId], display: 'hover' }));
  return {
    display: 'hover',
    lines,
    fields: lines.flatMap(line => line.fields),
    options: {
      rating: { ...defaultRating, ...(tuned.rating || {}) },
      title: { ...defaultTitle, ...(tuned.title || {}) },
    },
  };
}

function buildProfiles() {
  return Object.fromEntries(catalog.map(entry => [entry.id, buildProfile(entry.id)]));
}

// Two builds so the editor's baseline stays a separate snapshot of the same state.
const savedProfiles = buildProfiles();
const baselineProfiles = buildProfiles();

function wait(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

export default function CardsSettingsSlot() {
  const [values, setValues] = useState({ saved: savedProfiles, touchActions: false });
  const [savedValues, setSavedValues] = useState({ saved: baselineProfiles, touchActions: false });

  async function save({ values: submitted }) {
    await wait(450);
    setSavedValues({ saved: submitted.saved, touchActions: submitted.touchActions });
  }

  return <SettingsCard title="Media Cards" palette={settingsPalette}>
    <View style={styles.form}>
      <CardsEditor
        catalog={catalog}
        saved={values.saved}
        initialSaved={savedValues.saved}
        active="tv"
        touchActions={values.touchActions}
        onChange={setValues}
        onSave={save}
        palette={settingsPalette}
        buttonPalette={buttonPalette}
      />
    </View>
  </SettingsCard>;
}

const styles = StyleSheet.create({
  form: { gap: spacing.sm },
});
