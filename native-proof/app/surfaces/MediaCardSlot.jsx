import React, { useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { Badge } from '../../../frontend/ui/Badge';
import { ProgressChanger } from '../../../frontend/ui/ProgressChanger';
import { Note } from '../components/Note';
import { badgePalette, palette, progressPalette, spacing } from '../theme';

export const surface = {
  id: 'MEDIA-CARD',
  title: 'Media card',
  where: 'Home rails, Discover, Library, Search and List results',
  status: 'in_progress',
  note: 'The card artwork, title, status chip, rating and actions will replace this note. The shared badge and quick progress controls already render where the card will put them.',
};

export default function MediaCardSlot() {
  const [progress, setProgress] = useState(3);
  const [busy, setBusy] = useState(null);
  function adjust(operation) {
    setBusy(operation);
    setProgress(value => Math.max(0, Math.min(10, value + (operation === 'increase' ? 1 : -1))));
    setTimeout(() => setBusy(null), 500);
  }
  return <Note surface={surface}>
    <View style={styles.cardPreview}>
      <View style={styles.artwork}><Text style={styles.artworkText}>Artwork</Text></View>
      <View style={styles.cardBody}>
        <Text style={styles.cardTitle}>A finished card will show the title here</Text>
        <View style={styles.badgeRow}><Badge label="In progress" size="sm" tone="indigo" palette={badgePalette} /></View>
        <ProgressChanger value={String(progress)} max="10" unit="Episodes" showMax
          canDecrease={progress > 0} canIncrease={progress < 10} busyOperation={busy}
          decreaseLabel="Decrease progress" increaseLabel="Increase progress" onAdjust={adjust}
          palette={progressPalette} />
      </View>
    </View>
  </Note>;
}

const styles = StyleSheet.create({
  cardPreview: { flexDirection: 'row', gap: spacing.md, alignItems: 'flex-start', marginTop: spacing.xs },
  artwork: { width: 72, aspectRatio: 2 / 3, borderRadius: 6, backgroundColor: palette.background, alignItems: 'center', justifyContent: 'center' },
  artworkText: { color: palette.textMuted, fontSize: 10 },
  cardBody: { flex: 1, minWidth: 0, gap: spacing.sm },
  cardTitle: { color: palette.textSecondary, fontSize: 13, lineHeight: 18 },
  badgeRow: { alignSelf: 'flex-start' },
});
