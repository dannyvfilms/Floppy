import React, { useState } from 'react';
import { StyleSheet, View } from 'react-native';
import { AppearanceEditor } from '../../../frontend/settings/AppearanceEditor';
import { SettingsCard } from '../../../frontend/settings/SettingsCard';
import { palette, radius, spacing } from '../theme';

export const surface = {
  id: 'SET-APPEARANCE',
  title: 'Appearance and detail layout editor',
  where: 'Settings appearance theme, custom palette and detail section layout',
  status: 'in_progress',
  note: 'All theme presets and swatches, the custom palette colours and effect steppers, and every server detail-page family, zone, section toggle and move control render from the shared React Native editor with local validation and dirty/saving/error state. Values and saving are demo state; the web appearance page remains server-owned, and browser mounting plus iOS/Android runtime interaction were not exercised, so Expo parse/export is compile-only evidence.',
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
  success: palette.success,
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

const presets = {
  system: { label: 'System default' },
  light: { label: 'Light' },
  dark: { label: 'Dark' },
  catppuccin_mocha: { label: 'Catppuccin Mocha' },
  dracula: { label: 'Dracula' },
  nord: { label: 'Nord' },
  gruvbox: { label: 'Gruvbox' },
  oled: { label: 'OLED' },
  glass: { label: 'Glass cinema' },
  plex: { label: 'Plex inspired' },
  projector: { label: 'Projector' },
  video_store: { label: 'Video store' },
  custom: { label: 'Custom palette' },
};

const colors = {
  page_bg: { label: 'Page', default: '#10141f' },
  surface: { label: 'Cards', default: '#1b2233' },
  panel: { label: 'Panels', default: '#202940' },
  text: { label: 'Text', default: '#f6f1df' },
  muted: { label: 'Muted text', default: '#adb7cc' },
  accent: { label: 'Accent', default: '#ffb454' },
  accent_text: { label: 'Text on accent', default: '#111827' },
};

const effects = {
  radius: { label: 'Corner radius', default: 12, min: 0, max: 28, step: 2, unit: 'px' },
  blur: { label: 'Backdrop blur', default: 12, min: 0, max: 24, step: 2, unit: 'px' },
  surface_opacity: { label: 'Surface opacity', default: 82, min: 40, max: 100, step: 2, unit: '%' },
};

function zone(label, sections) {
  return { label, sections: sections.map(([key, title]) => ({ key, label: title })) };
}

// Mirrors src/users/appearance.py DETAIL_LAYOUT_FAMILIES so the native editor
// exposes every family, zone and section key the server accepts.
const families = {
  media: {
    label: 'Films, books and manga',
    zones: {
      sidebar: zone('Information column', [
        ['history', 'Your history'],
        ['details', 'Details'],
        ['genres', 'Genres'],
        ['studios', 'Studios'],
        ['collection', 'Collection'],
      ]),
      content: zone('Main content', [
        ['notes', 'Notes'],
        ['related', 'Related titles'],
        ['cast', 'Cast'],
        ['crew', 'Crew'],
        ['recommendations', 'Recommendations'],
      ]),
    },
  },
  series: {
    label: 'Series and seasons',
    zones: {
      sidebar: zone('Information column', [
        ['history', 'Your history'],
        ['details', 'Details'],
        ['genres', 'Genres'],
        ['studios', 'Studios'],
        ['collection', 'Collection'],
      ]),
      content: zone('Main content', [
        ['notes', 'Notes'],
        ['seasons', 'Seasons'],
        ['episodes', 'Episodes'],
        ['cast', 'Cast'],
        ['crew', 'Crew'],
        ['recommendations', 'Recommendations'],
      ]),
    },
  },
  game: {
    label: 'Games',
    zones: {
      sidebar: zone('Information column', [
        ['history', 'Your history'],
        ['details', 'Details'],
        ['genres', 'Genres'],
        ['studios', 'Studios'],
        ['collection', 'Collection'],
      ]),
      content: zone('Main content', [
        ['notes', 'Notes'],
        ['game_lengths', 'Play times'],
        ['cast', 'Cast'],
        ['crew', 'Crew'],
        ['recommendations', 'Recommendations'],
      ]),
    },
  },
  episode: {
    label: 'Episodes',
    zones: {
      content: zone('Content', [
        ['genres', 'Genres'],
        ['notes', 'Notes'],
        ['cast', 'Cast'],
        ['crew', 'Crew'],
      ]),
    },
  },
  comic: {
    label: 'Comic volumes',
    zones: {
      sidebar: zone('Information column', [
        ['history', 'Your history'],
        ['details', 'Details'],
        ['genres', 'Genres'],
        ['studios', 'Studios'],
        ['collection', 'Collection'],
      ]),
      content: zone('Main content', [
        ['notes', 'Notes'],
        ['episodes', 'Issues'],
        ['recommendations', 'Recommendations'],
      ]),
    },
  },
  comic_issue: {
    label: 'Comic issues',
    zones: {
      sidebar: zone('Information column', [
        ['details', 'Details'],
        ['authors', 'Authors'],
        ['collection', 'Collection'],
      ]),
    },
  },
  music_album: {
    label: 'Music albums',
    zones: {
      sidebar: zone('Information column', [
        ['details', 'Details'],
        ['genres', 'Genres'],
        ['collection', 'Collection'],
      ]),
      content: zone('Main content', [
        ['notes', 'Notes'],
        ['tracks', 'Tracks'],
      ]),
    },
  },
  music_artist: {
    label: 'Music artists',
    zones: {
      sidebar: zone('Information column', [
        ['details', 'Details'],
        ['genres', 'Genres'],
        ['collection', 'Collection'],
      ]),
      content: zone('Main content', [
        ['notes', 'Notes'],
        ['relations', 'Related artists'],
        ['discography', 'Discography'],
      ]),
    },
  },
  podcast: {
    label: 'Podcasts',
    zones: {
      sidebar: zone('Information column', [
        ['details', 'Details'],
        ['genres', 'Genres'],
      ]),
      content: zone('Main content', [
        ['notes', 'Notes'],
        ['episodes', 'Episodes'],
      ]),
    },
  },
  person: {
    label: 'People',
    zones: {
      hero: zone('Profile', [['biography', 'Biography and facts']]),
      content: zone('Content', [['filmography', 'Filmography']]),
    },
  },
  studio: {
    label: 'Studios',
    zones: {
      hero: zone('Profile', [['overview', 'Overview and facts']]),
      content: zone('Content', [['works', 'Works']]),
    },
  },
};

// Server default detail layouts keep every section enabled in registry order.
const defaultLayouts = Object.fromEntries(Object.entries(families).map(([familyKey, family]) => [
  familyKey,
  Object.fromEntries(Object.entries(family.zones).map(([zoneKey, value]) => [
    zoneKey,
    value.sections.map(section => section.key),
  ])),
]));

const initialValues = {
  theme: 'system',
  palette: Object.fromEntries(Object.entries(colors).map(([key, value]) => [key, value.default]).concat(Object.entries(effects).map(([key, value]) => [key, value.default]))),
  layouts: defaultLayouts,
};

function wait(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

export default function AppearanceSettingsSlot() {
  const [values, setValues] = useState(initialValues);
  const [savedValues, setSavedValues] = useState(initialValues);

  async function save({ values: submitted }) {
    await wait(450);
    setSavedValues(submitted);
  }

  return <SettingsCard title="Appearance" palette={settingsPalette}>
    <View style={styles.form}>
      <AppearanceEditor
        presets={presets}
        colors={colors}
        effects={effects}
        families={families}
        values={values}
        initialValues={savedValues}
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
