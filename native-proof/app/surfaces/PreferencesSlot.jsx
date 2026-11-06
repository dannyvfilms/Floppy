import React, { useState } from 'react';
import { SettingsPreferencesView } from '../../../frontend/pages/SettingsPreferencesView';
import { palette, radius } from '../theme';

export const surface = {
  id: 'SET-PREFERENCES',
  title: 'Preferences and save states',
  where: 'Settings preferences',
  status: 'ported',
  note: 'Theme, logo, date/time, locale, title, region, week start and general tracking fields render from the shared React Native preferences form with local dirty/saving/error state and a polite save bar.',
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
  badgeBorder: palette.surfaceMuted,
  badgeBackground: palette.surfaceStrong,
  badgeText: palette.textSecondary,
  badgeHover: palette.surfaceMuted,
  success: palette.success,
  warning: palette.warning,
  danger: palette.danger,
  focusStyle: {},
};

const buttonPalette = {
  primary: { background: palette.accentStrong, pressed: '#4338ca', hovered: '#4338ca', text: '#ffffff', border: 'transparent' },
  surface: { background: palette.surfaceStrong, pressed: palette.surfaceMuted, hovered: palette.surfaceMuted, text: palette.text, border: palette.border },
  'danger-solid': { background: palette.danger, pressed: '#b91c1c', hovered: '#b91c1c', text: '#ffffff', border: 'transparent' },
  radius: radius.sm,
  focusStyle: {},
};

const currencies = [
  ['auto', 'Auto (browser region)'], ['USD', 'USD ($)'], ['EUR', 'EUR (€)'], ['GBP', 'GBP (£)'],
  ['CAD', 'CAD (CA$)'], ['AUD', 'AUD (A$)'], ['NZD', 'NZD (NZ$)'], ['JPY', 'JPY (¥)'],
  ['CNY', 'CNY (CN¥)'], ['KRW', 'KRW (₩)'], ['INR', 'INR (₹)'], ['BRL', 'BRL (R$)'],
  ['MXN', 'MXN (MX$)'], ['CHF', 'CHF'], ['SEK', 'SEK (kr)'], ['NOK', 'NOK (kr)'],
  ['DKK', 'DKK (kr)'], ['PLN', 'PLN (zł)'], ['CZK', 'CZK (Kč)'], ['ZAR', 'ZAR (R)'],
  ['SGD', 'SGD (S$)'], ['HKD', 'HKD (HK$)'],
].map(([value, label]) => ({ value, label }));

const sections = [
  {
    id: 'display-layout',
    title: 'Display & Layout',
    copy: 'Control content display.',
    fields: [
      {
        name: 'theme', label: 'Theme', help: 'App color theme.', type: 'select',
        options: [
          { value: 'system', label: 'System default' },
          { value: 'dark', label: 'Dark' },
          { value: 'light', label: 'Light' },
        ],
      },
      {
        name: 'logo_style', label: 'Logo', help: 'Floppy logo style.', type: 'select',
        options: [
          { value: 'colorful', label: 'Colorful' },
          { value: 'monochrome', label: 'Monochrome' },
        ],
      },
      {
        name: 'date_format', label: 'Date Format', help: 'How dates appear.', type: 'select',
        options: [
          { value: 'system_default', label: 'System default — Aug 12, 2025 / 12 Aug 2025' },
          { value: 'iso_8601', label: 'ISO 8601 — 2025-08-12' },
          { value: 'month_d_yyyy', label: 'Month D, YYYY — Aug 12, 2025' },
          { value: 'd_mon_yyyy', label: 'D Mon YYYY — 12 Aug 2025' },
          { value: 'm_d_yyyy', label: 'M/D/YYYY — 08/12/2025' },
          { value: 'd_m_yyyy', label: 'D/M/YYYY — 12/08/2025' },
          { value: 'dd_mm_yyyy', label: 'DD.MM.YYYY — 12.08.2025' },
          { value: 'yyyy_mm_dd', label: 'YYYY/MM/DD — 2025/08/12' },
        ],
      },
      {
        name: 'time_format', label: 'Time Format', help: 'How times appear.', type: 'select',
        options: [
          { value: 'system_default', label: 'System default — 6:45 PM / 18:45' },
          { value: 'h_mm_ampm', label: '12-hour (h:mm AM/PM) — 6:45 PM' },
          { value: 'hh_mm_ampm', label: '12-hour, leading zero (hh:mm AM/PM) — 06:45 PM' },
          { value: 'hh_mm', label: '24-hour (HH:mm) — 18:45' },
          { value: 'hh_mm_ss', label: '24-hour with seconds (HH:mm:ss) — 18:45:00' },
        ],
      },
      {
        name: 'currency', label: 'Currency', help: 'Symbol shown on collection prices.', type: 'select',
        options: currencies,
      },
      {
        name: 'mobile_grid_layout', label: 'Mobile Grid', help: 'Mobile column count.', type: 'select',
        options: [
          { value: 'comfortable', label: 'Comfortable (2 columns)' },
          { value: 'compact', label: 'Compact (3 columns)' },
        ],
      },
      {
        name: 'title_display_preference', label: 'Title Display', help: 'Card title style.', type: 'select',
        options: [
          { value: 'localized', label: 'Show Localized Titles' },
          { value: 'original', label: 'Show Original Titles' },
          { value: 'auto', label: 'Auto (if available)' },
        ],
      },
      {
        name: 'top_talent_sort_by', label: 'Talent Sort', help: 'Statistics sort order.', type: 'select',
        options: [
          { value: 'plays', label: 'Plays' },
          { value: 'time', label: 'Time' },
          { value: 'titles', label: 'Titles' },
        ],
      },
    ],
  },
  {
    id: 'language-metadata',
    title: 'Language & Metadata',
    copy: 'Manage languages and providers.',
    fields: [
      {
        name: 'watch_provider_region', label: 'Provider Region', help: 'Provider region.', type: 'select',
        options: [
          { value: 'UNSET', label: 'Not set' },
          { value: 'US', label: 'United States' },
          { value: 'GB', label: 'United Kingdom' },
          { value: 'DE', label: 'Germany' },
          { value: 'FR', label: 'France' },
          { value: 'JP', label: 'Japan' },
        ],
      },
      {
        name: 'metadata_language', label: 'Metadata Language', help: 'Metadata language.', type: 'select',
        options: [
          { value: '', label: 'Server Default (en)' },
          { value: 'en', label: 'English' },
          { value: 'es-ES', label: 'Spanish (Spain)' },
          { value: 'fr', label: 'French' },
          { value: 'de-DE', label: 'German' },
          { value: 'ja', label: 'Japanese' },
          { value: 'ko-KR', label: 'Korean' },
          { value: 'zh-CN', label: 'Chinese (Simplified)' },
        ],
      },
      {
        name: 'ui_language', label: 'UI Language', help: 'Interface display language.', type: 'select',
        options: [
          { value: 'auto', label: 'Auto (browser language)' },
          { value: 'en', label: 'English' },
          { value: 'de', label: 'Deutsch' },
          { value: 'es', label: 'Español' },
          { value: 'fr', label: 'Français' },
          { value: 'it', label: 'Italiano' },
        ],
      },
    ],
  },
  {
    id: 'tracking-interaction',
    title: 'Tracking & Interaction',
    copy: 'Control how Floppy tracks and interacts with your activity.',
    fields: [
      {
        name: 'hide_completed_recommendations', type: 'toggle', label: 'Hide Completed',
        help: 'Hide completed items.', offLabel: 'Show completed', onLabel: 'Hide completed',
      },
      {
        name: 'show_recommendations', type: 'toggle', label: 'Recommendations',
        help: 'Show recommendations on detail pages.', offLabel: 'Hidden', onLabel: 'Shown',
      },
      {
        name: 'rating_scale', label: 'Rating Scale', help: 'Choose a rating scale, or turn ratings off.', type: 'select',
        options: [
          { value: '10', label: '1-10 stars' },
          { value: '5', label: '1-5 stars' },
          { value: '0', label: 'Disabled' },
        ],
      },
      {
        name: 'quick_season_update_mobile', label: 'Home Buttons', help: 'Home card actions.', type: 'select',
        options: [
          { value: 'none', label: 'None' },
          { value: 'season_update', label: 'Quick Season Update buttons only' },
          { value: 'next_episode', label: 'Next Episode button only' },
          { value: 'both', label: 'Both' },
        ],
      },
      {
        name: 'game_logging_style', label: 'Game Logging', help: 'Game history style.', type: 'select',
        options: [
          { value: 'sessions', label: 'Sessions — new entry per play; exact history' },
          { value: 'repeats', label: 'Repeats — update one entry; spreads time across range' },
        ],
      },
      {
        name: 'book_comic_manga_progress_percentage', type: 'toggle', label: 'Progress Format',
        help: 'Percent or pages.', offLabel: 'Pages/Issues/Chapters', onLabel: 'Percentage',
      },
      {
        name: 'session_duration', label: 'Session Duration', help: 'Sign-in timeout.', type: 'select',
        options: [
          { value: '86400', label: '1 day' },
          { value: '604800', label: '1 week' },
          { value: '1209600', label: '2 weeks' },
          { value: '2592000', label: '30 days' },
          { value: '7776000', label: '90 days' },
        ],
      },
    ],
  },
  {
    id: 'general',
    title: 'General',
    copy: 'Calendar and library automation.',
    fields: [
      {
        name: 'week_start_day', label: 'Week Start', help: 'First day in calendars and date ranges.', type: 'select',
        options: [
          { value: 'monday', label: 'Monday' },
          { value: 'sunday', label: 'Sunday' },
        ],
      },
      {
        name: 'auto_pause_rules', type: 'autoPause', label: 'Library Management',
        help: 'Pause in-progress items after a set number of weeks.',
        addLabel: 'Add auto-pause rule',
        addAnotherLabel: 'Enabled. Add another rule.',
        emptyLabel: 'No auto-pause rules yet. Add one to get started.',
        libraryLabel: 'Library',
        weeksLabel: 'weeks',
        removeLabel: 'Remove',
        defaultLibrary: 'tv',
        defaultWeeks: 16,
        options: [
          { value: 'all', label: 'All Libraries' },
          { value: 'movie', label: 'Movies' },
          { value: 'tv', label: 'TV Shows' },
          { value: 'anime', label: 'Anime' },
          { value: 'book', label: 'Books' },
          { value: 'game', label: 'Games' },
        ],
      },
    ],
  },
];

const initialValues = {
  theme: 'system',
  logo_style: 'colorful',
  date_format: 'system_default',
  time_format: 'system_default',
  currency: 'auto',
  mobile_grid_layout: 'compact',
  title_display_preference: 'localized',
  top_talent_sort_by: 'plays',
  watch_provider_region: 'UNSET',
  metadata_language: '',
  ui_language: 'auto',
  hide_completed_recommendations: false,
  show_recommendations: true,
  rating_scale: '10',
  quick_season_update_mobile: 'none',
  game_logging_style: 'repeats',
  book_comic_manga_progress_percentage: false,
  session_duration: '1209600',
  week_start_day: 'monday',
  auto_pause_rules: [{ library: 'tv', weeks: 16 }],
};

function validate(values) {
  const errors = {};
  const rules = values.auto_pause_rules || [];
  if (rules.some(rule => !Number.isInteger(rule.weeks) || rule.weeks < 1)) {
    errors.auto_pause_rules = 'Enter at least one week for each auto-pause rule.';
  }
  return errors;
}

function wait(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

export default function PreferencesSlot() {
  const [values, setValues] = useState(initialValues);
  const [savedValues, setSavedValues] = useState(initialValues);

  function change(name, value) {
    setValues(current => ({ ...current, [name]: value }));
  }

  async function save({ values: submitted }) {
    await wait(450);
    setSavedValues(submitted);
  }

  return <SettingsPreferencesView
    sections={sections}
    values={values}
    initialValues={savedValues}
    onChange={change}
    onSave={save}
    validate={validate}
    palette={settingsPalette}
    buttonPalette={buttonPalette}
  />;
}
