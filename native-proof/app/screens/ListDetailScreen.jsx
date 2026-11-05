import React, { useMemo, useState } from 'react';
import { StyleSheet, Text, TextInput, View } from 'react-native';
import { Screen } from '../components/Screen';
import { Button } from '../../../frontend/ui/Button';
import { FilterBar } from '../../../frontend/ui/FilterBar';
import { ListHeader } from '../../../frontend/ui/ListHeader';
import { ListMembershipPopup } from '../../../frontend/ui/ListMembership';
import { ListResults } from '../../../frontend/ui/ListResults';
import { SmartRuleBuilder, SmartRuleSummary } from '../../../frontend/ui/SmartRules';
import { TierBoard } from '../../../frontend/ui/TierBoard';
import { createListTransport } from '../data/listTransport';
import { palette, radius, spacing } from '../theme';

export const surface = {
  id: 'LIST-DETAIL',
  status: 'ported',
  title: 'List detail results, membership, bulk actions, smart rules and tiers',
  where: 'List detail page for manual, smart and source-backed lists, including the smart-rule editor and tier board',
  note: 'Results, the configurable table and column menu, membership, bulk actions, smart-rule summary/editor and the tier board use shared React Native presentation. Mutations route through the list transport; native login, server selection and CSRF transport remain unconfigured, so the native adapter keeps local preview state while the browser adapter uses the same-origin session.',
};

const BULK_STATUSES = [
  { value: 'Completed', label: 'Completed' },
  { value: 'In progress', label: 'In progress' },
  { value: 'Paused', label: 'Paused' },
  { value: 'Planning', label: 'Planning' },
  { value: 'Dropped', label: 'Dropped' },
];

const MEMBERSHIPS = {
  1: [
    { id: 'you', name: 'Danny', handle: '@danny', role: 'owner' },
    { id: 'sam', name: 'Sam', handle: '@sam', role: 'collaborator' },
    { id: 'riley', name: 'Riley', handle: '@riley', role: 'collaborator' },
  ],
  2: [{ id: 'you', name: 'Danny', handle: '@danny', role: 'owner' }],
  3: [
    { id: 'northstar', name: 'Northstar', handle: '@northstar', role: 'owner' },
    { id: 'you', name: 'Danny', handle: '@danny', role: 'collaborator' },
    { id: 'sam', name: 'Sam', handle: '@sam', role: 'collaborator' },
    { id: 'riley', name: 'Riley', handle: '@riley', role: 'collaborator' },
    { id: 'jordan', name: 'Jordan', handle: '@jordan', role: 'collaborator' },
  ],
};

const SUGGESTIONS = {
  1: ['Avery', 'Morgan'],
  2: ['Sam', 'Riley'],
  3: [],
};

const LINKS = {
  1: { rss: true, radarr: true, sonarr: true, exportCsv: true },
  2: { rss: true, exportCsv: true },
  3: { rss: true, radarr: true, sonarr: true, exportCsv: true },
};

const ALL_ITEMS = {
  dune: {
    id: 'dune', title: 'Dune: Part Two', mediaType: 'movie', mediaTypeLabel: 'Movie',
    status: 'Completed', statusLabel: 'Completed', score: 8.6,
    progressLabel: 'Watched', releaseLabel: 'Mar 1, 2024', releaseDate: '2024-03-01',
    addedLabel: 'Feb 12, 2025', addedDate: '2025-02-12', startDateLabel: 'Mar 2, 2024', endDateLabel: 'Mar 2, 2024',
    rank: 1, image: { src: 'https://picsum.photos/seed/floppy-list-dune/400/600', fallback: '', source: 'primary' },
    rating: { label: '8.6', value: 8.6, scaleMax: 10 },
    cardCornerChips: [{ kind: 'runtime', text: '2h 46m' }],
  },
  quietOrbit: {
    id: 'quiet-orbit', title: 'The Quiet Orbit', mediaType: 'tv', mediaTypeLabel: 'Show',
    status: 'In progress', statusLabel: 'In progress', score: 8.0,
    progressLabel: '6 / 10 episodes', releaseLabel: '2024', releaseDate: '2024-02-08',
    addedLabel: 'Jan 30, 2025', addedDate: '2025-01-30', startDateLabel: 'Feb 2, 2024', endDateLabel: null,
    rank: 2, image: { src: 'https://picsum.photos/seed/floppy-list-orbit/400/600', fallback: '', source: 'primary' },
    rating: { label: '8.0', value: 8, scaleMax: 10 },
    progressBar: { percent: 60, paused: false },
    cardCornerChips: [{ kind: 'next-episode', text: 'Next ep' }],
  },
  signal: {
    id: 'signal', title: 'Signal & Static', mediaType: 'podcast', mediaTypeLabel: 'Podcast',
    status: 'In progress', statusLabel: 'In progress', score: 4.5,
    progressLabel: '3 / 8 episodes', releaseLabel: '2023', releaseDate: '2023-09-14',
    addedLabel: 'Mar 4, 2025', addedDate: '2025-03-04', startDateLabel: 'Sep 14, 2023', endDateLabel: null,
    rank: 3, cardShape: 'square',
    image: { src: 'https://picsum.photos/seed/floppy-list-signal/400/400', fallback: '', source: 'primary' },
    rating: { label: '4.5', value: 4.5, scaleMax: 5 },
    progressBar: { percent: 38, paused: true },
  },
  paper: {
    id: 'paper-lanterns', title: 'Paper Lanterns', mediaType: 'book', mediaTypeLabel: 'Book',
    status: 'Planning', statusLabel: 'Planning', score: 6.5,
    progressLabel: '0 / 320 pages', releaseLabel: '2022', releaseDate: '2022-10-04',
    addedLabel: 'Apr 18, 2025', addedDate: '2025-04-18', startDateLabel: null, endDateLabel: null,
    rank: 4, image: { src: 'https://picsum.photos/seed/floppy-list-paper/400/600', fallback: '', source: 'primary' },
    rating: { label: '6.5', value: 6.5, scaleMax: 10 },
  },
  hades: {
    id: 'hades', title: 'Hades II', mediaType: 'game', mediaTypeLabel: 'Game',
    status: 'In progress', statusLabel: 'In progress', score: 9.1,
    progressLabel: '14h played', releaseLabel: '2024', releaseDate: '2024-05-06',
    addedLabel: 'Jun 2, 2025', addedDate: '2025-06-02', startDateLabel: 'May 7, 2024', endDateLabel: null,
    rank: 5, cardShape: 'square',
    image: { src: 'https://picsum.photos/seed/floppy-list-hades/400/400', fallback: '', source: 'primary' },
    rating: { label: '9.1', value: 9.1, scaleMax: 10 },
    progressBar: { percent: 42, paused: false },
  },
  severance: {
    id: 'severance', title: 'Severance', mediaType: 'tv', mediaTypeLabel: 'Show',
    status: 'Completed', statusLabel: 'Completed', score: 8.9,
    progressLabel: '9 / 9 episodes', releaseLabel: '2022', releaseDate: '2022-02-18',
    addedLabel: 'Dec 8, 2024', addedDate: '2024-12-08', startDateLabel: 'Feb 18, 2022', endDateLabel: 'Apr 8, 2022',
    rank: 6, image: { src: 'https://picsum.photos/seed/floppy-list-severance/400/600', fallback: '', source: 'primary' },
    rating: { label: '8.9', value: 8.9, scaleMax: 10 },
    progressBar: { percent: 100, paused: false },
  },
  bear: {
    id: 'the-bear', title: 'The Bear', mediaType: 'tv', mediaTypeLabel: 'Show',
    status: 'Paused', statusLabel: 'Paused', score: 8.2,
    progressLabel: '4 / 10 episodes', releaseLabel: '2022', releaseDate: '2022-06-23',
    addedLabel: 'Nov 2, 2024', addedDate: '2024-11-02', startDateLabel: 'Jun 23, 2022', endDateLabel: null,
    rank: 7, image: { src: 'https://picsum.photos/seed/floppy-list-bear/400/600', fallback: '', source: 'primary' },
    rating: { label: '8.2', value: 8.2, scaleMax: 10 },
    progressBar: { percent: 40, paused: true },
  },
  studio: {
    id: 'home-studio', title: 'Building a Home Studio', mediaType: 'video', mediaTypeLabel: 'Video',
    status: 'Completed', statusLabel: 'Completed', score: null,
    progressLabel: '12:40 watched', releaseLabel: '2024', releaseDate: '2024-04-12',
    addedLabel: 'May 12, 2025', addedDate: '2025-05-12', startDateLabel: 'Apr 12, 2024', endDateLabel: 'Apr 12, 2024',
    rank: 8, cardShape: 'landscape', video: true,
    image: { src: 'https://picsum.photos/seed/floppy-list-studio/800/450', fallback: '', source: 'primary' },
    cardCornerChips: [{ kind: 'runtime', text: '12:40' }],
  },
  memory: {
    id: 'memory', title: 'A Memory Called Empire', mediaType: 'book', mediaTypeLabel: 'Book',
    status: 'Dropped', statusLabel: 'Dropped', score: 7.0,
    progressLabel: '180 / 512 pages', releaseLabel: '2019', releaseDate: '2019-03-26',
    addedLabel: 'Aug 21, 2024', addedDate: '2024-08-21', startDateLabel: 'Mar 26, 2019', endDateLabel: null,
    rank: 9, image: { src: 'https://picsum.photos/seed/floppy-list-memory/400/600', fallback: '', source: 'primary' },
    rating: { label: '7.0', value: 7, scaleMax: 10 },
    progressBar: { percent: 35, paused: true },
  },
  blueEye: {
    id: 'blue-eye', title: 'Blue Eye Samurai', mediaType: 'anime', mediaTypeLabel: 'Anime',
    status: 'Planning', statusLabel: 'Planning', score: null,
    progressLabel: '0 / 8 episodes', releaseLabel: '2023', releaseDate: '2023-11-03',
    addedLabel: 'Jan 9, 2025', addedDate: '2025-01-09', startDateLabel: null, endDateLabel: null,
    rank: 10, image: { src: 'https://picsum.photos/seed/floppy-list-samurai/400/600', fallback: '', source: 'primary' },
  },
  outerWilds: {
    id: 'outer-wilds', title: 'Outer Wilds', mediaType: 'game', mediaTypeLabel: 'Game',
    status: 'Completed', statusLabel: 'Completed', score: 9.5,
    progressLabel: '22h played', releaseLabel: '2019', releaseDate: '2019-05-28',
    addedLabel: 'Jul 14, 2024', addedDate: '2024-07-14', startDateLabel: 'May 28, 2019', endDateLabel: 'Jun 9, 2019',
    rank: 11, cardShape: 'square',
    image: { src: 'https://picsum.photos/seed/floppy-list-wilds/400/400', fallback: '', source: 'primary' },
    rating: { label: '9.5', value: 9.5, scaleMax: 10 },
    progressBar: { percent: 100, paused: false },
  },
  cinder: {
    id: 'cinder', title: 'Cinder', mediaType: 'movie', mediaTypeLabel: 'Movie',
    status: 'In progress', statusLabel: 'In progress', score: 7.4,
    progressLabel: '1h 12m watched', releaseLabel: '2025', releaseDate: '2025-01-17',
    addedLabel: 'Mar 28, 2025', addedDate: '2025-03-28', startDateLabel: 'Jan 17, 2025', endDateLabel: null,
    rank: 12, image: { src: 'https://picsum.photos/seed/floppy-list-cinder/400/600', fallback: '', source: 'primary' },
    rating: { label: '7.4', value: 7.4, scaleMax: 10 },
    progressBar: { percent: 48, paused: false },
  },
};

const LIST_ITEMS = {
  1: Object.values(ALL_ITEMS),
  2: ['quietOrbit', 'severance', 'paper', 'hades', 'memory', 'blueEye', 'outerWilds', 'cinder'].map(key => ALL_ITEMS[key]),
  3: ['dune', 'severance', 'bear', 'outerWilds', 'signal'].map(key => ALL_ITEMS[key]),
};

const DEMO_TIER_ASSIGNMENTS = {
  dune: 's',
  quietOrbit: 'a',
  signal: 'b',
  paper: 'a',
  hades: 's',
  severance: 'a',
  bear: 'b',
  studio: 'c',
  memory: 'c',
  blueEye: 'd',
  outerWilds: 's',
  cinder: 'b',
};

const DEFAULT_TIERS = [
  { id: 's', name: 'S', color: '#ff7f7f' },
  { id: 'a', name: 'A', color: '#ffbf7f' },
  { id: 'b', name: 'B', color: '#ffdf7f' },
  { id: 'c', name: 'C', color: '#bfff7f' },
  { id: 'd', name: 'D', color: '#7fbfff' },
  { id: 'f', name: 'F', color: '#c4a7ff' },
];

const SMART_OPTIONS = {
  mediaTypes: [
    { value: 'movie', label: 'Movie' },
    { value: 'tv', label: 'TV Show' },
    { value: 'book', label: 'Book' },
    { value: 'game', label: 'Game' },
    { value: 'anime', label: 'Anime' },
    { value: 'video', label: 'Video' },
  ],
  statuses: [
    { value: 'Completed', label: 'Completed' },
    { value: 'In progress', label: 'In Progress' },
    { value: 'Planning', label: 'Planning' },
    { value: 'Paused', label: 'Paused' },
    { value: 'Dropped', label: 'Dropped' },
  ],
  relativeUnits: [
    { value: 'days', label: 'Days' },
    { value: 'weeks', label: 'Weeks' },
    { value: 'months', label: 'Months' },
    { value: 'years', label: 'Years' },
  ],
  genres: ['Science Fiction', 'Fantasy', 'Drama', 'Adventure', 'Mystery', 'Animation'],
  impliedGenres: ['Science Fiction', 'Fantasy', 'Drama'],
  years: [
    { value: '2025', label: '2025' },
    { value: '2024', label: '2024' },
    { value: '2023', label: '2023' },
    { value: '2022', label: '2022' },
    { value: 'unknown', label: 'Unknown' },
  ],
  sources: [
    { value: 'tmdb', label: 'The Movie Database' },
    { value: 'openlibrary', label: 'Open Library' },
    { value: 'igdb', label: 'Internet Game Database' },
    { value: 'manual', label: 'Manual' },
  ],
  languages: [
    { value: 'en', label: 'EN' },
    { value: 'ja', label: 'JA' },
    { value: 'fr', label: 'FR' },
  ],
  countries: [
    { value: 'US', label: 'US' },
    { value: 'GB', label: 'GB' },
    { value: 'JP', label: 'JP' },
  ],
  platforms: [
    { value: 'PC', label: 'PC' },
    { value: 'Switch', label: 'Switch' },
    { value: 'PlayStation 5', label: 'PlayStation 5' },
  ],
  origins: [
    { value: 'JP', label: 'JP' },
    { value: 'US', label: 'US' },
  ],
  formats: [
    { value: 'hardcover', label: 'Hardcover' },
    { value: 'paperback', label: 'Paperback' },
    { value: 'ebook', label: 'eBook' },
  ],
  authors: [
    { value: 'Martha Wells', label: 'Martha Wells' },
    { value: 'Ursula K. Le Guin', label: 'Ursula K. Le Guin' },
  ],
  providers: [
    { value: 'Netflix', label: 'Netflix' },
    { value: 'Max', label: 'Max' },
  ],
  tags: ['sci-fi', 'favourites', 'weekend'],
  lists: [
    { id: '1', label: 'Weekend Watchlist' },
    { id: '3', label: 'Shared with Friends' },
  ],
  showGenres: true,
  showImpliedGenres: true,
  showYears: true,
  showSources: true,
  showLanguages: true,
  showCountries: true,
  showPlatforms: true,
  showOrigins: true,
  showFormats: true,
  showAuthors: true,
  showProviders: true,
};

const DEFAULT_SMART_RULES = {
  media_types: [],
  status: [],
  rating: 'all',
  rating_min: '',
  rating_max: '',
  collection: 'all',
  genre: '',
  implied_genre: '',
  year: '',
  release: 'all',
  completed_date_from: '',
  completed_date_to: '',
  completed_date_within: '',
  completed_date_within_unit: 'days',
  release_date_from: '',
  release_date_to: '',
  release_date_within: '',
  release_date_within_unit: 'days',
  date_added_from: '',
  date_added_to: '',
  date_added_within: '',
  date_added_within_unit: 'days',
  source: '',
  search: '',
  sort: 'date_added',
  sort_direction: 'desc',
  language: '',
  country: '',
  platform: '',
  origin: '',
  format: '',
  author: '',
  provider: '',
  tag: [],
  tag_mode: 'or',
  list: [],
  semantics_version: '2',
};

const DEMO_SMART_RULES = {
  2: {
    ...DEFAULT_SMART_RULES,
    media_types: ['book', 'movie'],
    rating: 'rated',
    rating_min: '7.5',
    genre: 'Science Fiction',
    tag: ['sci-fi'],
    tag_mode: 'or',
  },
};

function smartRulesFor(list) {
  return { ...DEFAULT_SMART_RULES, ...(DEMO_SMART_RULES[list?.id] || {}) };
}

function tiersFor(list) {
  return DEFAULT_TIERS.map(tier => ({ ...tier }));
}


const DEFAULT_LIST = {
  id: '1',
  name: 'Weekend Watchlist',
  itemsCount: 12,
  completionPercent: 25,
  visibility: 'public',
  memberCount: 3,
  canEdit: true,
  canRecommend: true,
  role: 'Owner',
  href: '/demo/lists/1',
};

const FILTER_PALETTE = {
  background: palette.background,
  surface: palette.surface,
  surfaceStrong: palette.surfaceStrong,
  surfaceHover: palette.surfaceMuted,
  border: palette.border,
  text: palette.text,
  textSecondary: palette.textSecondary,
  textMuted: palette.textMuted,
  accent: palette.accent,
  accentStrong: palette.accentStrong,
  accentText: '#ffffff',
  danger: palette.danger,
  disabled: palette.textMuted,
  overlay: 'rgba(24, 24, 27, 0.78)',
  radius: radius.md,
};

const LIST_PALETTE = {
  ...palette,
  textSecondary: palette.textSecondary,
  border: palette.border,
  accentStrong: palette.accentStrong,
  accent: palette.accent,
  disabled: palette.textMuted,
  overlay: 'rgba(24, 24, 27, 0.78)',
  backdrop: 'rgba(0, 0, 0, 0.6)',
};

function buildList(source) {
  const base = { ...DEFAULT_LIST, ...(source || {}) };
  const members = source?.members || MEMBERSHIPS[base.id] || MEMBERSHIPS['1'];
  const current = members.find(member => member.id === 'you');
  return {
    ...base,
    visibility: String(base.visibility || 'private').toLowerCase(),
    members,
    memberCount: source?.memberCount || members.length,
    isOwner: source?.isOwner ?? current?.role === 'owner',
    role: source?.role || (current?.role === 'owner' ? 'Owner' : 'Collaborator'),
    links: source?.links || LINKS[base.id] || LINKS['1'],
  };
}

function itemsFor(list) {
  const source = LIST_ITEMS[list.id] || LIST_ITEMS['1'];
  const ranks = {};
  return source.map(item => {
    const tier = DEMO_TIER_ASSIGNMENTS[item.id] || '';
    ranks[tier] = (ranks[tier] || 0) + 1;
    return { ...item, tier, tierRank: ranks[tier] };
  });
}

function tierIndexForScore(score, tierCount) {
  const steps = Math.floor(((10 - Number(score)) * tierCount) / 10);
  return Math.max(0, Math.min(steps, tierCount - 1));
}

function defaultFilters(list) {
  const nested = list.isSmart || (list.source && list.source !== 'local');
  return {
    mediaTypes: [],
    statuses: [],
    sort: nested ? 'date_added' : 'custom',
    direction: nested ? 'desc' : 'asc',
    view: 'grid',
    ranges: {
      rating: { from: '', to: '', within: '', unit: 'days' },
      dateAdded: { from: '', to: '', within: '', unit: 'days' },
    },
  };
}

function ratingRange(value) {
  const from = value?.from ? Number(value.from) : null;
  const to = value?.to ? Number(value.to) : null;
  return { from: Number.isNaN(from) ? null : from, to: Number.isNaN(to) ? null : to };
}

function withinDays(iso, within, unit) {
  if (!iso || !within) {
    return true;
  }
  const amount = Number(within);
  if (!amount) {
    return true;
  }
  const days = { days: 1, weeks: 7, months: 30, years: 365 }[unit] || 1;
  return Date.now() - Date.parse(iso) <= amount * days * 86400000;
}

function sortItems(items, filters) {
  const direction = filters.direction === 'asc' ? 1 : -1;
  return [...items].sort((a, b) => {
    switch (filters.sort) {
      case 'title':
        return direction * a.title.localeCompare(b.title);
      case 'media_type':
        return direction * a.mediaTypeLabel.localeCompare(b.mediaTypeLabel);
      case 'release_date':
        return direction * String(a.releaseDate || '').localeCompare(String(b.releaseDate || ''));
      case 'date_added':
        return direction * String(a.addedDate || '').localeCompare(String(b.addedDate || ''));
      case 'score':
        return direction * ((a.score ?? -1) - (b.score ?? -1));
      case 'progress':
        return direction * String(a.progressLabel || '').localeCompare(String(b.progressLabel || ''));
      case 'custom':
        return (a.rank ?? Number.MAX_SAFE_INTEGER) - (b.rank ?? Number.MAX_SAFE_INTEGER);
      default:
        return 0;
    }
  });
}

function activeFilter(filters) {
  return filters.mediaTypes.length > 0
    || filters.statuses.length > 0
    || Object.values(filters.ranges).some(value => value.from || value.to || value.within);
}

export default function ListDetailScreen({ params, onBack, navigate }) {
  const transport = useMemo(
    () => createListTransport(params?.listTransport),
    [params?.listTransport],
  );
  const [list, setList] = useState(() => buildList(params?.list));
  const [filters, setFilters] = useState(() => defaultFilters(buildList(params?.list)));
  const [items, setItems] = useState(() => itemsFor(buildList(params?.list)));
  const [search, setSearch] = useState('');
  const [selectMode, setSelectMode] = useState(false);
  const [selectedIds, setSelectedIds] = useState([]);
  const [bulkMessage, setBulkMessage] = useState(null);
  const [notice, setNotice] = useState(null);
  const [membersOpen, setMembersOpen] = useState(false);
  const [suggestions, setSuggestions] = useState(() => SUGGESTIONS[list.id] || []);
  const [smartRules, setSmartRules] = useState(() => smartRulesFor(buildList(params?.list)));
  const [draftRules, setDraftRules] = useState(() => smartRulesFor(buildList(params?.list)));
  const [smartEdit, setSmartEdit] = useState(false);
  const [smartSaveState, setSmartSaveState] = useState('idle');
  const [tiers, setTiers] = useState(() => tiersFor(buildList(params?.list)));
  const [tierNotice, setTierNotice] = useState('');
  const [tierUndo, setTierUndo] = useState([]);
  const isSmart = !!list.isSmart;

  const options = useMemo(() => {
    const mediaTypes = [];
    const statuses = [];
    items.forEach(item => {
      if (!mediaTypes.some(entry => entry.value === item.mediaType)) {
        mediaTypes.push({ value: item.mediaType, label: item.mediaTypeLabel });
      }
      const value = item.status.toLowerCase();
      if (!statuses.some(entry => entry.value === value)) {
        statuses.push({ value, label: item.statusLabel });
      }
    });
    return {
      mediaTypes,
      statuses,
      sorts: [
        { value: 'custom', label: 'Custom order' },
        { value: 'date_added', label: 'Date added' },
        { value: 'title', label: 'Title' },
        { value: 'release_date', label: 'Release date' },
        { value: 'score', label: 'Rating' },
        { value: 'progress', label: 'Progress' },
        { value: 'media_type', label: 'Media type' },
      ],
      views: [
        { value: 'grid', label: 'Grid' },
        { value: 'table', label: 'Table' },
        ...(isSmart ? [] : [{ value: 'tiers', label: 'Tiers' }]),
      ],
      ranges: [
        { key: 'rating', label: 'Rating', type: 'number', placeholder: '0–10' },
        {
          key: 'dateAdded',
          label: 'Date added',
          type: 'date',
          placeholder: 'YYYY-MM-DD',
          relative: true,
          units: [
            { value: 'days', label: 'Days' },
            { value: 'weeks', label: 'Weeks' },
            { value: 'months', label: 'Months' },
            { value: 'years', label: 'Years' },
          ],
        },
      ],
    };
  }, [items, isSmart]);

  const visibleItems = useMemo(() => {
    const query = search.trim().toLowerCase();
    const rating = ratingRange(filters.ranges.rating);
    const dateRange = filters.ranges.dateAdded || {};
    const filtered = items.filter(item => {
      if (query && !item.title.toLowerCase().includes(query)) {
        return false;
      }
      if (filters.mediaTypes.length && !filters.mediaTypes.includes(item.mediaType)) {
        return false;
      }
      if (filters.statuses.length && !filters.statuses.includes(item.status.toLowerCase())) {
        return false;
      }
      if (rating.from != null && (item.score == null || item.score < rating.from)) {
        return false;
      }
      if (rating.to != null && (item.score == null || item.score > rating.to)) {
        return false;
      }
      if (dateRange.from && String(item.addedDate || '') < dateRange.from) {
        return false;
      }
      if (dateRange.to && String(item.addedDate || '') > dateRange.to) {
        return false;
      }
      if (dateRange.within && !withinDays(item.addedDate, dateRange.within, dateRange.unit)) {
        return false;
      }
      return true;
    });
    return sortItems(filtered, filters);
  }, [items, search, filters]);

  const tierColumns = useMemo(() => tiers.map(tier => ({
    tier,
    items: visibleItems
      .filter(item => item.tier === tier.id)
      .sort((a, b) => (a.tierRank || 0) - (b.tierRank || 0)),
  })), [tiers, visibleItems]);

  const tierUnranked = useMemo(() => visibleItems
    .filter(item => !tiers.some(tier => tier.id === item.tier))
    .sort((a, b) => (a.tierRank || 0) - (b.tierRank || 0)), [tiers, visibleItems]);

  function changeFilters(intent) {
    setFilters(current => {
      if (intent.type === 'clear') {
        return defaultFilters(list);
      }
      if (intent.type === 'toggle') {
        const values = current[intent.key] || [];
        return {
          ...current,
          [intent.key]: values.includes(intent.value)
            ? values.filter(value => value !== intent.value)
            : [...values, intent.value],
        };
      }
      if (intent.type === 'set') {
        return { ...current, [intent.key]: intent.value };
      }
      if (intent.type === 'range') {
        return {
          ...current,
          ranges: { ...current.ranges, [intent.key]: intent.value },
        };
      }
      return current;
    });
    setBulkMessage(null);
  }

  function toggleSelectMode() {
    if (selectMode) {
      setSelectedIds([]);
      setBulkMessage(null);
    }
    setSelectMode(!selectMode);
  }

  function toggleItem(id) {
    setSelectedIds(current => current.includes(id)
      ? current.filter(value => value !== id)
      : [...current, id]);
    setBulkMessage(null);
  }

  async function removeItems(ids) {
    const targets = items.filter(item => ids.includes(item.id));
    if (!targets.length) {
      return;
    }
    const previousItems = items;
    setItems(current => current.filter(item => !ids.includes(item.id)));
    setSelectedIds([]);
    setBulkMessage(null);
    try {
      await Promise.all(targets.map(item => transport.removeItem({
        listId: list.id,
        itemId: item.itemId ?? item.id,
      })));
      setNotice(transport.mode === 'local'
        ? `${targets.length} item(s) removed from the local preview. ${transport.reason}`
        : `Removed ${targets.length} item(s) from ${list.name}.`);
    } catch (error) {
      setItems(previousItems);
      setNotice(error.message || 'The items could not be removed.');
    }
  }

  async function runBulkAction(kind, value) {
    const ids = selectedIds;
    if (!ids.length) {
      return;
    }
    if (kind === 'remove') {
      await removeItems(ids);
      return;
    }
    if (kind === 'status') {
      if (!value) {
        setBulkMessage('Choose a status for the selected items.');
        return;
      }
      const previousItems = items;
      setItems(current => current.map(item => (
        ids.includes(item.id)
          ? { ...item, status: value, statusLabel: value }
          : item
      )));
      setBulkMessage(null);
      try {
        await transport.bulkStatus({ itemIds: ids, status: value });
        setNotice(transport.mode === 'local'
          ? `Set ${ids.length} item(s) to ${value} in the local preview. ${transport.reason}`
          : `Set ${ids.length} item(s) to ${value}.`);
      } catch (error) {
        setItems(previousItems);
        setNotice(error.message || 'The status update failed.');
      }
      return;
    }
    if (kind === 'collection') {
      try {
        await transport.bulkCollection({ itemIds: ids });
        setBulkMessage(transport.mode === 'local'
          ? `${ids.length} selected · collection changes stay in the local preview. ${transport.reason}`
          : `${ids.length} item(s) added to your collection.`);
      } catch (error) {
        setBulkMessage(error.message || 'The collection update failed.');
      }
      return;
    }
    const labels = {
      list: 'Add to list',
      tag: 'Tag change',
      plays: 'Add plays',
    };
    setBulkMessage(`${ids.length} selected · ${labels[kind] || kind} needs its option picker or job transport, which is not ported.`);
  }

  async function changeVisibility(visibility) {
    const previous = list.visibility;
    setList(current => ({ ...current, visibility }));
    try {
      await transport.updateVisibility({ listId: list.id, visibility });
      setNotice(transport.mode === 'local'
        ? `Visibility set to ${visibility} in the local preview. ${transport.reason}`
        : `Visibility set to ${visibility}.`);
    } catch (error) {
      setList(current => ({ ...current, visibility: previous }));
      setNotice(error.message || 'Visibility could not be saved.');
    }
  }

  async function addMember(suggestion) {
    const input = typeof suggestion === 'string' ? { name: suggestion } : suggestion;
    const id = String(input.id ?? input.name.toLowerCase());
    if (list.members.some(member => String(member.id) === id)) {
      return;
    }
    const member = {
      id,
      name: input.name,
      handle: input.handle || `@${id}`,
      role: 'collaborator',
    };
    const nextMembers = [...list.members, member];
    if (transport.mode === 'server' && nextMembers
      .filter(entry => entry.role !== 'owner')
      .some(entry => !/^\d+$/.test(String(entry.id)))) {
      setNotice('Adding a collaborator needs a user id from the server directory; that picker is not ported.');
      return;
    }
    const previousMembers = list.members;
    const previousSuggestions = suggestions;
    setList(current => ({
      ...current,
      members: nextMembers,
      memberCount: nextMembers.length,
    }));
    setSuggestions(current => current.filter(entry => entry !== member.name));
    try {
      await transport.setCollaborators({ listId: list.id, members: nextMembers });
      setNotice(transport.mode === 'local'
        ? `${member.name} added as a collaborator in the local preview. ${transport.reason}`
        : `${member.name} added as a collaborator.`);
    } catch (error) {
      setList(current => ({
        ...current,
        members: previousMembers,
        memberCount: previousMembers.length,
      }));
      setSuggestions(previousSuggestions);
      setNotice(error.message || 'The collaborator could not be added.');
    }
  }

  async function removeMember(id) {
    const member = list.members.find(entry => String(entry.id) === String(id));
    const nextMembers = list.members.filter(entry => String(entry.id) !== String(id));
    if (transport.mode === 'server' && nextMembers
      .filter(entry => entry.role !== 'owner')
      .some(entry => !/^\d+$/.test(String(entry.id)))) {
      setNotice('Removing a collaborator needs server user ids; this list is still using preview members.');
      return;
    }
    const previousMembers = list.members;
    setList(current => ({
      ...current,
      members: nextMembers,
      memberCount: nextMembers.length,
    }));
    try {
      await transport.setCollaborators({ listId: list.id, members: nextMembers });
      setNotice(transport.mode === 'local'
        ? `${member?.name || 'Collaborator'} removed in the local preview. ${transport.reason}`
        : `${member?.name || 'Collaborator'} removed.`);
    } catch (error) {
      setList(current => ({
        ...current,
        members: previousMembers,
        memberCount: previousMembers.length,
      }));
      setNotice(error.message || 'The collaborator could not be removed.');
    }
  }

  async function rateItem(item, score) {
    const previousItems = items;
    setItems(current => current.map(entry => (
      entry.id === item.id
        ? {
            ...entry,
            score,
            rating: {
              ...(entry.rating || { scaleMax: 10 }),
              value: score,
              label: score == null ? null : String(score),
            },
          }
        : entry
    )));
    try {
      await transport.rateItem({ item, score });
    } catch (error) {
      setItems(previousItems);
      setNotice(error.message || 'The rating could not be saved.');
    }
  }

  function changeSmartRule(next) {
    setDraftRules(next);
    setSmartSaveState('dirty');
  }

  async function saveSmartRules(next) {
    const saved = {
      ...next,
      semantics_version: smartRules.semantics_version || next.semantics_version || '',
    };
    setSmartSaveState('saving');
    try {
      await transport.saveSmartRules?.({ listId: list.id, rules: saved });
      setSmartRules(saved);
      setDraftRules(saved);
      setSmartSaveState('saved');
      setNotice(transport.mode === 'local'
        ? 'Smart rules saved in the local preview. The server evaluation is unchanged.'
        : 'Smart rules saved.');
    } catch (error) {
      setSmartSaveState('error');
      setNotice(error.message || 'The smart rules could not be saved.');
    }
  }

  function startSmartEdit() {
    setDraftRules(smartRules);
    setSmartEdit(true);
    setSmartSaveState('idle');
  }

  function cancelSmartEdit() {
    setDraftRules(smartRules);
    setSmartEdit(false);
    setSmartSaveState('idle');
  }

  function saveTiers(nextTiers) {
    const validIds = new Set(nextTiers.map(tier => tier.id));
    const removed = items.some(item => item.tier && !validIds.has(item.tier));
    setTiers(nextTiers);
    setItems(current => current.map((item, index) => (
      validIds.has(item.tier) ? item : { ...item, tier: '', tierRank: index }
    )));
    setTierUndo([]);
    setTierNotice(removed
      ? 'Tier definitions saved; items from removed tiers are now unranked in this demo.'
      : 'Tier definitions saved in this demo.');
  }

  function moveTierItem({ itemId, tierId, itemIds }) {
    const order = new Map((itemIds || []).map((id, index) => [id, index]));
    setItems(current => current.map(item => {
      if (item.id === itemId) {
        return { ...item, tier: tierId, tierRank: order.get(item.id) ?? (item.tierRank || 0) };
      }
      if (order.has(item.id)) {
        return { ...item, tierRank: order.get(item.id) };
      }
      return item;
    }));
    setTierUndo([]);
    setTierNotice('Item moved in the local preview; the server saves the tier and order.');
  }

  function reorderTierItem({ itemId, tierId, direction }) {
    setItems(current => {
      const group = current
        .filter(item => item.tier === tierId)
        .sort((a, b) => (a.tierRank || 0) - (b.tierRank || 0));
      const index = group.findIndex(item => item.id === itemId);
      const target = group[index + (direction === 'up' ? -1 : 1)];
      if (!target) {
        return current;
      }
      const rank = group[index].tierRank;
      return current.map(item => {
        if (item.id === itemId) {
          return { ...item, tierRank: target.tierRank };
        }
        if (item.id === target.id) {
          return { ...item, tierRank: rank };
        }
        return item;
      });
    });
    setTierNotice('Item order updated in the local preview.');
  }

  function fillTiersFromRatings() {
    const unranked = items.filter(item => (
      !tiers.some(tier => tier.id === item.tier) && item.score != null
    ));
    if (!unranked.length) {
      setTierNotice('None of the unranked items have a rating.');
      return { placed: 0 };
    }
    const placements = unranked.map(item => ({
      itemId: item.id,
      tier: tiers[tierIndexForScore(item.score, tiers.length)].id,
    }));
    const counts = {};
    const placementByItem = new Map(placements.map(entry => [entry.itemId, entry.tier]));
    setItems(current => current.map(item => {
      const tier = placementByItem.get(item.id);
      if (!tier) {
        return item;
      }
      counts[tier] = (counts[tier] || 0) + 1;
      return { ...item, tier, tierRank: counts[tier] };
    }));
    setTierUndo(placements);
    setTierNotice('Filled from ratings in the local preview; the server performs the real fill.');
    return { placed: placements.length };
  }

  function undoTierFill() {
    const placed = new Map(tierUndo.map(entry => [entry.itemId, entry.tier]));
    setItems(current => current.map((item, index) => (
      placed.get(item.id) === item.tier
        ? { ...item, tier: '', tierRank: index }
        : item
    )));
    setTierUndo([]);
    setTierNotice('Fill undone in the local preview.');
  }

  function openTierExport() {
    setTierNotice('Tier image export is ready for the platform download adapter.');
  }

  function openLink(row) {
    setMembersOpen(false);
    setNotice(`${row.label} link is ready for the platform browser or download adapter.`);
  }

  function openItem(item) {
    if (navigate) {
      navigate('Detail', { item });
      return;
    }
    setNotice(`${item.title} uses the platform navigation adapter.`);
  }

  function recommendItem() {
    setNotice('Recommendations remain a server flow; the native recommend screen is not ported.');
  }

  const emptyMode = items.length === 0
    ? 'empty'
    : search.trim() ? 'search'
      : activeFilter(filters) ? 'filters'
        : 'empty';

  return <Screen title={list.name} subtitle="List detail" onBack={onBack}>
    <ListHeader
      list={list}
      palette={LIST_PALETTE}
      labels={{ more: 'Members' }}
      onAddItem={() => setNotice('Add New Item remains a server flow; the native add-item screen is not ported.')}
      onExport={() => setNotice('CSV export is ready for the platform download adapter.')}
      onMore={() => setMembersOpen(true)}
      onEdit={() => setMembersOpen(true)} />
    {notice ? <Text style={styles.notice}>{notice}</Text> : null}
    {isSmart ? <View style={styles.smartPanel}>
      <View style={styles.smartActions}>
        {list.canEdit ? <Button
          label={smartEdit ? 'Done editing' : 'Edit smart rules'}
          tone={smartEdit ? 'surface' : 'primary'}
          onPress={() => (smartEdit ? cancelSmartEdit() : startSmartEdit())} /> : null}
      </View>
      <SmartRuleSummary
        rules={smartEdit ? draftRules : smartRules}
        options={SMART_OPTIONS}
        editMode={smartEdit}
        saveState={smartSaveState}
        palette={LIST_PALETTE} />
      {list.canEdit && smartEdit ? <SmartRuleBuilder
        rules={draftRules}
        options={SMART_OPTIONS}
        editMode
        canEdit
        saveState={smartSaveState}
        palette={LIST_PALETTE}
        onChange={changeSmartRule}
        onSave={saveSmartRules}
        onCancel={cancelSmartEdit} /> : null}
    </View> : null}
    <View style={styles.controls}>
      <TextInput
        style={styles.search}
        placeholder="Search this list or recommend something…"
        placeholderTextColor={palette.textMuted}
        value={search}
        onChangeText={setSearch}
        autoCorrect={false}
        accessibilityLabel="Search this list" />
      <FilterBar
        filters={filters}
        options={options}
        palette={FILTER_PALETTE}
        resultCount={visibleItems.length}
        labels={{
          filters: 'Filters',
          status: 'Status',
          sort: 'Sort',
          view: 'View',
          range: 'Range',
        }}
        onChange={changeFilters} />
    </View>
    {!isSmart && filters.view === 'tiers' ? <TierBoard
      tiers={tiers}
      columns={tierColumns}
      unranked={tierUnranked}
      canEdit={!!list.canEdit}
      canFill={!!list.canEdit}
      maxTiers={12}
      notice={tierNotice}
      undoAvailable={tierUndo.length > 0}
      palette={LIST_PALETTE}
      onSaveTiers={saveTiers}
      onMoveItem={moveTierItem}
      onReorderItem={reorderTierItem}
      onFillFromRatings={fillTiersFromRatings}
      onUndoFill={undoTierFill}
      onExport={openTierExport}
      onOpenItem={openItem} /> : <ListResults
      items={visibleItems}
      layout={filters.view}
      sort={filters.sort}
      palette={LIST_PALETTE}
      canEdit={list.canEdit}
      canRecommend={list.canRecommend}
      isSmart={list.isSmart}
      selectMode={selectMode}
      selectedIds={selectedIds}
      onToggleItem={toggleItem}
      onToggleSelectMode={toggleSelectMode}
      onClearSelection={() => {
        setSelectedIds([]);
        setBulkMessage(null);
      }}
      onBulkAction={runBulkAction}
      bulkStatuses={BULK_STATUSES}
      onRemoveItems={removeItems}
      bulkMessage={bulkMessage}
      onOpenItem={openItem}
      onRate={rateItem}
      emptyMode={emptyMode}
      hasSearch={!!search.trim()}
      onRecommend={recommendItem}
      onBrowse={() => navigate?.('Search', { query: '' })} />}
    <ListMembershipPopup
      open={membersOpen}
      list={list}
      palette={LIST_PALETTE}
      suggestions={suggestions}
      onClose={() => setMembersOpen(false)}
      onChangeVisibility={changeVisibility}
      onAddMember={addMember}
      onRemoveMember={removeMember}
      onOpenLink={openLink} />
  </Screen>;
}

const styles = StyleSheet.create({
  controls: { gap: spacing.md },
  smartPanel: { gap: spacing.md },
  smartActions: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm },
  search: {
    backgroundColor: palette.surfaceStrong,
    color: palette.text,
    borderRadius: radius.sm,
    paddingHorizontal: spacing.sm,
    paddingVertical: spacing.sm,
  },
  notice: { color: palette.textMuted, fontSize: 12, lineHeight: 17 },
});
