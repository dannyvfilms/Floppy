import React, { useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';
import * as ImagePicker from 'expo-image-picker';
import { ArtworkPicker, EditionPicker } from '../../../frontend/ui/ArtworkPicker';
import { palette, radius, spacing } from '../theme';

export const surface = {
  id: 'ARTWORK',
  status: 'ported',
  title: 'Cover and edition selection',
  where: 'Detail and tracking metadata for library items',
  note: 'The cover picker and edition picker use the shared ArtworkPicker and EditionPicker. Photo-library and camera choices stay in the Expo adapter, and saving is local demo state. The web keeps the server-owned upload, link fetch, permissions, CSRF and local-cover storage; those boundaries are not exercised on a device here.',
};

const artworkPalette = {
  ...palette,
  radius: radius.md,
  radiusSmall: radius.sm,
  button: {
    radius: radius.sm,
    primary: { background: palette.accentStrong, pressed: '#4338ca', hovered: '#4338ca', text: '#ffffff', border: 'transparent' },
    surface: { background: palette.surfaceStrong, pressed: palette.surfaceMuted, hovered: palette.surfaceMuted, text: palette.text, border: palette.border },
    focusStyle: {},
  },
};

const coverLabels = {
  choose: 'Choose photo',
  urlToggle: 'Enter a URL',
  urlPlaceholder: 'Link to an image, or to a book or comic page',
  urlLabel: 'Image or page link',
  save: 'Save cover',
  cancel: 'Cancel',
  candidatesLoading: 'Looking for other covers…',
  candidatesError: 'Other covers could not load.',
  candidatesEmpty: 'No other covers found.',
  saveError: 'Could not save that cover.',
};

const editionLabels = {
  selectedEdition: 'Selected',
  editionsLoading: 'Looking for editions…',
  editionsError: 'Editions could not load.',
  noEditions: 'No editions found.',
  noEditionsQuery: 'No editions match this search.',
  retry: 'Try again',
};

const candidates = [
  { id: 'cover-1', uri: 'https://picsum.photos/seed/floppy-orbit-alt/400/600', title: 'Northline edition' },
  { id: 'cover-2', uri: 'https://picsum.photos/seed/floppy-orbit-score/400/600', title: 'Soundtrack edition' },
  { id: 'cover-3', uri: 'https://picsum.photos/seed/floppy-orbit-art/400/600', title: 'Poster edition' },
];

const editions = [
  {
    id: 'hc-1',
    uri: 'https://picsum.photos/seed/floppy-orbit-book/80/100',
    title: 'The Quiet Orbit',
    meta: ['English · Hardcover'],
  },
  {
    id: 'hc-2',
    uri: 'https://picsum.photos/seed/floppy-orbit-book-de/80/100',
    title: 'Die stille Umlaufbahn',
    meta: ['German · Paperback'],
  },
  {
    id: 'hc-3',
    uri: 'https://picsum.photos/seed/floppy-orbit-book-audio/80/100',
    title: 'The Quiet Orbit',
    meta: ['English · Audiobook'],
  },
];

function selectedEditionRow(id) {
  return editions.find(row => row.id === id) || null;
}

export default function ArtworkSlot() {
  const [currentCover, setCurrentCover] = useState('https://picsum.photos/seed/floppy-orbit-detail/400/600');
  const [selectedCover, setSelectedCover] = useState(null);
  const [url, setUrl] = useState('');
  const [showUrl, setShowUrl] = useState(false);
  const [coverStatus, setCoverStatus] = useState('');
  const [editionQuery, setEditionQuery] = useState('');
  const [selectedEdition, setSelectedEdition] = useState(selectedEditionRow('hc-1'));
  const [editionStatus, setEditionStatus] = useState('');

  async function pickPhoto(source) {
    const options = { mediaTypes: ['images'], allowsMultipleSelection: false, quality: 1 };
    try {
      const result = source === 'camera'
        ? await ImagePicker.launchCameraAsync(options)
        : await ImagePicker.launchImageLibraryAsync(options);
      if (result.canceled || !result.assets?.length) return;
      const asset = result.assets[0];
      setSelectedCover({ kind: 'file', uri: asset.uri, title: asset.fileName || 'New cover' });
      setUrl('');
      setCoverStatus('');
    } catch (error) {
      setCoverStatus(error?.message || 'That photo could not be opened.');
    }
  }

  function changeUrl(value) {
    setUrl(value);
    const trimmed = value.trim();
    setSelectedCover(trimmed ? { kind: 'url', uri: trimmed, title: 'New cover' } : null);
    setCoverStatus('');
  }

  function resetCover() {
    setSelectedCover(null);
    setUrl('');
    setCoverStatus('');
  }

  function saveCover() {
    if (!selectedCover) return;
    setCurrentCover(selectedCover.uri);
    setSelectedCover(null);
    setUrl('');
    setCoverStatus('Cover updated.');
  }

  const needle = editionQuery.trim().toLowerCase();
  const visibleEditions = needle
    ? editions.filter(row => [row.title, ...row.meta].join(' ').toLowerCase().includes(needle))
    : editions;

  return <View style={styles.root}>
    {coverStatus ? <Text accessibilityLiveRegion="polite" style={styles.status}>{coverStatus}</Text> : null}
    <ArtworkPicker
      title="Cover"
      current={{ uri: currentCover }}
      candidates={candidates}
      selected={selectedCover}
      url={url}
      showUrl={showUrl}
      supportsDrag={false}
      cameraLabel="Take a photo"
      labels={coverLabels}
      palette={artworkPalette}
      onChooseFile={() => pickPhoto('library')}
      onCamera={() => pickPhoto('camera')}
      onToggleUrl={() => setShowUrl(value => !value)}
      onUrlChange={changeUrl}
      onPickCandidate={candidate => {
        setSelectedCover({ kind: 'candidate', id: candidate.id, uri: candidate.uri, title: candidate.title });
        setUrl('');
        setCoverStatus('');
      }}
      onReset={resetCover}
      onSave={saveCover}
    />

    <View style={styles.divider} />
    {editionStatus ? <Text accessibilityLiveRegion="polite" style={styles.status}>{editionStatus}</Text> : null}
    <EditionPicker
      title="Specific edition"
      description="Pick the edition used for this title's details and cover. Play history stays with the title."
      provider="Hardcover"
      query={editionQuery}
      placeholder="Search editions..."
      results={visibleEditions}
      selected={selectedEdition}
      selectedId={selectedEdition?.id}
      state="ready"
      open
      labels={editionLabels}
      palette={artworkPalette}
      onQueryChange={setEditionQuery}
      onFocus={() => {}}
      onSelect={row => {
        setSelectedEdition(row);
        setEditionStatus('Edition updated.');
      }}
    />
  </View>;
}

const styles = StyleSheet.create({
  root: { gap: spacing.md },
  divider: { height: 1, backgroundColor: palette.border, marginVertical: spacing.sm },
  status: { color: palette.success, fontSize: 12 },
});
