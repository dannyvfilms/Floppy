import React, { useEffect, useMemo, useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { Button } from '../../../frontend/ui/Button';
import { CollectionBrowser } from '../../../frontend/ui/CollectionBrowser';
import {
  CollectionCopyDialog,
} from '../../../frontend/ui/CollectionCopies';
import {
  CollectionFieldManager,
  CollectionFieldValueInputs,
} from '../../../frontend/ui/CollectionCustomFields';
import { Screen } from '../components/Screen';
import { palette, spacing } from '../theme';

export const surface = {
  id: 'OWNERSHIP',
  status: 'ported',
  title: 'Collection and copies',
  where: 'Collection browser and detail ownership',
  note: 'The collection browser renders realistic owned items in grid, grouped rows and table views with the shared search, filter bar, sort, completeness and per-view paging controls. Pages load in bounded batches and each media-type row loads independently. The shared copy dialog covers existing copies, medium fields, season scope and owner/read-only states, while the shared custom-field value editor and owner-only manager handle typed values. Mutations stay in local demo state; Django remains authoritative for ownership, validation, season expansion and persistence, and iOS/Android runtime interaction has not been exercised.',
};

const MEDIA_LABELS = {
  movie: 'Movies',
  tv: 'TV Shows',
  anime: 'Anime',
  book: 'Books',
  comic: 'Comics',
  manga: 'Manga',
  game: 'Games',
  music: 'Music',
  podcast: 'Podcasts',
  video: 'Videos',
};

const MEDIA_COLORS = {
  movie: '#6366f1',
  tv: '#0ea5e9',
  anime: '#f43f5e',
  book: '#d946ef',
  comic: '#f59e0b',
  manga: '#fb7185',
  game: '#10b981',
  music: '#ec4899',
  podcast: '#8b5cf6',
  video: '#f97316',
};

const VIDEO_FIELDS = [
  { name: 'format', label: 'Format', type: 'select', options: ['4K Blu-ray', 'Blu-ray', 'DVD', 'Digital', 'Streaming', 'VHS'].map(value => ({ value, label: value })) },
  { name: 'resolution', label: 'Resolution', type: 'select', options: ['480p', '720p', '1080p', '4K', '8K'].map(value => ({ value, label: value })) },
  { name: 'hdr', label: 'HDR', type: 'select', options: ['HDR10', 'HDR10+', 'Dolby Vision', 'HLG'].map(value => ({ value, label: value })) },
  { name: 'audioCodec', label: 'Audio codec', type: 'select', options: ['Dolby Atmos', 'Dolby TrueHD', 'DTS-HD MA', 'DTS', 'AAC', 'FLAC'].map(value => ({ value, label: value })) },
  { name: 'audioChannels', label: 'Audio channels', type: 'select', options: ['Mono', 'Stereo', '5.1', '7.1', '7.1.2', '7.1.4'].map(value => ({ value, label: value })) },
  { name: 'bitrate', label: 'Bitrate', type: 'number', help: 'Kilobits per second' },
  { name: 'is3d', label: '3D', type: 'checkbox' },
  { name: 'purchasePrice', label: 'Purchase price', type: 'number' },
  { name: 'purchaseLocation', label: 'Location', type: 'text' },
  { name: 'collectedAt', label: 'Collected at', type: 'text', help: 'YYYY-MM-DD' },
];

const BOOK_FIELDS = [
  { name: 'format', label: 'Format', type: 'select', options: ['Hardcover', 'Paperback', 'Trade Paperback', 'Digital', 'Audiobook'].map(value => ({ value, label: value })) },
  { name: 'purchasePrice', label: 'Purchase price', type: 'number' },
  { name: 'purchaseLocation', label: 'Location', type: 'text' },
  { name: 'collectedAt', label: 'Collected at', type: 'text', help: 'YYYY-MM-DD' },
];

const GAME_FIELDS = [
  { name: 'format', label: 'Format', type: 'select', options: ['Physical', 'Digital', 'ROM', 'Subscription', 'Cloud'].map(value => ({ value, label: value })) },
  { name: 'resolution', label: 'Platform', type: 'select', options: ['PC (Windows)', 'Mac', 'Steam Deck', 'PlayStation 5', 'Xbox Series X|S', 'Nintendo Switch', 'Mobile (iOS)'].map(value => ({ value, label: value })) },
  { name: 'hdr', label: 'Edition', type: 'select', options: ['Standard', 'Deluxe', 'Gold', 'Ultimate', "Collector's", 'Game of the Year', 'Complete', 'Definitive'].map(value => ({ value, label: value })) },
  { name: 'purchasePrice', label: 'Purchase price', type: 'number' },
  { name: 'purchaseLocation', label: 'Location', type: 'text' },
  { name: 'collectedAt', label: 'Collected at', type: 'text', help: 'YYYY-MM-DD' },
];

const MUSIC_FIELDS = [
  { name: 'format', label: 'Format', type: 'select', options: ['Vinyl', 'CD', 'Digital', 'Cassette', 'SACD', 'Streaming'].map(value => ({ value, label: value })) },
  { name: 'audioCodec', label: 'Audio codec', type: 'select', options: ['FLAC', 'MP3', 'AAC', 'ALAC', 'WAV', 'OGG', 'Opus'].map(value => ({ value, label: value })) },
  { name: 'audioChannels', label: 'Audio channels', type: 'select', options: ['Mono', 'Stereo', '5.1', '7.1'].map(value => ({ value, label: value })) },
  { name: 'bitrate', label: 'Bitrate', type: 'number' },
  { name: 'purchasePrice', label: 'Purchase price', type: 'number' },
  { name: 'purchaseLocation', label: 'Location', type: 'text' },
  { name: 'collectedAt', label: 'Collected at', type: 'text', help: 'YYYY-MM-DD' },
];

const MEDIUM_FIELDS = {
  video: VIDEO_FIELDS,
  books: BOOK_FIELDS,
  games: GAME_FIELDS,
  music: MUSIC_FIELDS,
};

function mediumFor(mediaType) {
  if (mediaType === 'book' || mediaType === 'comic' || mediaType === 'manga') return 'books';
  if (mediaType === 'game' || mediaType === 'boardgame') return 'games';
  if (mediaType === 'music' || mediaType === 'podcast') return 'music';
  return 'video';
}

const DEMO_ITEMS = [
  {
    id: 'quiet-orbit',
    mediaType: 'tv',
    title: 'The Quiet Orbit',
    identity: { mediaType: 'tv', source: 'tmdb', mediaId: '76479' },
    image: { src: 'https://picsum.photos/seed/floppy-orbit/400/600', fallback: '' },
    format: '4K Blu-ray',
    resolution: '4K',
    hdr: 'Dolby Vision',
    location: 'Shelf A',
    rating: 8.6,
    collectedAt: '2026-10-01',
    releaseDate: '2024-02-08',
    lastWatched: '2026-10-18',
    completeness: { collected: 6, total: 10, isPartial: true },
    seasons: [
      { number: 1, label: 'Season 1 · 8 episodes' },
      { number: 2, label: 'Season 2 · 2 episodes' },
    ],
    customValues: { 1: 'Collector edition', 2: 'Good', 4: 'Shelf A' },
    copies: [
      {
        id: 'orbit-copy-1', label: '4K Blu-ray', mediaType: '4K Blu-ray', resolution: '4K',
        hdr: 'Dolby Vision', audioCodec: 'Dolby Atmos', audioChannels: '7.1.4',
        purchasePrice: '39.99', purchaseLocation: 'Shelf A', collectedAt: '2026-10-01',
      },
      {
        id: 'orbit-copy-2', label: 'Digital', mediaType: 'Digital', resolution: '4K',
        hdr: 'HDR10', purchaseLocation: 'Apple TV', collectedAt: '2026-02-02',
      },
    ],
  },
  {
    id: 'dune-part-two',
    mediaType: 'movie',
    title: 'Dune: Part Two',
    identity: { mediaType: 'movie', source: 'tmdb', mediaId: '693134' },
    image: { src: 'https://picsum.photos/seed/floppy-dune/400/600', fallback: '' },
    format: '4K Blu-ray',
    resolution: '4K',
    hdr: 'Dolby Vision',
    location: 'Shelf A',
    rating: 9,
    collectedAt: '2026-03-14',
    releaseDate: '2024-03-01',
    lastWatched: '2026-09-02',
    customValues: { 1: 'Steelbook', 2: 'Mint', 4: 'Shelf A' },
    copies: [{
      id: 'dune-copy-1', label: 'Steelbook', mediaType: '4K Blu-ray', resolution: '4K',
      hdr: 'Dolby Vision', audioCodec: 'Dolby Atmos', audioChannels: '7.1.4',
      purchasePrice: '34.99', purchaseLocation: 'Shelf A', collectedAt: '2026-03-14',
    }],
  },
  {
    id: 'hades-two',
    mediaType: 'game',
    title: 'Hades II',
    identity: { mediaType: 'game', source: 'igdb', mediaId: '127367' },
    image: { src: 'https://picsum.photos/seed/floppy-hades/800/450', fallback: '' },
    format: 'Digital',
    resolution: 'Steam Deck',
    hdr: 'Deluxe',
    location: 'Steam',
    rating: 8.8,
    collectedAt: '2026-09-25',
    releaseDate: '2025-06-05',
    lastWatched: '2026-10-12',
    customValues: { 1: 'Early access', 2: 'Good', 4: 'Steam' },
    copies: [{
      id: 'hades-copy-1', label: 'Deluxe', mediaType: 'Digital', resolution: 'Steam Deck',
      hdr: 'Deluxe', purchaseLocation: 'Steam', collectedAt: '2026-09-25',
    }],
  },
  {
    id: 'paper-lanterns',
    mediaType: 'book',
    title: 'Paper Lanterns',
    identity: { mediaType: 'book', source: 'openlibrary', mediaId: 'OL27448W' },
    image: { src: 'https://picsum.photos/seed/floppy-lanterns/400/600', fallback: '' },
    format: 'Hardcover',
    location: 'Shelf B',
    rating: 7.5,
    collectedAt: '2026-05-11',
    releaseDate: '2022-10-04',
    lastWatched: '2026-07-30',
    customValues: { 1: 'Signed first edition', 2: 'Mint', 3: true, 4: 'Shelf B' },
    copies: [{
      id: 'lanterns-copy-1', label: 'Hardcover', mediaType: 'Hardcover',
      purchasePrice: '28.00', purchaseLocation: 'Shelf B', collectedAt: '2026-05-11',
    }],
  },
  {
    id: 'signal-static',
    mediaType: 'podcast',
    title: 'Signal & Static',
    identity: { mediaType: 'podcast', source: 'pocketcasts', mediaId: 'signal-carrier-wave' },
    image: { src: 'https://picsum.photos/seed/floppy-signal/400/400', fallback: '' },
    format: 'Digital',
    location: 'Pocket Casts',
    rating: 8.1,
    collectedAt: '2026-01-19',
    releaseDate: '2023-09-14',
    lastWatched: '2026-10-26',
    customValues: { 1: 'Subscriber feed', 4: 'Pocket Casts' },
    copies: [{
      id: 'signal-copy-1', label: 'Subscriber feed', mediaType: 'Digital',
      purchaseLocation: 'Pocket Casts', collectedAt: '2026-01-19',
    }],
  },
  {
    id: 'saga-61',
    mediaType: 'comic',
    title: 'Saga',
    identity: { mediaType: 'comic', source: 'comicvine', mediaId: '4050-25793' },
    image: { src: 'https://picsum.photos/seed/floppy-saga/400/600', fallback: '' },
    format: 'Trade Paperback',
    location: 'Shelf C',
    rating: 9.1,
    collectedAt: '2026-10-28',
    releaseDate: '2025-11-12',
    lastWatched: '2026-11-01',
    copyLabel: 'Vol. 61',
    customValues: { 1: 'First printing', 2: 'Good', 4: 'Shelf C', 5: 61 },
    copies: [{
      id: 'saga-copy-1', label: 'Vol. 61', mediaType: 'Trade Paperback',
      purchaseLocation: 'Shelf C', collectedAt: '2026-10-28',
    }],
  },
  {
    id: 'night-drive',
    mediaType: 'music',
    title: 'Night Drive',
    identity: { mediaType: 'music', source: 'musicbrainz', mediaId: 'night-drive' },
    image: { src: 'https://picsum.photos/seed/floppy-night-drive/400/400', fallback: '' },
    format: 'Vinyl',
    location: 'Shelf D',
    rating: 8,
    collectedAt: '2026-06-12',
    releaseDate: '2024-05-17',
    lastWatched: '2026-09-18',
    customValues: { 1: 'Translucent blue', 2: 'Mint', 4: 'Shelf D' },
    copies: [{
      id: 'night-copy-1', label: 'Vinyl', mediaType: 'Vinyl', audioCodec: 'FLAC',
      audioChannels: 'Stereo', purchasePrice: '31.00', purchaseLocation: 'Shelf D',
      collectedAt: '2026-06-12',
    }],
  },
  {
    id: 'lantern-keeper',
    mediaType: 'book',
    title: 'The Lantern Keeper',
    identity: { mediaType: 'book', source: 'openlibrary', mediaId: 'OL3394711W' },
    image: { src: 'https://picsum.photos/seed/floppy-keeper/400/600', fallback: '' },
    format: 'Paperback',
    location: 'Shelf B',
    rating: 7.2,
    collectedAt: '2026-08-03',
    releaseDate: '2021-09-07',
    lastWatched: '2026-08-19',
    customValues: { 1: 'Book club edition', 2: 'Worn', 4: 'Shelf B' },
    copies: [{
      id: 'keeper-copy-1', label: 'Paperback', mediaType: 'Paperback',
      purchasePrice: '18.99', purchaseLocation: 'Shelf B', collectedAt: '2026-08-03',
    }],
  },
  {
    id: 'severance',
    mediaType: 'tv',
    title: 'Severance',
    identity: { mediaType: 'tv', source: 'tmdb', mediaId: '95396' },
    image: { src: 'https://picsum.photos/seed/floppy-severance/400/600', fallback: '' },
    format: 'Digital',
    resolution: '4K',
    hdr: 'Dolby Vision',
    location: 'Apple TV',
    rating: 8.9,
    collectedAt: '2026-04-08',
    releaseDate: '2022-02-18',
    lastWatched: '2026-08-21',
    completeness: { collected: 9, total: 9, isPartial: false },
    seasons: [{ number: 1, label: 'Season 1 · 9 episodes' }],
    customValues: { 1: 'Apple TV purchase', 2: 'Mint', 4: 'Apple TV' },
    copies: [{
      id: 'severance-copy-1', label: 'Digital', mediaType: 'Digital', resolution: '4K',
      hdr: 'Dolby Vision', audioCodec: 'Dolby Atmos', audioChannels: '5.1',
      purchasePrice: '24.99', purchaseLocation: 'Apple TV', collectedAt: '2026-04-08',
    }],
  },
  {
    id: 'the-bear',
    mediaType: 'tv',
    title: 'The Bear',
    identity: { mediaType: 'tv', source: 'tmdb', mediaId: '136315' },
    image: { src: 'https://picsum.photos/seed/floppy-bear/400/600', fallback: '' },
    format: 'Digital',
    resolution: '1080p',
    hdr: 'HDR10',
    location: 'Hulu',
    rating: 8.2,
    collectedAt: '2025-11-02',
    releaseDate: '2022-06-23',
    lastWatched: '2026-07-11',
    completeness: { collected: 4, total: 10, isPartial: true },
    seasons: [
      { number: 1, label: 'Season 1 · 8 episodes' },
      { number: 2, label: 'Season 2 · 2 episodes' },
    ],
    customValues: { 1: 'Streaming access', 2: 'Good', 4: 'Hulu' },
    copies: [{
      id: 'bear-copy-1', label: 'Streaming access', mediaType: 'Digital', resolution: '1080p',
      hdr: 'HDR10', audioCodec: 'AAC', audioChannels: '5.1',
      purchaseLocation: 'Hulu', collectedAt: '2025-11-02',
    }],
  },
  {
    id: 'arrival',
    mediaType: 'movie',
    title: 'Arrival',
    identity: { mediaType: 'movie', source: 'tmdb', mediaId: '329865' },
    image: { src: 'https://picsum.photos/seed/floppy-arrival/400/600', fallback: '' },
    format: '4K Blu-ray',
    resolution: '4K',
    hdr: 'HDR10',
    location: 'Shelf A',
    rating: 9.2,
    collectedAt: '2026-02-09',
    releaseDate: '2016-11-11',
    lastWatched: '2026-10-03',
    customValues: { 1: 'Limited edition', 2: 'Mint', 4: 'Shelf A' },
    copies: [{
      id: 'arrival-copy-1', label: '4K Blu-ray', mediaType: '4K Blu-ray', resolution: '4K',
      hdr: 'HDR10', audioCodec: 'DTS-HD MA', audioChannels: '7.1',
      purchasePrice: '29.99', purchaseLocation: 'Shelf A', collectedAt: '2026-02-09',
    }],
  },
  {
    id: 'oppenheimer',
    mediaType: 'movie',
    title: 'Oppenheimer',
    identity: { mediaType: 'movie', source: 'tmdb', mediaId: '872585' },
    image: { src: 'https://picsum.photos/seed/floppy-oppenheimer/400/600', fallback: '' },
    format: 'Blu-ray',
    resolution: '1080p',
    location: 'Shelf A',
    rating: 8.7,
    collectedAt: '2026-01-05',
    releaseDate: '2023-07-21',
    lastWatched: '2026-04-14',
    customValues: { 1: 'Two-disc edition', 2: 'Good', 4: 'Shelf A' },
    copies: [{
      id: 'oppenheimer-copy-1', label: 'Blu-ray', mediaType: 'Blu-ray', resolution: '1080p',
      audioCodec: 'DTS-HD MA', audioChannels: '5.1',
      purchasePrice: '22.99', purchaseLocation: 'Shelf A', collectedAt: '2026-01-05',
    }],
  },
  {
    id: 'outer-wilds',
    mediaType: 'game',
    title: 'Outer Wilds',
    identity: { mediaType: 'game', source: 'igdb', mediaId: '126593' },
    image: { src: 'https://picsum.photos/seed/floppy-outer-wilds/800/450', fallback: '' },
    format: 'Digital',
    resolution: 'PC (Windows)',
    hdr: 'Standard',
    location: 'Steam',
    rating: 9.5,
    collectedAt: '2025-07-14',
    releaseDate: '2019-05-28',
    lastWatched: '2026-06-29',
    customValues: { 1: 'Archaeologist Edition', 2: 'Mint', 4: 'Steam' },
    copies: [{
      id: 'wilds-copy-1', label: 'Archaeologist Edition', mediaType: 'Digital',
      resolution: 'PC (Windows)', hdr: 'Standard', purchasePrice: '24.49',
      purchaseLocation: 'Steam', collectedAt: '2025-07-14',
    }],
  },
  {
    id: 'baldurs-gate',
    mediaType: 'game',
    title: "Baldur's Gate 3",
    identity: { mediaType: 'game', source: 'igdb', mediaId: '119171' },
    image: { src: 'https://picsum.photos/seed/floppy-baldurs-gate/800/450', fallback: '' },
    format: 'Digital',
    resolution: 'PlayStation 5',
    hdr: 'Deluxe',
    location: 'PlayStation Store',
    rating: 9.6,
    collectedAt: '2026-07-30',
    releaseDate: '2023-08-03',
    lastWatched: '2026-10-27',
    customValues: { 1: 'Digital Deluxe', 2: 'Mint', 4: 'PlayStation Store' },
    copies: [{
      id: 'baldurs-copy-1', label: 'Digital Deluxe', mediaType: 'Digital',
      resolution: 'PlayStation 5', hdr: 'Deluxe', purchasePrice: '79.99',
      purchaseLocation: 'PlayStation Store', collectedAt: '2026-07-30',
    }],
  },
  {
    id: 'piranesi',
    mediaType: 'book',
    title: 'Piranesi',
    identity: { mediaType: 'book', source: 'openlibrary', mediaId: 'OL20894559W' },
    image: { src: 'https://picsum.photos/seed/floppy-piranesi/400/600', fallback: '' },
    format: 'Hardcover',
    location: 'Shelf B',
    rating: 8.4,
    collectedAt: '2026-02-22',
    releaseDate: '2020-09-15',
    lastWatched: '2026-03-18',
    customValues: { 1: 'First edition', 2: 'Mint', 3: false, 4: 'Shelf B' },
    copies: [{
      id: 'piranesi-copy-1', label: 'Hardcover', mediaType: 'Hardcover',
      purchasePrice: '26.00', purchaseLocation: 'Shelf B', collectedAt: '2026-02-22',
    }],
  },
  {
    id: 'memory-empire',
    mediaType: 'book',
    title: 'A Memory Called Empire',
    identity: { mediaType: 'book', source: 'openlibrary', mediaId: 'OL20078351W' },
    image: { src: 'https://picsum.photos/seed/floppy-memory/400/600', fallback: '' },
    format: 'Paperback',
    location: 'Shelf B',
    rating: 7,
    collectedAt: '2025-08-21',
    releaseDate: '2019-03-26',
    lastWatched: '2026-01-07',
    customValues: { 1: 'Book club edition', 2: 'Worn', 4: 'Shelf B' },
    copies: [{
      id: 'memory-copy-1', label: 'Paperback', mediaType: 'Paperback',
      purchasePrice: '17.50', purchaseLocation: 'Shelf B', collectedAt: '2025-08-21',
    }],
  },
  {
    id: 'blue-sunday',
    mediaType: 'music',
    title: 'Blue Sunday',
    identity: { mediaType: 'music', source: 'musicbrainz', mediaId: 'blue-sunday' },
    image: { src: 'https://picsum.photos/seed/floppy-blue-sunday/400/400', fallback: '' },
    format: 'Vinyl',
    location: 'Shelf D',
    rating: 8.5,
    collectedAt: '2026-11-01',
    releaseDate: '2025-03-21',
    lastWatched: '2026-11-03',
    customValues: { 1: '180g pressing', 2: 'Mint', 4: 'Shelf D' },
    copies: [{
      id: 'sunday-copy-1', label: 'Vinyl', mediaType: 'Vinyl', audioCodec: 'FLAC',
      audioChannels: 'Stereo', purchasePrice: '34.00', purchaseLocation: 'Shelf D',
      collectedAt: '2026-11-01',
    }],
  },
  {
    id: 'long-signal',
    mediaType: 'podcast',
    title: 'The Long Signal',
    identity: { mediaType: 'podcast', source: 'pocketcasts', mediaId: 'the-long-signal' },
    image: { src: 'https://picsum.photos/seed/floppy-long-signal/400/400', fallback: '' },
    format: 'Digital',
    location: 'Pocket Casts',
    rating: 7.9,
    collectedAt: '2026-03-30',
    releaseDate: '2024-01-08',
    lastWatched: '2026-10-19',
    customValues: { 1: 'Subscriber feed', 4: 'Pocket Casts' },
    copies: [{
      id: 'long-signal-copy-1', label: 'Subscriber feed', mediaType: 'Digital',
      purchaseLocation: 'Pocket Casts', collectedAt: '2026-03-30',
    }],
  },
  {
    id: 'monstress',
    mediaType: 'comic',
    title: 'Monstress',
    identity: { mediaType: 'comic', source: 'comicvine', mediaId: '4050-74693' },
    image: { src: 'https://picsum.photos/seed/floppy-monstress/400/600', fallback: '' },
    format: 'Trade Paperback',
    location: 'Shelf C',
    rating: 8.8,
    collectedAt: '2026-09-09',
    releaseDate: '2016-11-08',
    lastWatched: '2026-09-22',
    copyLabel: 'Vol. 1',
    customValues: { 1: 'First printing', 2: 'Mint', 4: 'Shelf C', 5: 1 },
    copies: [{
      id: 'monstress-copy-1', label: 'Vol. 1', mediaType: 'Trade Paperback',
      purchaseLocation: 'Shelf C', collectedAt: '2026-09-09',
    }],
  },
  {
    id: 'blue-eye',
    mediaType: 'anime',
    title: 'Blue Eye Samurai',
    identity: { mediaType: 'anime', source: 'tmdb', mediaId: '210935' },
    image: { src: 'https://picsum.photos/seed/floppy-blue-eye/400/600', fallback: '' },
    format: 'Digital',
    resolution: '4K',
    hdr: 'Dolby Vision',
    location: 'Netflix',
    rating: 9,
    collectedAt: '2026-05-05',
    releaseDate: '2023-11-03',
    lastWatched: '2026-06-02',
    completeness: { collected: 8, total: 8, isPartial: false },
    seasons: [{ number: 1, label: 'Season 1 · 8 episodes' }],
    customValues: { 1: 'Streaming access', 2: 'Mint', 4: 'Netflix' },
    copies: [{
      id: 'blue-eye-copy-1', label: 'Streaming access', mediaType: 'Digital', resolution: '4K',
      hdr: 'Dolby Vision', audioCodec: 'Dolby Atmos', audioChannels: '5.1',
      purchaseLocation: 'Netflix', collectedAt: '2026-05-05',
    }],
  },
  {
    id: 'home-studio',
    mediaType: 'video',
    title: 'Building a Home Studio',
    identity: { mediaType: 'video', source: 'manual', mediaId: 'home-studio' },
    image: { src: 'https://picsum.photos/seed/floppy-studio/800/450', fallback: '' },
    format: 'Digital',
    resolution: '1080p',
    location: 'Drive',
    rating: null,
    collectedAt: '2026-10-20',
    releaseDate: '2024-04-12',
    lastWatched: '2026-10-20',
    customValues: { 1: 'Creator download', 4: 'Drive' },
    copies: [{
      id: 'studio-copy-1', label: 'Creator download', mediaType: 'Digital',
      resolution: '1080p', audioCodec: 'AAC', audioChannels: 'Stereo',
      purchaseLocation: 'Drive', collectedAt: '2026-10-20',
    }],
  },
];

const DEMO_FIELD_GROUPS = [
  {
    id: 'g1',
    name: 'Physical details',
    fields: [
      { id: '1', label: 'Edition', fieldType: 'text', options: [], mediaTypes: ['movie', 'tv', 'anime', 'book', 'comic', 'manga', 'game', 'music', 'podcast', 'video'] },
      { id: '2', label: 'Condition', fieldType: 'select', options: ['Mint', 'Good', 'Worn'], mediaTypes: ['movie', 'tv', 'anime', 'book', 'comic', 'manga', 'game', 'music', 'podcast', 'video'] },
      { id: '3', label: 'Signed', fieldType: 'checkbox', options: [], mediaTypes: ['book', 'comic', 'manga'] },
    ],
  },
  {
    id: 'g2',
    name: 'Storage',
    fields: [
      { id: '4', label: 'Shelf', fieldType: 'text', options: [], mediaTypes: ['movie', 'tv', 'anime', 'book', 'comic', 'manga', 'game', 'music', 'podcast', 'video'] },
      { id: '5', label: 'Volume', fieldType: 'number', options: [], mediaTypes: ['comic', 'manga'] },
    ],
  },
];

const FIELD_TYPE_CHOICES = [
  { value: 'text', label: 'Text' },
  { value: 'number', label: 'Number' },
  { value: 'date', label: 'Date' },
  { value: 'select', label: 'Select' },
  { value: 'checkbox', label: 'Checkbox' },
];

const MEDIA_TYPE_CHOICES = ['movie', 'tv', 'anime', 'book', 'manga', 'comic', 'game', 'boardgame', 'music', 'podcast', 'video']
  .map(value => ({ value, label: MEDIA_LABELS[value] || value }));

const DEFAULT_FILTERS = {
  type: 'all',
  format: 'all',
  resolution: 'all',
  hdr: 'all',
  location: 'all',
  rating: 'all',
  completeness: 'all',
  customFilter: '',
  customValue: '',
  query: '',
  sort: 'collected_at',
  direction: 'desc',
  view: 'grid',
};

function valuesFromForm(fields, item) {
  const copy = item?.copies?.[0] || {};
  const values = {};
  fields.forEach(field => {
    const fallback = field.name === 'format' ? copy.mediaType || item?.format
      : field.name === 'resolution' ? copy.resolution || item?.resolution
        : field.name === 'hdr' ? copy.hdr || item?.hdr
          : field.name === 'purchaseLocation' ? copy.purchaseLocation || (item && item.location)
            : copy[field.name] ?? item?.[field.name] ?? '';
    values[field.name] = fallback == null ? '' : String(fallback);
  });
  return values;
}

function copyLabelFor(values, groups) {
  const fields = groups.flatMap(group => group.fields || []);
  const volume = fields.find(field => field.label.trim().toLowerCase() === 'volume');
  if (volume && values[String(volume.id)] != null && values[String(volume.id)] !== '') {
    return `Vol. ${values[String(volume.id)]}`;
  }
  const issue = fields.find(field => ['issue', 'issue nr'].includes(field.label.trim().toLowerCase()));
  if (issue && values[String(issue.id)] != null && values[String(issue.id)] !== '') {
    return `#${values[String(issue.id)]}`;
  }
  return 'Copy';
}

function groupForItem(item, groups) {
  if (!item) return [];
  return groups
    .map(group => ({
      ...group,
      fields: group.fields.filter(field => (field.mediaTypes || []).includes(item.mediaType)),
    }))
    .filter(group => group.fields.length);
}

function itemLocation(item) {
  return item.purchaseLocation || item.location || '';
}

function itemMatches(item, filters) {
  if (filters.type !== 'all' && item.mediaType !== filters.type) return false;
  if (filters.format !== 'all' && item.format !== filters.format) return false;
  if (filters.resolution !== 'all' && item.resolution !== filters.resolution) return false;
  if (filters.hdr !== 'all' && item.hdr !== filters.hdr) return false;
  if (filters.location !== 'all' && itemLocation(item) !== filters.location) return false;
  if (filters.rating === 'rated' && item.rating == null) return false;
  if (filters.rating === 'not_rated' && item.rating != null) return false;
  if (filters.completeness === 'partial' && !item.completeness?.isPartial) return false;
  if (filters.completeness === 'full' && (!item.completeness || item.completeness.isPartial)) return false;
  if (filters.customFilter && filters.customValue) {
    const value = item.customValues?.[filters.customFilter];
    if (String(value) !== String(filters.customValue)) return false;
  }
  const query = (filters.query || '').trim().toLowerCase();
  if (query && !`${item.title} ${item.format || ''} ${itemLocation(item)}`.toLowerCase().includes(query)) {
    return false;
  }
  return true;
}

function sortItems(items, filters) {
  const direction = filters.direction === 'asc' ? 1 : -1;
  const sorted = [...items];
  sorted.sort((left, right) => {
    if (filters.sort === 'title') return left.title.localeCompare(right.title) * direction;
    if (filters.sort === 'release') {
      return String(left.releaseDate || left.collectedAt).localeCompare(String(right.releaseDate || right.collectedAt)) * direction;
    }
    if (filters.sort === 'rating') return ((left.rating || 0) - (right.rating || 0)) * direction;
    if (filters.sort === 'last_watched') {
      return String(left.lastWatched || '').localeCompare(String(right.lastWatched || '')) * direction;
    }
    return String(left.collectedAt).localeCompare(String(right.collectedAt)) * direction;
  });
  return sorted;
}

function applyFilterIntent(filters, intent) {
  if (intent.type === 'reset') return { ...DEFAULT_FILTERS, view: filters.view };
  if (intent.type === 'type') return { ...filters, type: intent.value || 'all' };
  if (intent.type === 'completeness') return { ...filters, completeness: intent.value || 'all' };
  if (intent.type === 'set') return { ...filters, [intent.key]: intent.value };
  return filters;
}

function buildOptions(items) {
  const unique = key => [...new Set(items.map(item => item[key]).filter(Boolean))]
    .sort()
    .map(value => ({ value, label: value }));
  const formats = unique('format');
  const locations = [...new Set(items.map(itemLocation).filter(Boolean))]
    .sort()
    .map(value => ({ value, label: value }));
  return {
    mediaTypes: Object.keys(MEDIA_LABELS)
      .filter(value => items.some(item => item.mediaType === value))
      .map(value => ({ value, label: MEDIA_LABELS[value] })),
    formats,
    resolutions: unique('resolution'),
    hdrs: unique('hdr'),
    locations,
    sorts: [
      { value: 'collected_at', label: 'Date collected' },
      { value: 'title', label: 'Title' },
      { value: 'release', label: 'Release date' },
      { value: 'rating', label: 'Rating' },
      { value: 'last_watched', label: 'Last watched' },
    ],
    customFilter: {
      id: '2',
      label: 'Condition',
      choices: ['Mint', 'Good', 'Worn'].map(value => ({ value, label: value })),
    },
  };
}

function toBrowserItem(item) {
  return {
    ...item,
    mediaTypeLabel: MEDIA_LABELS[item.mediaType] || item.mediaType,
    mediaTypeColor: MEDIA_COLORS[item.mediaType] || palette.accent,
    purchaseLocation: itemLocation(item),
    copyLabel: item.copyLabel || '',
  };
}

const PAGE_SIZE = 6;
const ROW_BATCH = 2;
const TABLE_COLUMNS = ['title', 'type', 'format', 'location', 'collected'];

function filterSignature(filters) {
  const { view, ...rest } = filters;
  return JSON.stringify(rest);
}

function buildGroups(items, limits, loadingKey) {
  const byType = new Map();
  items.forEach(item => {
    if (!byType.has(item.mediaType)) byType.set(item.mediaType, []);
    byType.get(item.mediaType).push(item);
  });
  return [...byType.entries()].map(([type, rows]) => {
    const limit = limits[type] ?? ROW_BATCH;
    const loaded = rows.slice(0, limit);
    return {
      key: type,
      label: MEDIA_LABELS[type] || type,
      items: loaded.map(toBrowserItem),
      loadedCount: loaded.length,
      total: rows.length,
      hasMore: loaded.length < rows.length,
      loadingMore: loadingKey === type,
    };
  });
}

export default function CollectionScreen({ navigate, onBack }) {
  const [items, setItems] = useState(DEMO_ITEMS);
  const [filters, setFilters] = useState(DEFAULT_FILTERS);
  const [owner, setOwner] = useState(true);
  const [selectedId, setSelectedId] = useState(null);
  const [editingId, setEditingId] = useState(null);
  const [formValues, setFormValues] = useState({});
  const [formErrors, setFormErrors] = useState({});
  const [scope, setScope] = useState('item');
  const [selectedSeason, setSelectedSeason] = useState('1');
  const [saveNote, setSaveNote] = useState('');
  const [customGroups, setCustomGroups] = useState(DEMO_FIELD_GROUPS);
  const [customDraft, setCustomDraft] = useState(DEMO_FIELD_GROUPS);
  const [customErrors, setCustomErrors] = useState({});
  const [manageFields, setManageFields] = useState(false);
  const [page, setPage] = useState(1);
  const [rowLimits, setRowLimits] = useState({});
  const [loadingMore, setLoadingMore] = useState(false);
  const [loadingRow, setLoadingRow] = useState('');
  const [collectionNotice, setCollectionNotice] = useState('');

  const options = useMemo(() => buildOptions(items), [items]);
  const filteredItems = useMemo(
    () => sortItems(items.filter(item => itemMatches(item, filters)), filters),
    [items, filters],
  );
  const totalCount = filteredItems.length;
  const isRows = filters.view === 'rows';
  const visibleItems = useMemo(
    () => (isRows ? filteredItems : filteredItems.slice(0, page * PAGE_SIZE)).map(toBrowserItem),
    [filteredItems, isRows, page],
  );
  const groups = useMemo(
    () => (isRows ? buildGroups(filteredItems, rowLimits, loadingRow) : null),
    [filteredItems, isRows, rowLimits, loadingRow],
  );
  const hasMore = !isRows && totalCount > page * PAGE_SIZE;
  const signature = filterSignature(filters);
  const selectedItem = items.find(item => item.id === selectedId) || null;
  const selectedFields = selectedItem ? MEDIUM_FIELDS[mediumFor(selectedItem.mediaType)] || VIDEO_FIELDS : VIDEO_FIELDS;
  const selectedCustomGroups = groupForItem(selectedItem, customGroups);
  const selectedValues = selectedItem?.customValues || {};

  useEffect(() => {
    setPage(1);
    setRowLimits({});
    setLoadingMore(false);
    setLoadingRow('');
  }, [signature]);

  function changeFilters(intent) {
    setFilters(current => applyFilterIntent(current, intent));
    setCollectionNotice('');
  }

  function loadMore() {
    if (loadingMore || !hasMore) return;
    setLoadingMore(true);
    setCollectionNotice('Loading the next collection page…');
    setTimeout(() => {
      setPage(current => current + 1);
      setLoadingMore(false);
      setCollectionNotice('');
    }, 250);
  }

  function loadMoreGroup(group) {
    if (!group?.hasMore || loadingRow) return;
    const key = group.key;
    setLoadingRow(key);
    setCollectionNotice(`Loading more ${String(group.label || key).toLowerCase()}…`);
    setTimeout(() => {
      setRowLimits(current => ({ ...current, [key]: (current[key] ?? ROW_BATCH) + ROW_BATCH }));
      setLoadingRow('');
      setCollectionNotice('');
    }, 250);
  }

  function openCopy(item, copy = null) {
    setSelectedId(item.id);
    setEditingId(copy?.id || null);
    setFormValues(copy ? {
      format: copy.mediaType || '',
      resolution: copy.resolution || '',
      hdr: copy.hdr || '',
      audioCodec: copy.audioCodec || '',
      audioChannels: copy.audioChannels || '',
      bitrate: copy.bitrate == null ? '' : String(copy.bitrate),
      is3d: !!copy.is3d,
      purchasePrice: copy.purchasePrice || '',
      purchaseLocation: copy.purchaseLocation || '',
      collectedAt: copy.collectedAt || '',
    } : valuesFromForm(selectedFields, item));
    setFormErrors({});
    setScope('item');
    setSelectedSeason(String(item.seasons?.[0]?.number || '1'));
    setSaveNote('');
    setManageFields(false);
  }

  function closeCopy() {
    setSelectedId(null);
    setEditingId(null);
    setFormErrors({});
    setSaveNote('');
  }

  function changeForm(name, value) {
    setFormValues(current => ({ ...current, [name]: value }));
    setFormErrors(current => ({ ...current, [name]: '' }));
  }

  function validateCopy() {
    const errors = {};
    if (formValues.purchasePrice !== '' && Number.isNaN(Number(formValues.purchasePrice))) {
      errors.purchasePrice = 'Enter a number.';
    } else if (formValues.purchasePrice !== '' && Number(formValues.purchasePrice) < 0) {
      errors.purchasePrice = 'Must be at least zero.';
    }
    if (formValues.bitrate !== '' && Number.isNaN(Number(formValues.bitrate))) {
      errors.bitrate = 'Enter a number.';
    }
    if (formValues.collectedAt && !/^\d{4}-\d{2}-\d{2}$/.test(formValues.collectedAt)) {
      errors.collectedAt = 'Use YYYY-MM-DD.';
    }
    return errors;
  }

  function saveCopy() {
    if (!selectedItem || !owner) return;
    const errors = validateCopy();
    if (Object.keys(errors).length) {
      setFormErrors(errors);
      return;
    }
    const label = copyLabelFor(selectedValues, customGroups);
    const copy = {
      id: editingId || `${selectedItem.id}-copy-${Date.now()}`,
      label: label === 'Copy' ? formValues.format || 'Copy' : label,
      mediaType: formValues.format || '',
      resolution: formValues.resolution || '',
      hdr: formValues.hdr || '',
      audioCodec: formValues.audioCodec || '',
      audioChannels: formValues.audioChannels || '',
      bitrate: formValues.bitrate || '',
      is3d: !!formValues.is3d,
      purchasePrice: formValues.purchasePrice || '',
      purchaseLocation: formValues.purchaseLocation || '',
      collectedAt: formValues.collectedAt || '',
    };
    setItems(current => current.map(item => {
      if (item.id !== selectedItem.id) return item;
      const copies = editingId
        ? item.copies.map(existing => existing.id === editingId ? { ...existing, ...copy } : existing)
        : [...item.copies, copy];
      return {
        ...item,
        copies,
        format: copy.mediaType || item.format,
        resolution: copy.resolution || item.resolution,
        hdr: copy.hdr || item.hdr,
        location: copy.purchaseLocation || item.location,
        collectedAt: copy.collectedAt || item.collectedAt,
      };
    }));
    const cascadeCount = scope === 'episodes'
      ? selectedItem.seasons?.reduce((total, season) => total + Number(String(season.label).match(/(\d+) episodes/)?.[1] || 0), 0)
      : scope === 'season'
        ? Number(String(selectedItem.seasons?.find(season => String(season.number) === String(selectedSeason))?.label).match(/(\d+) episodes/)?.[1] || 0)
        : 0;
    setSaveNote(cascadeCount
      ? `Copy saved. ${cascadeCount} episode copies are created by the season cascade.`
      : 'Copy saved.');
    setEditingId(null);
    if (!editingId) {
      const nextCopies = [...selectedItem.copies, copy];
      setFormValues(valuesFromForm(selectedFields, { ...selectedItem, copies: nextCopies }));
    }
  }

  function removeCopy(copy) {
    if (!selectedItem || !owner) return;
    const nextCopies = selectedItem.copies.filter(existing => existing.id !== copy.id);
    setItems(current => current.map(item => item.id === selectedItem.id
      ? { ...item, copies: nextCopies }
      : item));
    if (editingId === copy.id) {
      setEditingId(null);
      setFormValues(valuesFromForm(selectedFields, { ...selectedItem, copies: nextCopies }));
    }
    setSaveNote(nextCopies.length ? 'Copy removed.' : 'Copy removed. This item now has no owned copies.');
  }

  function changeCustomValue(key, value) {
    if (!selectedItem || !owner) return;
    setItems(current => current.map(item => item.id === selectedItem.id
      ? { ...item, customValues: { ...(item.customValues || {}), [key]: value } }
      : item));
  }

  function validateFieldGroups(groups) {
    const errors = {};
    groups.forEach(group => {
      if (!String(group.name || '').trim()) errors.group = 'Every group needs a name.';
      group.fields.forEach(field => {
        if (!String(field.label || '').trim()) errors.field = 'Every field needs a label.';
        if (!(field.mediaTypes || []).length) {
          errors.field = `${field.label || 'A field'} needs at least one media type.`;
        }
        if ((field.fieldType || field.field_type) === 'select' && !String(field.optionsText || (field.options || []).join('\n')).trim()) {
          errors.options = `${field.label || 'A select field'} needs at least one option.`;
        }
      });
    });
    return errors;
  }

  function saveFieldGroups() {
    if (!owner) return;
    const errors = validateFieldGroups(customDraft);
    if (Object.keys(errors).length) {
      setCustomErrors(errors);
      return;
    }
    const normalized = customDraft.map(group => ({
      ...group,
      fields: group.fields.map(field => ({
        ...field,
        mediaTypes: field.mediaTypes || field.media_types || [],
        options: (field.fieldType || field.field_type) === 'select'
          ? String(field.optionsText || (field.options || []).join('\n')).split('\n').map(option => option.trim()).filter(Boolean)
          : [],
      })),
    }));
    setCustomGroups(normalized);
    setCustomDraft(normalized);
    setCustomErrors({});
    setManageFields(false);
    setSaveNote('Custom fields saved. Django still validates ownership and field ids on the server.');
  }

  const readOnlyLabel = owner ? 'Read-only preview' : 'Return to owner view';

  return <Screen title="Collection" subtitle="Every copy you own, grouped and labelled" onBack={onBack}>
    <View style={styles.demoBar}>
      <View style={styles.demoCopy}>
        <Text style={styles.demoTitle}>Owner collection</Text>
        <Text style={styles.demoText}>
          {owner
            ? 'Tap any cover or table row to open its copies, media fields and custom values. Server ownership and validation remain authoritative.'
            : 'Mutation controls are hidden for a read-only viewer. Copies and custom values stay visible.'}
        </Text>
      </View>
      <Button label={readOnlyLabel} tone="surface" palette={palette}
        onPress={() => {
          setOwner(current => !current);
          setManageFields(false);
        }} />
    </View>

    <CollectionBrowser
      items={visibleItems}
      groups={groups}
      filters={filters}
      options={options}
      resultCount={totalCount}
      tableColumns={TABLE_COLUMNS}
      hasMore={hasMore}
      loadingMore={loadingMore}
      palette={palette}
      onFilterChange={changeFilters}
      onLoadMore={loadMore}
      onLoadMoreGroup={loadMoreGroup}
      onOpenCopy={item => openCopy(items.find(entry => entry.id === item.id) || item)}
    />
    {collectionNotice ? <Text accessibilityLiveRegion="polite" style={styles.notice}>{collectionNotice}</Text> : null}

    <CollectionCopyDialog
      visible={!!selectedItem}
      item={selectedItem}
      copies={selectedItem?.copies || []}
      fields={selectedFields}
      values={formValues}
      errors={formErrors}
      palette={palette}
      canMutate={owner}
      scope={scope}
      seasons={selectedItem?.seasons || []}
      selectedSeason={selectedSeason}
      editingId={editingId}
      saveNote={saveNote}
      onClose={closeCopy}
      onChange={changeForm}
      onScopeChange={setScope}
      onSeasonChange={setSelectedSeason}
      onSave={saveCopy}
      onEdit={copy => openCopy(selectedItem, copy)}
      onRemove={removeCopy}
    >
      <CollectionFieldValueInputs
        groups={selectedCustomGroups}
        values={selectedValues}
        errors={{}}
        palette={palette}
        canEdit={owner}
        onChange={changeCustomValue}
      />
      {owner ? <Button
        label={manageFields ? 'Done managing fields' : 'Manage custom fields'}
        tone="surface"
        palette={palette}
        onPress={() => {
          setManageFields(current => !current);
          setCustomDraft(customGroups);
        }} /> : null}
      {owner && manageFields ? <CollectionFieldManager
        groups={customDraft}
        fieldTypes={FIELD_TYPE_CHOICES}
        mediaTypes={MEDIA_TYPE_CHOICES}
        palette={palette}
        canManage={owner}
        dirty={JSON.stringify(customDraft) !== JSON.stringify(customGroups)}
        error={customErrors.group || customErrors.field || customErrors.options || ''}
        onChange={setCustomDraft}
        onSave={saveFieldGroups}
        onReset={() => {
          setCustomDraft(customGroups);
          setCustomErrors({});
        }} /> : null}
    </CollectionCopyDialog>
  </Screen>;
}

const styles = StyleSheet.create({
  demoBar: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: spacing.md },
  demoCopy: { flex: 1, gap: 2 },
  demoTitle: { color: palette.text, fontSize: 14, fontWeight: '700' },
  demoText: { color: palette.textMuted, fontSize: 12, lineHeight: 17 },
  notice: { color: palette.textMuted, fontSize: 12, lineHeight: 17 },
});
