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
  note: 'Theme presets, custom palette effects and detail section enable/order render from the shared React Native editor with local validation and dirty/saving/error state. Native runtime interaction and a browser adapter remain unverified.',
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

const families = {
  media: {
    label: 'Films, books and manga',
    zones: {
      sidebar: {
        label: 'Information column',
        sections: [
          { key: 'history', label: 'Your history' },
          { key: 'details', label: 'Details' },
          { key: 'genres', label: 'Genres' },
          { key: 'studios', label: 'Studios' },
          { key: 'collection', label: 'Collection' },
        ],
      },
      content: {
        label: 'Main content',
        sections: [
          { key: 'notes', label: 'Notes' },
          { key: 'related', label: 'Related titles' },
          { key: 'cast', label: 'Cast' },
          { key: 'crew', label: 'Crew' },
          { key: 'recommendations', label: 'Recommendations' },
        ],
      },
    },
  },
  series: {
    label: 'Series and seasons',
    zones: {
      sidebar: {
        label: 'Information column',
        sections: [
          { key: 'history', label: 'Your history' },
          { key: 'details', label: 'Details' },
          { key: 'genres', label: 'Genres' },
          { key: 'studios', label: 'Studios' },
          { key: 'collection', label: 'Collection' },
        ],
      },
      content: {
        label: 'Main content',
        sections: [
          { key: 'notes', label: 'Notes' },
          { key: 'seasons', label: 'Seasons' },
          { key: 'episodes', label: 'Episodes' },
          { key: 'cast', label: 'Cast' },
          { key: 'crew', label: 'Crew' },
          { key: 'recommendations', label: 'Recommendations' },
        ],
      },
    },
  },
  game: {
    label: 'Games',
    zones: {
      sidebar: {
        label: 'Information column',
        sections: [
          { key: 'history', label: 'Your history' },
          { key: 'details', label: 'Details' },
          { key: 'genres', label: 'Genres' },
          { key: 'studios', label: 'Studios' },
          { key: 'collection', label: 'Collection' },
        ],
      },
      content: {
        label: 'Main content',
        sections: [
          { key: 'notes', label: 'Notes' },
          { key: 'playtimes', label: 'Play times' },
          { key: 'cast', label: 'Cast' },
          { key: 'crew', label: 'Crew' },
          { key: 'recommendations', label: 'Recommendations' },
        ],
      },
    },
  },
};

const initialValues = {
  theme: 'dark',
  palette: Object.fromEntries(Object.entries(colors).map(([key, value]) => [key, value.default]).concat(Object.entries(effects).map(([key, value]) => [key, value.default]))),
  layouts: {
    media: {
      sidebar: ['history', 'details', 'genres', 'collection'],
      content: ['notes', 'cast', 'crew', 'recommendations'],
    },
    series: {
      sidebar: ['history', 'details', 'genres'],
      content: ['notes', 'seasons', 'episodes', 'cast'],
    },
    game: {
      sidebar: ['history', 'details', 'genres'],
      content: ['notes', 'playtimes', 'recommendations'],
    },
  },
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
