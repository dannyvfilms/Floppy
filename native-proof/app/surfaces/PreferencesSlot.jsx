import React, { useState } from 'react';
import { SettingsPreferencesView } from '../../../frontend/pages/SettingsPreferencesView';
import { actionIcons } from '../../../frontend/ui/actionIcons';
import { preferencesMeta, preferencesToForm } from '../data/settingsTransport';
import { applyThemeSetting } from '../themeSync';
import { getThemeSetting } from '../themeState';
import SettingsLoadState from './SettingsLoadState';
import { useSettingsPalettes } from './settingsPalettes';
import { useSettingsResource } from './useSettingsResource';
import SettingsSaveBar from './SettingsSaveBar';

export const surface = {
  id: 'SET-PREFERENCES',
  title: 'Preferences and save states',
  where: 'Settings preferences',
  status: 'ported',
  note: 'Every control of the web preferences form loads from and saves to /api/v1/user/preferences/, including theme, logo, region, metadata and interface language, recommendations and auto-pause rules. Region and metadata-language options come from /api/v1/user/preferences/choices/ (the TMDB lists the web page renders). Saving a theme applies it to the running app. Loading, signed-out and error-with-retry states are real; a failed load never enables Save.',
};

const currencies = [
  ['auto', 'Auto (browser region)'], ['USD', 'USD ($)'], ['EUR', 'EUR (€)'], ['GBP', 'GBP (£)'],
  ['CAD', 'CAD (CA$)'], ['AUD', 'AUD (A$)'], ['NZD', 'NZD (NZ$)'], ['JPY', 'JPY (¥)'],
  ['CNY', 'CNY (CN¥)'], ['KRW', 'KRW (₩)'], ['INR', 'INR (₹)'], ['BRL', 'BRL (R$)'],
  ['MXN', 'MXN (MX$)'], ['CHF', 'CHF'], ['SEK', 'SEK (kr)'], ['NOK', 'NOK (kr)'],
  ['DKK', 'DKK (kr)'], ['PLN', 'PLN (zł)'], ['CZK', 'CZK (Kč)'], ['ZAR', 'ZAR (R)'],
  ['SGD', 'SGD (S$)'], ['HKD', 'HKD (HK$)'],
].map(([value, label]) => ({ value, label }));

const baseSections = [
  {
    id: 'display-layout',
    icon: actionIcons.settings,
    footer: 'Card subtitles, the progress bar, and zero ratings are on the Media Cards page.',
    footerAfter: 'mobile_grid_layout',
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
          { value: 'system_default', label: 'System default: Aug 12, 2025 / 12 Aug 2025' },
          { value: 'iso_8601', label: 'ISO 8601: 2025-08-12' },
          { value: 'month_d_yyyy', label: 'Month D, YYYY: Aug 12, 2025' },
          { value: 'd_mon_yyyy', label: 'D Mon YYYY: 12 Aug 2025' },
          { value: 'm_d_yyyy', label: 'M/D/YYYY: 08/12/2025' },
          { value: 'd_m_yyyy', label: 'D/M/YYYY: 12/08/2025' },
          { value: 'dd_mm_yyyy', label: 'DD.MM.YYYY: 12.08.2025' },
          { value: 'yyyy_mm_dd', label: 'YYYY/MM/DD: 2025/08/12' },
        ],
      },
      {
        name: 'time_format', label: 'Time Format', help: 'How times appear.', type: 'select',
        options: [
          { value: 'system_default', label: 'System default: 6:45 PM / 18:45' },
          { value: 'h_mm_ampm', label: '12-hour (h:mm AM/PM): 6:45 PM' },
          { value: 'hh_mm_ampm', label: '12-hour, leading zero (hh:mm AM/PM): 06:45 PM' },
          { value: 'hh_mm', label: '24-hour (HH:mm): 18:45' },
          { value: 'hh_mm_ss', label: '24-hour with seconds (HH:mm:ss): 18:45:00' },
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
    icon: actionIcons.globe,
    title: 'Language & Metadata',
    copy: 'Manage languages and providers.',
    fields: [
      {
        name: 'watch_provider_region', label: 'Provider Region', help: 'Provider region.', type: 'select',
        options: [],
      },
      {
        name: 'metadata_language', label: 'Metadata Language', help: 'Metadata language.', type: 'select',
        options: [],
      },
      {
        name: 'ui_language', label: 'UI Language', help: 'Interface display language.', type: 'select',
        options: [],
      },
    ],
  },
  {
    id: 'tracking-interaction',
    icon: actionIcons.pulse,
    title: 'Tracking & Interaction',
    copy: 'Control how Floppy tracks and interacts with your activity.',
    fields: [
      {
        name: 'hide_completed_recommendations', type: 'toggle', label: 'Hide Completed',
        help: 'Hide completed items.', offLabel: 'Disabled - show completed items', onLabel: 'Enabled - hide completed items',
      },
      {
        name: 'show_recommendations', type: 'toggle', label: 'Recommendations',
        help: 'Show recommendations on detail pages.', offLabel: 'Disabled - hide recommendations', onLabel: 'Enabled - show recommendations',
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
          { value: 'sessions', label: 'Sessions: new entry per play; exact history' },
          { value: 'repeats', label: 'Repeats: update one entry; spreads time across range' },
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
    id: 'automation',
    icon: actionIcons.signal,
    title: 'Automation',
    copy: 'Manage automated rules.',
    fields: [
      {
        name: 'auto_pause_rules', type: 'autoPause', label: 'Library Management',
        help: 'Pause in-progress items.',
        addLabel: 'Disabled. Click to add rule.',
        addAnotherLabel: 'Enabled. Click to add additional rule.',
        emptyLabel: 'No auto-pause rules yet. Add one to get started.',
        libraryLabel: 'Library',
        weeksLabel: 'weeks',
        removeLabel: 'Remove',
        defaultLibrary: 'all',
        defaultWeeks: 16,
        options: [],
      },
    ],
  },
];

const uiLanguages = [
  { value: 'auto', label: 'Auto (browser language)' },
  { value: 'en', label: 'English' },
  { value: 'de', label: 'Deutsch' },
  { value: 'es', label: 'Español' },
  { value: 'fr', label: 'Français' },
  { value: 'it', label: 'Italiano' },
];

const THEME_OPTIONS = [
  { value: 'system', label: 'System default' },
  { value: 'dark', label: 'Dark' },
  { value: 'light', label: 'Light' },
];

const AUTO_PAUSE_LABELS = {
  all: 'All Libraries', movie: 'Movies', tv: 'TV Shows', season: 'TV Seasons', anime: 'Anime',
  book: 'Books', game: 'Games', comic: 'Comics', manga: 'Manga', boardgame: 'Board Games',
};

function titleCase(value) {
  return String(value).replace(/[_-]+/g, ' ').replace(/\b\w/g, letter => letter.toUpperCase());
}

// Keep the web wording for known values, follow the server's list of values.
function matchServerChoices(options, serverValues) {
  if (!Array.isArray(serverValues) || !serverValues.length) return options;
  const labels = new Map(options.map(option => [String(option.value), option.label]));
  return serverValues.map(value => ({ value: String(value), label: labels.get(String(value)) || titleCase(value) }));
}

function pairsToOptions(pairs) {
  return (pairs || []).map(([value, label]) => ({ value, label }));
}

function buildSections(meta, lists, current) {
  const choices = meta.choices || {};
  const themeOptions = THEME_OPTIONS.some(option => option.value === current.theme)
    ? THEME_OPTIONS
    : [...THEME_OPTIONS, { value: current.theme, label: `${titleCase(current.theme)} (set in Appearance)` }];
  return baseSections.map(section => ({
    ...section,
    fields: section.fields.map(field => {
      if (field.name === 'theme') return { ...field, options: themeOptions };
      if (field.name === 'watch_provider_region') return { ...field, placeholder: 'Disabled', options: pairsToOptions(lists.watch_provider_region) };
      if (field.name === 'metadata_language') return { ...field, options: pairsToOptions(lists.metadata_language) };
      if (field.name === 'ui_language') return { ...field, options: matchServerChoices(uiLanguages, choices.ui_language) };
      if (field.name === 'auto_pause_rules') {
        const libraries = ['all', ...meta.autoPauseLibraries];
        const options = libraries.map(value => ({ value, label: AUTO_PAUSE_LABELS[value] || titleCase(value) }));
        return { ...field, options, defaultLibrary: 'all' };
      }
      if (field.type === 'select' && Array.isArray(choices[field.name]) && field.options.length) {
        return { ...field, options: matchServerChoices(field.options, choices[field.name]) };
      }
      return field;
    }),
  }));
}

function validate(values) {
  const errors = {};
  const rules = values.auto_pause_rules || [];
  if (rules.some(rule => !Number.isInteger(rule.weeks) || rule.weeks < 1)) {
    errors.auto_pause_rules = 'Enter at least one week for each auto-pause rule.';
  }
  return errors;
}

function PreferencesForm({ transport, payload, lists, reload, onOpenCards }) {
  const { settingsPalette, buttonPalette } = useSettingsPalettes();
  const [initial] = useState(() => preferencesToForm(payload));
  const [meta] = useState(() => preferencesMeta(payload));
  const [values, setValues] = useState(initial);
  const [savedValues, setSavedValues] = useState(initial);
  const [formError, setFormError] = useState('');

  async function save({ values: submitted }) {
    setFormError('');
    try {
      const changes = Object.fromEntries(Object.entries(submitted)
        .filter(([field, value]) => JSON.stringify(value) !== JSON.stringify(savedValues[field])));
      const response = await transport.savePreferences(changes);
      const fresh = { ...submitted, ...preferencesToForm(response) };
      setValues(fresh);
      setSavedValues(fresh);
      if (fresh.theme && fresh.theme !== getThemeSetting().theme) {
        applyThemeSetting({ theme: fresh.theme, custom: getThemeSetting().custom });
      }
    } catch (cause) {
      setFormError(cause?.message || 'Preferences could not be saved.');
      if (cause?.code === 'signed_out') reload();
    }
  }

  return <SettingsPreferencesView
    heading={false}
    SaveBar={SettingsSaveBar}
    sections={buildSections(meta, lists, values)}
    values={values}
    initialValues={savedValues}
    onChange={(name, value) => setValues(current => ({ ...current, [name]: value }))}
    onSave={save}
    validate={validate}
    formError={formError}
    palette={{ ...settingsPalette, preferenceCards: true }}
    onSectionLink={onOpenCards}
    buttonPalette={buttonPalette}
  />;
}

export default function PreferencesSlot({ onOpenCards }) {
  const resource = useSettingsResource(async transport => {
    const [payload, lists] = await Promise.all([
      transport.loadPreferences(),
      transport.loadPreferenceChoices().catch(() => ({})),
    ]);
    return { payload, lists };
  });
  if (resource.state !== 'ready') {
    return <SettingsLoadState state={resource.state} message={resource.message} onRetry={resource.reload} />;
  }
  return <PreferencesForm transport={resource.transport} payload={resource.data.payload}
    lists={resource.data.lists} reload={resource.reload} onOpenCards={onOpenCards} />;
}
