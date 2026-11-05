import React, { useState } from 'react';
import { View } from 'react-native';
import { MediaTable } from '../../../frontend/ui/MediaTable';
import { MediaColumnMenu } from '../../../frontend/ui/ColumnMenu';
import { palette, spacing } from '../theme';

export const surface = {
  id: 'TABLES',
  status: 'in_progress',
  title: 'Table view and columns',
  where: 'Library and list table layouts',
  note: 'The configurable media table, shared cells and column menu render selected, ordered and persisted columns with sorting, score/status/units, bounded rows and accessible horizontal scrolling. Web media and list tables consume the same server projection through the existing column preference endpoints; native column changes stay in local demo state until account transport is wired. The per-row quick-track modal, browser interaction pass and iOS/Android runtime and accessibility passes remain.',
};

const COLUMNS = [
  { key: 'image', label: '', width: 56, fixed: true, visible: true },
  { key: 'title', label: 'Title', width: 240, primary: true, fixed: true, visible: true },
  { key: 'media_type', label: 'Media Type', width: 120, align: 'center', visible: true },
  { key: 'score', label: 'Score', width: 100, align: 'center', visible: true },
  { key: 'progress', label: 'Progress', width: 130, align: 'center', visible: true },
  { key: 'status', label: 'Status', width: 120, align: 'center', visible: true },
  { key: 'runtime', label: 'Runtime', width: 110, align: 'center', visible: true },
  { key: 'time_watched', label: 'Time Watched', width: 140, align: 'center', visible: true },
  { key: 'release_date', label: 'Release Date', width: 130, align: 'center', visible: false },
  { key: 'date_added', label: 'Date Added', width: 130, align: 'center', visible: false },
  { key: 'genres', label: 'Genres', width: 200, visible: false },
];

const ROWS = [
  {
    id: 'dune', title: 'Dune: Part Two',
    cells: {
      image: { kind: 'image', src: 'https://picsum.photos/seed/floppy-table-dune/80/80', alt: 'Dune: Part Two' },
      title: { kind: 'title', text: 'Dune: Part Two', href: 'Detail' },
      media_type: { kind: 'text', text: 'Movie', muted: true },
      score: { kind: 'score', rated: true, text: '8.6' },
      progress: { kind: 'text', text: 'Watched' },
      status: { kind: 'status', text: 'Completed' },
      runtime: { kind: 'text', text: '2h 46m' },
      time_watched: { kind: 'text', text: '2h 46m' },
      release_date: { kind: 'text', text: 'Mar 1, 2024' },
      date_added: { kind: 'text', text: 'Feb 12, 2025' },
      genres: { kind: 'genres', items: [{ label: 'Sci-Fi' }, { label: 'Drama' }] },
    },
  },
  {
    id: 'orbit', title: 'The Quiet Orbit',
    cells: {
      image: { kind: 'image', src: 'https://picsum.photos/seed/floppy-table-orbit/80/80', alt: 'The Quiet Orbit' },
      title: { kind: 'title', text: 'The Quiet Orbit', href: 'Detail' },
      media_type: { kind: 'text', text: 'Show', muted: true },
      score: { kind: 'score', rated: true, text: '8.0' },
      progress: { kind: 'progress', text: '6', maxText: ' / 10 episodes', note: 'Total' },
      status: { kind: 'status', text: 'In progress' },
      runtime: { kind: 'text', text: '48m' },
      time_watched: { kind: 'text', text: '4h 48m' },
      release_date: { kind: 'text', text: '2024' },
      date_added: { kind: 'text', text: 'Jan 30, 2025' },
      genres: { kind: 'genres', items: [{ label: 'Mystery' }] },
    },
  },
  {
    id: 'hades', title: 'Hades II',
    cells: {
      image: { kind: 'image', src: 'https://picsum.photos/seed/floppy-table-hades/80/80', alt: 'Hades II' },
      title: { kind: 'title', text: 'Hades II', href: 'Detail' },
      media_type: { kind: 'text', text: 'Game', muted: true },
      score: { kind: 'score', rated: true, text: '9.1' },
      progress: { kind: 'progress', text: '14h played', note: 'Total' },
      status: { kind: 'status', text: 'In progress' },
      runtime: { kind: 'text', text: '—', muted: true },
      time_watched: { kind: 'text', text: '14h' },
      release_date: { kind: 'text', text: '2024' },
      date_added: { kind: 'text', text: 'Jun 2, 2025' },
      genres: { kind: 'genres', items: [{ label: 'Roguelike' }, { label: 'Action' }] },
    },
  },
  {
    id: 'signal', title: 'Signal & Static',
    cells: {
      image: { kind: 'image', src: 'https://picsum.photos/seed/floppy-table-signal/80/80', alt: 'Signal & Static' },
      title: { kind: 'title', text: 'Signal & Static', href: 'Detail' },
      media_type: { kind: 'text', text: 'Podcast', muted: true },
      score: { kind: 'score', rated: true, text: '4.5' },
      progress: { kind: 'progress', text: '3', maxText: ' / 8 episodes', note: 'Total' },
      status: { kind: 'status', text: 'In progress' },
      runtime: { kind: 'text', text: '52m' },
      time_watched: { kind: 'text', text: '2h 36m' },
      release_date: { kind: 'text', text: '2023' },
      date_added: { kind: 'text', text: 'Mar 4, 2025' },
      genres: { kind: 'genres', items: [{ label: 'Fiction' }] },
    },
  },
  {
    id: 'paper', title: 'Paper Lanterns',
    cells: {
      image: { kind: 'image', src: 'https://picsum.photos/seed/floppy-table-paper/80/80', alt: 'Paper Lanterns' },
      title: { kind: 'title', text: 'Paper Lanterns', href: 'Detail' },
      media_type: { kind: 'text', text: 'Book', muted: true },
      score: { kind: 'score', rated: true, text: '6.5' },
      progress: { kind: 'progress', text: '0', maxText: ' / 320 pages' },
      status: { kind: 'status', text: 'Planning' },
      runtime: { kind: 'text', text: '—', muted: true },
      time_watched: { kind: 'text', text: '—', muted: true },
      release_date: { kind: 'text', text: '2022' },
      date_added: { kind: 'text', text: 'Apr 18, 2025' },
      genres: { kind: 'genres', items: [{ label: 'Fantasy' }] },
    },
  },
  {
    id: 'studio', title: 'Building a Home Studio',
    cells: {
      image: { kind: 'image', src: 'https://picsum.photos/seed/floppy-table-studio/80/80', alt: 'Building a Home Studio' },
      title: { kind: 'title', text: 'Building a Home Studio', href: 'Detail' },
      media_type: { kind: 'text', text: 'Video', muted: true },
      score: { kind: 'score', rated: false, text: '' },
      progress: { kind: 'text', text: '12:40 watched' },
      status: { kind: 'status', text: 'Completed' },
      runtime: { kind: 'text', text: '12:40' },
      time_watched: { kind: 'text', text: '12m' },
      release_date: { kind: 'text', text: '2024' },
      date_added: { kind: 'text', text: 'May 12, 2025' },
      genres: { kind: 'genres', items: [{ label: 'How-to' }] },
    },
  },
];

export default function TableSlot({ onOpenDetail }) {
  const [columns, setColumns] = useState(() => COLUMNS.map(column => ({ ...column })));
  const [sort, setSort] = useState('title');
  const [direction, setDirection] = useState('asc');
  function saveColumns({ order, hidden }) {
    const hiddenSet = new Set(hidden);
    const byKey = new Map(columns.map(column => [column.key, column]));
    setColumns(order.map(key => byKey.get(key)).filter(Boolean)
      .map(column => ({ ...column, visible: !hiddenSet.has(column.key) })));
  }
  function sortBy(key) {
    setDirection(sort === key ? (direction === 'asc' ? 'desc' : 'asc') : 'asc');
    setSort(key);
  }
  return <View style={{ gap: spacing.sm }}>
    <MediaColumnMenu
      columns={columns}
      defaultOrder={COLUMNS.map(column => column.key)}
      defaultHidden={COLUMNS.filter(column => column.visible === false).map(column => column.key)}
      palette={{ ...palette, link: '#818cf8', accentContrast: '#ffffff' }}
      onSave={saveColumns} />
    <MediaTable
      columns={columns.filter(column => column.visible !== false)}
      rows={ROWS}
      sort={sort}
      sortDirection={direction}
      onSort={sortBy}
      onOpen={row => onOpenDetail?.(row)}
      palette={{ ...palette, link: '#818cf8', accentContrast: '#ffffff' }}
      caption="Library table" />
  </View>;
}
