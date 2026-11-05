import React, { useState } from 'react';
import { StyleSheet, View } from 'react-native';
import { RatingChip } from '../../../frontend/ui/RatingChip';
import { RatingStarIcon } from '../../../frontend/ui/RatingStarIcon.native';
import { ratingPalette, spacing } from '../theme';

export const surface = {
  id: 'RATING',
  status: 'in_progress',
  title: 'Score chip and rating popup',
  where: 'Detail pages, episode rows, music tracks and cards',
  note: 'The detail personal score chip, the episode/music/comic pill chips, music track and comic issue row chips and their popup use the shared RatingChip and RatingStars. The native shell places the detail pill; the compact row layout compiles but is not placed on a native row, and the season episode card title rating and provider score chips remain legacy.',
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

export default function RatingSlot() {
  const [score, setScore] = useState(8);
  const [open, setOpen] = useState(false);
  return <View style={styles.row}>
    <RatingChip
      value={score}
      scaleMax={10}
      displayValue={score === null ? null : String(score)}
      cardDisplayValue={score === null ? null : `${score}.0`}
      derived={derived}
      layout="pill"
      labels={labels}
      renderStar={RatingStarIcon}
      onSelect={setScore}
      palette={ratingPalette}
      open={open}
      onOpenChange={setOpen} />
  </View>;
}

const styles = StyleSheet.create({
  row: { marginTop: spacing.xs },
});
