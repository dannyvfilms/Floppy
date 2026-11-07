import React, { useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { Button } from '../../../frontend/ui/Button';
import { palette, radius, spacing } from '../theme';

export const surface = {
  id: 'BUTTON',
  title: 'Primary, surface and danger actions',
  where: 'Save bars, Load more, provider actions and confirmations',
  status: 'ported',
  note: 'The shared React Native Button renders the primary save bar, surface Load more and Sync now, solid danger Delete and Disconnect, ghost-danger inline removal and danger-deep permanent delete in small and base sizes, with disabled and busy state and the shared accessibility role, label and state. Browser anchors, form submit and htmx attributes stay in the web implementation; native URL actions remain caller-owned through Linking. Runtime press, disabled and screen-reader behaviour were not verified on a device here, and the legacy controls.jsx islands and hand-written template buttons remain outside this surface.',
};

const buttonPalette = {
  primary: { background: palette.accentStrong, pressed: '#4338ca', hovered: '#4338ca', text: '#ffffff', border: 'transparent' },
  surface: { background: palette.surfaceStrong, pressed: palette.surfaceMuted, hovered: palette.surfaceMuted, text: palette.text, border: palette.border },
  'danger-solid': { background: palette.danger, pressed: '#b91c1c', hovered: '#b91c1c', text: '#ffffff', border: 'transparent' },
  'danger-deep': { background: '#b91c1c', pressed: '#991b1b', hovered: '#991b1b', text: '#ffffff', border: 'transparent' },
  'ghost-danger': { background: 'transparent', pressed: 'rgba(220, 38, 38, 0.2)', hovered: 'rgba(220, 38, 38, 0.2)', text: '#f87171', border: 'transparent' },
  radius: radius.sm,
  focusStyle: {},
};

const LAST_PAGE = 3;

export default function ButtonSlot() {
  const [saving, setSaving] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [page, setPage] = useState(1);
  const [tagRemoved, setTagRemoved] = useState(false);
  const [status, setStatus] = useState('');

  function save() {
    setSaving(true);
    setStatus('Saving settings…');
    setTimeout(() => {
      setSaving(false);
      setStatus('Settings saved');
    }, 600);
  }

  function loadMore() {
    setLoadingMore(true);
    const nextPage = Math.min(page + 1, LAST_PAGE);
    setTimeout(() => {
      setPage(nextPage);
      setLoadingMore(false);
      setStatus(nextPage >= LAST_PAGE ? 'All items loaded' : `Loaded page ${nextPage}`);
    }, 600);
  }

  function sync() {
    setSyncing(true);
    setStatus('Sync started');
    setTimeout(() => {
      setSyncing(false);
      setStatus('Sync finished');
    }, 600);
  }

  function removeTag() {
    setTagRemoved(true);
    setStatus('Favorite tag removed');
  }

  const allLoaded = page >= LAST_PAGE;

  return <View style={styles.group}>
    <Button label="Save settings" size="base" width="full" tone="primary"
      busy={saving} disabled={saving}
      accessibilityLabel="Save settings"
      onPress={save} palette={buttonPalette} />
    <View style={styles.row}>
      <Button label="Discard changes" size="base" tone="surface"
        disabled={saving}
        accessibilityLabel="Discard settings changes"
        onPress={() => setStatus('Settings changes discarded')} palette={buttonPalette} />
    </View>
    <View style={styles.row}>
      <Button label={allLoaded ? 'All loaded' : 'Load more'} tone="surface"
        busy={loadingMore} disabled={loadingMore || allLoaded}
        accessibilityLabel={allLoaded ? 'All items loaded' : 'Load more items'}
        onPress={loadMore} palette={buttonPalette} />
      <Button label="Delete list" tone="danger-solid"
        disabled={saving}
        accessibilityLabel="Delete this list"
        onPress={() => setStatus('Deleting needs confirmation on the list screen')} palette={buttonPalette} />
    </View>
    <View style={styles.row}>
      <Button label="Sync now" tone="surface"
        busy={syncing} disabled={syncing}
        accessibilityLabel="Sync AniList now"
        onPress={sync} palette={buttonPalette} />
      <Button label="Disconnect" tone="danger-solid"
        disabled={syncing}
        accessibilityLabel="Disconnect AniList"
        onPress={() => setStatus('Disconnecting needs confirmation on the provider screen')} palette={buttonPalette} />
    </View>
    <View style={styles.row}>
      <Button label={tagRemoved ? 'Tag removed' : 'Remove tag'} tone="ghost-danger"
        disabled={tagRemoved}
        accessibilityLabel="Delete Favorite tag"
        onPress={removeTag} palette={buttonPalette} />
      <Button label="Delete permanently" tone="danger-deep"
        accessibilityLabel="Delete list permanently"
        onPress={() => setStatus('Permanent delete needs confirmation on the list screen')} palette={buttonPalette} />
    </View>
    {status ? <Text accessibilityRole="status" accessibilityLiveRegion="polite" style={styles.status}>{status}</Text> : null}
  </View>;
}

const styles = StyleSheet.create({
  group: { gap: spacing.sm },
  row: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', gap: spacing.sm },
  status: { color: palette.textMuted, fontSize: 12 },
});
