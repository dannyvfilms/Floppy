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
  note: 'Home sections, shelves, filters, sorting and ordering render from the shared React Native editor with local validation and dirty/saving/error state; list search results come from the caller. Native runtime interaction, drag-order parity and a browser adapter remain unverified.',
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
  { value: 'In progress', label: 'In progress' },
  { value: 'Planning', label: 'Planning' },
  { value: 'Paused', label: 'Paused' },
  { value: 'Completed', label: 'Completed' },
  { value: 'Dropped', label: 'Dropped' },
];

const librarySorts = [
  { value: 'title', label: 'Title' },
  { value: 'score', label: 'Rating' },
  { value: 'date_added', label: 'Date Added' },
  { value: 'end_date', label: 'Last Watched' },
  { value: 'random', label: 'Random' },
];

const upNextSorts = [
  { value: 'episode_feed', label: 'Up Next' },
  { value: 'title', label: 'Title' },
  { value: 'score', label: 'Rating' },
];

function filterFields(extra = {}) {
  return [
    { key: 'status', label: 'Status', options: statusOptions },
    { key: 'progress', label: 'Progress', options: [
      { value: 'not_caught_up', label: 'Not caught up' },
      { value: 'caught_up', label: 'Caught up' },
    ] },
    { key: 'rating', label: 'Rating', options: [
      { value: 'rated', label: 'Rated' },
      { value: 'unrated', label: 'Unrated' },
    ] },
    { key: 'collection', label: 'Collection', options: [
      { value: 'owned', label: 'Owned' },
      { value: 'wishlist', label: 'Wishlist' },
    ] },
    { key: 'genre', label: 'Genre', options: [
      { value: 'Drama', label: 'Drama' },
      { value: 'Comedy', label: 'Comedy' },
      { value: 'Science fiction', label: 'Science fiction' },
    ] },
    { key: 'year', label: 'Year', options: [
      { value: '2026', label: '2026' },
      { value: '2025', label: '2025' },
    ] },
    { key: 'tag', label: 'Tags', options: [
      { value: 'favorite', label: 'Favorite' },
      { value: 'rewatch', label: 'Rewatch' },
    ] },
    ...(extra.fields || []),
  ];
}

const sections = [
  {
    media_type: 'all',
    label: 'All media',
    available_media_types: ['movie', 'tv', 'music', 'book'],
    sort_choices: { library_query: librarySorts, custom_list: librarySorts, up_next: upNextSorts },
    filter_fields: filterFields({ fields: [
      { key: 'media_types', label: 'Media types', options: [
        { value: 'movie', label: 'Movies' },
        { value: 'tv', label: 'TV Shows', subviews: [{ value: 'shows', label: 'Shows' }, { value: 'episodes', label: 'Episodes' }], default_subview: 'shows' },
        { value: 'music', label: 'Music', subviews: [{ value: 'albums', label: 'Albums' }, { value: 'tracks', label: 'Tracks' }], default_subview: 'albums' },
        { value: 'book', label: 'Books' },
      ] },
    ] }),
    rows: [
      {
        id: 1,
        client_id: 'row-1',
        row_type: 'library_query',
        custom_title: '',
        custom_list_id: null,
        custom_list_name: '',
        sort_by: 'end_date',
        direction: 'desc',
        recent_show: 'album',
        filters: { status: ['In progress'], media_types: ['movie', 'tv'], progress: 'not_caught_up' },
      },
    ],
  },
  {
    media_type: 'movie',
    label: 'Movies',
    available_media_types: [],
    sort_choices: { library_query: librarySorts, custom_list: librarySorts, up_next: upNextSorts },
    filter_fields: filterFields(),
    rows: [
      {
        id: 2,
        client_id: 'row-2',
        row_type: 'library_query',
        custom_title: 'Continue watching',
        custom_list_id: null,
        custom_list_name: '',
        sort_by: 'title',
        direction: 'asc',
        recent_show: 'album',
        filters: { status: ['In progress'], progress: 'not_caught_up', rating: 'all', collection: 'owned' },
      },
    ],
  },
  {
    media_type: 'tv',
    label: 'TV Shows',
    available_media_types: [],
    sort_choices: { library_query: librarySorts, custom_list: librarySorts, up_next: upNextSorts },
    filter_fields: filterFields({ fields: [
      { key: 'subview', label: 'Display level', options: [
        { value: 'shows', label: 'Shows' },
        { value: 'episodes', label: 'Episodes' },
      ] },
    ] }),
    rows: [
      {
        id: 3,
        client_id: 'row-3',
        row_type: 'up_next',
        custom_title: 'Next episodes',
        custom_list_id: null,
        custom_list_name: '',
        sort_by: 'title',
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
    sort_choices: { library_query: librarySorts, custom_list: librarySorts, up_next: upNextSorts },
    filter_fields: filterFields({ fields: [
      { key: 'subview', label: 'Display level', options: [
        { value: 'albums', label: 'Albums' },
        { value: 'tracks', label: 'Tracks' },
        { value: 'artists', label: 'Artists' },
      ] },
    ] }),
    rows: [
      {
        id: 4,
        client_id: 'row-4',
        row_type: 'recently_unrated',
        custom_title: '',
        custom_list_id: null,
        custom_list_name: '',
        sort_by: 'recent',
        direction: 'desc',
        recent_show: 'album',
        filters: {},
      },
    ],
  },
];

const listChoices = [
  { id: 11, name: 'Weekend picks', is_smart: false },
  { id: 12, name: 'Short films', is_smart: true },
  { id: 13, name: 'Science fiction', is_smart: false },
];

const mediaTypeChipStyles = [
  { value: 'solid', label: 'Solid' },
  { value: 'outline', label: 'Outline' },
  { value: 'soft', label: 'Soft' },
];

function wait(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

export default function HomeSettingsSlot() {
  const [values, setValues] = useState({
    sections,
    showMediaTypeHeaders: true,
    mediaTypeChipsEnabled: false,
    mediaTypeChipStyle: 'solid',
  });
  const [savedValues, setSavedValues] = useState({
    sections,
    showMediaTypeHeaders: true,
    mediaTypeChipsEnabled: false,
    mediaTypeChipStyle: 'solid',
  });

  async function save({ values: submitted }) {
    await wait(450);
    setSavedValues(submitted);
  }

  return <SettingsCard title="Home screen" palette={settingsPalette}>
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
