import React, { useState } from 'react';
import { StyleSheet, View } from 'react-native';
import { HomeScreenEditor } from '../../../frontend/settings/HomeScreenEditor';
import { SettingsCard } from '../../../frontend/settings/SettingsCard';
import { palette, radius, spacing } from '../theme';

export const surface = {
  id: 'SET-HOME',
  title: 'Home screen shelf editor',
  where: 'Settings home screen sections, rows, filters, sort and order',
  status: 'in_progress',
  note: 'Home sections, ordered library/Up Next/List rows, filters, sort/direction, chip colors, header and label visibility render from the shared React Native editor with realistic demo state and local validation/error handling. Blocked on native runtime interaction (iOS/Android) and a browser adapter: the Django page still uses Alpine/SortableJS, drag ordering is replaced by move buttons, and header/label toggles cannot mark the shared form dirty until the editor baseline tracks saved values.',
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

const statusOptions = [
  { value: 'all', label: 'All' },
  { value: 'In progress', label: 'In Progress' },
  { value: 'Completed', label: 'Completed' },
  { value: 'Planning', label: 'Planning' },
  { value: 'Paused', label: 'Paused' },
  { value: 'Dropped', label: 'Dropped' },
];

const progressOptions = [
  { value: 'caught_up', label: 'Caught Up' },
  { value: 'not_caught_up', label: 'Not Caught Up' },
];

const ratingOptions = [
  { value: 'rated', label: 'Rated' },
  { value: 'not_rated', label: 'Not Rated' },
];

const collectionOptions = [
  { value: 'collected', label: 'Collected' },
  { value: 'not_collected', label: 'Not Collected' },
];

const releaseOptions = [
  { value: 'released', label: 'Released' },
  { value: 'not_released', label: 'Not Released' },
];

const genreOptions = ['Drama', 'Comedy', 'Science fiction', 'Adventure', 'Pop'].map(value => ({ value, label: value }));
const yearOptions = ['2026', '2025', '2024', '2023'].map(value => ({ value, label: value }));
const languageOptions = ['English', 'Japanese', 'Spanish', 'French'].map(value => ({ value, label: value }));
const countryOptions = ['United States', 'United Kingdom', 'Japan', 'France'].map(value => ({ value, label: value }));
const providerOptions = ['Netflix', 'Max', 'Disney Plus', 'Apple TV Plus'].map(value => ({ value, label: value }));
const tagOptions = ['favorite', 'rewatch', 'halloween'].map(value => ({ value, label: value }));

const sourceOptions = [
  { value: 'tmdb', label: 'The Movie Database' },
  { value: 'tvdb', label: 'TheTVDB' },
  { value: 'musicbrainz', label: 'MusicBrainz' },
  { value: 'manual', label: 'Manual' },
];

const subviewOptions = [
  { value: 'artists', label: 'Artists' },
  { value: 'albums', label: 'Albums' },
  { value: 'tracks', label: 'Tracks' },
];

const mediaTypeOptions = [
  { value: 'movie', label: 'Movies' },
  {
    value: 'tv',
    label: 'TV Shows',
    subviews: [
      { value: 'shows', label: 'Shows' },
      { value: 'seasons', label: 'Seasons' },
      { value: 'episodes', label: 'Episodes' },
    ],
    default_subview: 'shows',
  },
  { value: 'music', label: 'Music', subviews: subviewOptions, default_subview: 'tracks' },
  { value: 'book', label: 'Books' },
];

const homeOnlySorts = [
  { value: 'upcoming', label: 'Upcoming' },
  { value: 'recent', label: 'Recent' },
  { value: 'completion', label: 'Completion' },
  { value: 'episodes_left', label: 'Episodes Left' },
];

const allSorts = [
  { value: 'recent', label: 'Recent' },
  { value: 'end_date', label: 'Last Watched' },
  { value: 'title', label: 'Title' },
  { value: 'score', label: 'Rating' },
  { value: 'date_added', label: 'Date Added' },
  { value: 'random', label: 'Random' },
];

const upNextSorts = [
  { value: 'episode_feed', label: 'Up Next' },
  { value: 'title', label: 'Title' },
  { value: 'score', label: 'Rating' },
  { value: 'date_added', label: 'Date Added' },
  { value: 'end_date', label: 'Last Watched' },
  { value: 'random', label: 'Random' },
];

const mediaSorts = [
  { value: 'score', label: 'Rating' },
  { value: 'title', label: 'Title' },
  { value: 'progress', label: 'Progress' },
  { value: 'release_date', label: 'Release Date' },
  { value: 'date_added', label: 'Date Added' },
  { value: 'start_date', label: 'Start Date' },
  { value: 'end_date', label: 'Last Watched' },
  { value: 'critic_rating', label: 'Critic Rating' },
  { value: 'popularity', label: 'Popularity' },
  { value: 'runtime', label: 'Runtime' },
  { value: 'time_watched', label: 'Time Watched' },
  { value: 'plays', label: 'Plays' },
];

const movieSorts = [...mediaSorts, ...homeOnlySorts, { value: 'random', label: 'Random' }];

const tvSorts = [
  ...mediaSorts.slice(0, 4),
  { value: 'next_episode_air_date', label: 'Episode Air Date' },
  ...mediaSorts.slice(4),
  { value: 'time_left', label: 'Time Left' },
  ...homeOnlySorts,
  { value: 'random', label: 'Random' },
];

const musicSorts = [
  { value: 'score', label: 'Rating' },
  { value: 'title', label: 'Title' },
  { value: 'progress', label: 'Progress' },
  { value: 'release_date', label: 'Release Date' },
  { value: 'date_added', label: 'Date Added' },
  { value: 'start_date', label: 'Start Date' },
  { value: 'end_date', label: 'Last Listened' },
  ...homeOnlySorts,
  { value: 'random', label: 'Random' },
];

function customListSorts(choices) {
  return choices.filter(choice => !homeOnlySorts.some(home => home.value === choice.value));
}

const statusField = { key: 'status', label: 'Status', options: statusOptions };
const progressField = { key: 'progress', label: 'Progress', options: progressOptions };
const ratingField = { key: 'rating', label: 'Rating', options: ratingOptions };
const collectionField = { key: 'collection', label: 'Collection', options: collectionOptions };
const genreField = { key: 'genre', label: 'Genre', options: genreOptions };
const yearField = { key: 'year', label: 'Year', options: yearOptions };
const releaseField = { key: 'release', label: 'Release', options: releaseOptions };
const sourceField = { key: 'source', label: 'Source', options: sourceOptions };
const languageField = { key: 'language', label: 'Language', options: languageOptions };
const countryField = { key: 'country', label: 'Country', options: countryOptions };
const providerField = { key: 'provider', label: 'Streaming Service', options: providerOptions };
const tagField = { key: 'tag', label: 'Tag', options: tagOptions };
const subviewField = { key: 'subview', label: 'Media Type', options: subviewOptions };
const mediaTypesField = { key: 'media_types', label: 'Media types', options: mediaTypeOptions };

function filterFields(mediaType) {
  if (mediaType === 'all') {
    return [mediaTypesField, statusField, progressField, ratingField, collectionField, releaseField, tagField];
  }
  const fields = [];
  if (mediaType === 'music') fields.push(subviewField);
  fields.push(statusField);
  if (mediaType === 'tv') fields.push(progressField);
  fields.push(ratingField, collectionField, genreField, yearField, releaseField, sourceField);
  if (mediaType === 'movie' || mediaType === 'tv') fields.push(languageField, countryField, providerField);
  fields.push(tagField);
  return fields;
}

const sections = [
  {
    media_type: 'all',
    label: 'All media',
    available_media_types: ['movie', 'tv', 'music', 'book'],
    sort_choices: { library_query: allSorts, custom_list: allSorts, up_next: upNextSorts },
    filter_fields: filterFields('all'),
    rows: [
      {
        id: 11,
        client_id: 'row-11',
        enabled: true,
        row_type: 'library_query',
        custom_title: 'Continue watching',
        custom_list_id: null,
        custom_list_name: '',
        sort_by: 'recent',
        direction: 'desc',
        recent_show: 'album',
        filters: {
          status: ['In progress'],
          media_types: ['movie', 'tv'],
          media_subviews: { tv: 'shows', music: 'tracks' },
          progress: 'not_caught_up',
          rating: 'all',
          collection: 'all',
          release: 'all',
          tag: [],
          tag_mode: 'or',
        },
      },
      {
        id: 12,
        client_id: 'row-12',
        enabled: true,
        row_type: 'up_next',
        custom_title: 'Up next',
        custom_list_id: null,
        custom_list_name: '',
        sort_by: 'episode_feed',
        direction: 'asc',
        recent_show: 'album',
        filters: {},
      },
    ],
  },
  {
    media_type: 'movie',
    label: 'Movies',
    available_media_types: [],
    sort_choices: { library_query: movieSorts, custom_list: customListSorts(movieSorts), up_next: upNextSorts },
    filter_fields: filterFields('movie'),
    media_type_chip_color: '#F97316',
    rows: [
      {
        id: 21,
        client_id: 'row-21',
        enabled: true,
        row_type: 'library_query',
        custom_title: 'Science fiction picks',
        custom_list_id: null,
        custom_list_name: '',
        sort_by: 'date_added',
        direction: 'desc',
        recent_show: 'album',
        filters: {
          status: ['In progress'],
          rating: 'rated',
          collection: 'collected',
          genre: 'Science fiction',
          year: '2026',
          release: 'released',
          source: 'tmdb',
          language: 'English',
          country: 'United States',
          provider: 'Netflix',
          tag: ['favorite'],
          tag_mode: 'or',
        },
      },
      {
        id: 22,
        client_id: 'row-22',
        enabled: true,
        row_type: 'custom_list',
        custom_title: 'Weekend picks',
        custom_list_id: 11,
        custom_list_name: 'Weekend picks',
        sort_by: 'title',
        direction: 'asc',
        recent_show: 'album',
        filters: {},
      },
    ],
  },
  {
    media_type: 'tv',
    label: 'TV Shows',
    available_media_types: [],
    sort_choices: { library_query: tvSorts, custom_list: customListSorts(tvSorts), up_next: upNextSorts },
    filter_fields: filterFields('tv'),
    media_type_chip_color: '#10B981',
    rows: [
      {
        id: 31,
        client_id: 'row-31',
        enabled: true,
        row_type: 'library_query',
        custom_title: 'Currently watching',
        custom_list_id: null,
        custom_list_name: '',
        sort_by: 'next_episode_air_date',
        direction: 'desc',
        recent_show: 'album',
        filters: {
          status: ['In progress'],
          progress: 'not_caught_up',
          rating: 'all',
          collection: 'all',
          genre: 'Drama',
          year: '',
          release: 'all',
          source: 'tvdb',
          language: 'English',
          country: 'United States',
          provider: 'Max',
          tag: ['rewatch'],
          tag_mode: 'or',
        },
      },
      {
        id: 32,
        client_id: 'row-32',
        enabled: true,
        row_type: 'up_next',
        custom_title: 'Next episodes',
        custom_list_id: null,
        custom_list_name: '',
        sort_by: 'episode_feed',
        direction: 'asc',
        recent_show: 'album',
        filters: {},
      },
    ],
  },
  {
    media_type: 'music',
    label: 'Music',
    available_media_types: [],
    sort_choices: { library_query: musicSorts, custom_list: customListSorts(musicSorts), up_next: upNextSorts },
    filter_fields: filterFields('music'),
    media_type_chip_color: '#FB7185',
    rows: [
      {
        id: 41,
        client_id: 'row-41',
        enabled: true,
        row_type: 'recently_unrated',
        custom_title: 'Recently played',
        custom_list_id: null,
        custom_list_name: '',
        sort_by: 'recent',
        direction: 'desc',
        recent_show: 'album',
        filters: {},
      },
      {
        id: 42,
        client_id: 'row-42',
        enabled: true,
        row_type: 'library_query',
        custom_title: 'Albums in rotation',
        custom_list_id: null,
        custom_list_name: '',
        sort_by: 'end_date',
        direction: 'desc',
        recent_show: 'album',
        filters: {
          subview: 'albums',
          status: ['In progress'],
          rating: 'not_rated',
          collection: 'collected',
          genre: 'Pop',
          release: 'released',
          source: 'musicbrainz',
          tag: [],
          tag_mode: 'or',
        },
      },
    ],
  },
];

const listChoices = [
  { id: 11, name: 'Weekend picks', is_smart: false, label: 'Weekend picks (List)' },
  { id: 12, name: 'Short films', is_smart: true, label: 'Short films (Smart list)' },
  { id: 13, name: 'Science fiction', is_smart: false, label: 'Science fiction (List)' },
];

const mediaTypeChipStyles = [
  { value: 'solid', label: 'Solid' },
  { value: 'soft', label: 'Soft' },
  { value: 'outline', label: 'Outline' },
];

function wait(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

export default function HomeSettingsSlot() {
  const [values, setValues] = useState({
    sections,
    showMediaTypeHeaders: false,
    mediaTypeChipsEnabled: true,
    mediaTypeChipStyle: 'soft',
  });
  const [savedValues, setSavedValues] = useState({
    sections,
    showMediaTypeHeaders: false,
    mediaTypeChipsEnabled: true,
    mediaTypeChipStyle: 'soft',
  });

  async function save({ values: submitted }) {
    await wait(450);
    setSavedValues(submitted);
  }

  return <SettingsCard title="Home Screen" palette={settingsPalette}>
    <View style={styles.form}>
      <HomeScreenEditor
        sections={values.sections}
        initialSections={savedValues.sections}
        listChoices={listChoices}
        mediaTypeChipStyles={mediaTypeChipStyles}
        showMediaTypeHeaders={values.showMediaTypeHeaders}
        mediaTypeChipsEnabled={values.mediaTypeChipsEnabled}
        mediaTypeChipStyle={values.mediaTypeChipStyle}
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
