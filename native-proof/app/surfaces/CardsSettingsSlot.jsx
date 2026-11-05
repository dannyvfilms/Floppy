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
  note: 'Per-media-type card lines, field order, visibility, title and rating options render from the shared React Native editor with a live preview and dirty/saving/error state. Native runtime interaction and a browser adapter remain unverified.',
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
  focusStyle: {},
};

const buttonPalette = {
  primary: { background: palette.accentStrong, pressed: '#4338ca', hovered: '#4338ca', text: '#ffffff', border: 'transparent' },
  surface: { background: palette.surfaceStrong, pressed: palette.surfaceMuted, hovered: palette.surfaceMuted, text: palette.text, border: palette.border },
  radius: radius.sm,
  focusStyle: {},
};

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

const typeFields = {
  movie: ['release_year', 'genres', 'runtime', 'progress', 'status', 'rating', 'last_played', 'date_added', 'synopsis'],
  tv: ['release_year', 'episode_code', 'progress', 'status', 'rating', 'last_played', 'date_added', 'synopsis'],
  anime: ['release_year', 'episode_code', 'progress', 'status', 'rating', 'last_played', 'date_added', 'synopsis'],
  season: ['episode_code', 'release_year', 'progress', 'status', 'rating', 'last_played', 'date_added', 'synopsis'],
  episode: ['episode_code', 'release_year', 'status', 'rating', 'last_played', 'synopsis'],
  book: ['release_year', 'series_position', 'progress', 'status', 'rating', 'author', 'date_added', 'synopsis'],
  comic: ['release_year', 'series_position', 'progress', 'status', 'rating', 'author', 'date_added', 'synopsis'],
  manga: ['release_year', 'series_position', 'progress', 'status', 'rating', 'author', 'date_added', 'synopsis'],
  game: ['release_year', 'platforms', 'progress', 'status', 'rating', 'last_played', 'date_added'],
  music: ['artist', 'album', 'track_number', 'release_year', 'rating', 'last_played', 'date_added'],
  podcast: ['release_year', 'progress', 'status', 'rating', 'last_played', 'date_added'],
  person: ['role'],
};

const typeLabels = {
  movie: 'Movies',
  tv: 'TV Shows',
  anime: 'Anime',
  season: 'Seasons',
  episode: 'Episodes',
  book: 'Books',
  comic: 'Comic Books',
  manga: 'Manga',
  game: 'Games',
  music: 'Music',
  podcast: 'Podcasts',
  person: 'People',
};

const catalog = Object.keys(typeFields).map(id => ({
  id,
  label: typeLabels[id],
  fields: typeFields[id].map(field => ({ id: field, label: fieldLabels[field] })),
}));

const lineSeeds = {
  movie: [['release_year'], ['genres', 'runtime'], ['progress']],
  tv: [['release_year'], ['progress', 'episode_code']],
  anime: [['release_year'], ['progress']],
  season: [['episode_code'], ['progress']],
  episode: [['episode_code'], ['last_played']],
  book: [['release_year'], ['series_position'], ['progress']],
  comic: [['release_year'], ['progress']],
  manga: [['release_year'], ['progress']],
  game: [['release_year'], ['progress']],
  music: [['artist'], ['album'], ['release_year']],
  podcast: [['release_year'], ['progress']],
  person: [['role']],
};

function defaultProfile(mediaType) {
  const lines = (lineSeeds[mediaType] || []).map((fields, index) => ({
    fields,
    display: index === 0 ? 'dormant' : 'hover',
  }));
  return {
    lines,
    fields: lines.flatMap(line => line.fields),
    options: {
      rating: { hide_zero: false, show: mediaType !== 'music' },
      title: { overflow: 'ellipsis', lines: 1, hover: 'bleed', hover_lines: 3 },
    },
  };
}

const saved = Object.fromEntries(Object.keys(typeFields).map(id => [id, defaultProfile(id)]));
const initialSaved = Object.fromEntries(Object.keys(typeFields).map(id => [id, defaultProfile(id)]));

function wait(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

export default function CardsSettingsSlot() {
  const [values, setValues] = useState({ saved, touchActions: false });
  const [savedValues, setSavedValues] = useState({ saved: initialSaved, touchActions: false });

  function change(next) {
    setValues({ saved: next.saved, touchActions: next.touchActions });
  }

  async function save({ values: submitted }) {
    await wait(450);
    setSavedValues({ saved: submitted.saved, touchActions: submitted.touchActions });
  }

  return <SettingsCard title="Media cards" palette={settingsPalette}>
    <View style={styles.form}>
      <CardsEditor
        catalog={catalog}
        saved={values.saved}
        initialSaved={savedValues.saved}
        active="movie"
        touchActions={values.touchActions}
        onChange={change}
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
