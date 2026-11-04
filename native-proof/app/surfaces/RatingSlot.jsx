import React, { useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { RatingStars } from '../../../frontend/ui/RatingStars';
import { Note } from '../components/Note';
import { palette, ratingPalette, spacing } from '../theme';

export const surface = {
  id: 'RATING',
  status: 'in_progress',
  title: 'Score chip and rating popup',
  where: 'Detail pages, episode rows, music tracks and cards',
  note: 'The score chip and its anchored popup will replace this note. The shared star input already renders here.',
};

export default function RatingSlot() {
  const [score, setScore] = useState(4);
  return <Note surface={surface}>
    <View style={styles.demo}>
      <Text style={styles.label}>Your rating</Text>
      <RatingStars scaleMax={10} value={score} label="Rate"
        renderStar={lit => <Text style={[styles.star, { color: lit ? ratingPalette.lit : ratingPalette.unlit }]}>★</Text>}
        onSelect={setScore} palette={{ ...ratingPalette, focusStyle: {} }} />
      <Text style={styles.value}>{score === null ? 'Not rated' : `${score} / 10`}</Text>
    </View>
  </Note>;
}

const styles = StyleSheet.create({
  demo: { gap: spacing.sm, marginTop: spacing.xs },
  label: { color: palette.textSecondary, fontSize: 12, fontWeight: '600' },
  star: { fontSize: 18 },
  value: { color: palette.textMuted, fontSize: 12 },
});
