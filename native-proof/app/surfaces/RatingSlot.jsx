import React, { useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { RatingChip } from '../../../frontend/ui/RatingChip';
import { RatingStarIcon } from '../../../frontend/ui/RatingStarIcon.native';
import { palette, ratingPalette, spacing } from '../theme';

export const surface = {
  id: 'RATING',
  status: 'in_progress',
  title: 'Score chip and rating popup',
  where: 'Detail pages, episode rows, music tracks and cards',
  note: 'The shared RatingChip and RatingStars render the detail pill, the carousel card, the compact track row, rated and unrated selection, toggle-to-clear, both viewer scales and the read-only public derived score. The read-only state wraps the shared chip because RatingChip has no readOnly prop. The compact layout is only a proof row here: the actual music-track and comic-issue rows live in native-proof/app/components/MusicParts.jsx and native-proof/app/surfaces/DetailChildrenSlot.jsx, outside this surface, so those consumers still need a compact placement. The season episode card title rating and provider score chips remain legacy on the web.',
};

const labels = {
  yourScore: 'Your score',
  derivedRating: 'Derived rating',
  editRating: 'Edit rating',
  addRating: 'Add rating',
  rate: 'Rate',
  derived: 'Derived',
  yourRating: 'Your rating',
  close: 'Close',
  prompt: 'Rate this show',
};

const derived = { score: '7.6', coverage: '5/8 episodes', label: 'Season 1', title: 'Derived from rated episodes.' };

function scoreText(value, scaleMax) {
  if (value === null || value === undefined) return null;
  return scaleMax === 5 ? `${value}/5` : String(value);
}

function cardScoreText(value, scaleMax) {
  if (value === null || value === undefined) return null;
  return scaleMax === 5 ? `${value}/5` : `${value}.0`;
}

function EditableRating({ layout = 'pill', initial = null, scaleMax = 10, derivedRating = null }) {
  const [value, setValue] = useState(initial);
  const [open, setOpen] = useState(false);
  return <RatingChip
    value={value}
    scaleMax={scaleMax}
    displayValue={scoreText(value, scaleMax)}
    cardDisplayValue={cardScoreText(value, scaleMax)}
    derived={derivedRating}
    layout={layout}
    labels={labels}
    renderStar={RatingStarIcon}
    onSelect={setValue}
    palette={ratingPalette}
    open={open}
    onOpenChange={setOpen} />;
}

function ReadOnlyDerived({ derivedRating }) {
  const label = `${labels.derivedRating}: ${derivedRating.score}, ${derivedRating.coverage}`;
  return <View accessible accessibilityRole="text" accessibilityLabel={label}
    pointerEvents="none" style={styles.readOnly}>
    <View accessible={false} accessibilityElementsHidden importantForAccessibility="no-hide-descendants">
      <RatingChip value={null} scaleMax={10} derived={derivedRating}
        layout="pill" labels={labels} renderStar={RatingStarIcon} palette={ratingPalette} />
    </View>
  </View>;
}

function Sample({ caption, children }) {
  return <View style={styles.sample}>
    <Text style={styles.caption}>{caption}</Text>
    {children}
  </View>;
}

export default function RatingSlot() {
  return <View style={styles.group}>
    <Sample caption="Detail · pill · rated">
      <EditableRating initial={8} derivedRating={derived} />
    </Sample>
    <Sample caption="Carousel · card · 5-point scale">
      <EditableRating layout="card" scaleMax={5} />
    </Sample>
    <Sample caption="Track row · compact · rated">
      <View style={styles.row}>
        <EditableRating layout="compact" initial={6} />
        <Text numberOfLines={1} style={styles.rowTitle}>Halcyon Relay — Main Theme</Text>
      </View>
    </Sample>
    <Sample caption="Public view · derived · read-only">
      <ReadOnlyDerived derivedRating={derived} />
    </Sample>
  </View>;
}

const styles = StyleSheet.create({
  group: { gap: spacing.md, marginTop: spacing.xs },
  sample: { gap: spacing.xs },
  caption: { color: palette.textMuted, fontSize: 12 },
  row: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm },
  rowTitle: { flexShrink: 1, color: palette.textSecondary, fontSize: 13 },
  readOnly: { alignSelf: 'flex-start' },
});
