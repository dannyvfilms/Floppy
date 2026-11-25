import React from 'react';
import { View } from 'react-native';
import { CollectionGroup, CollectionRow } from './CollectionCopies';
import { actionIcons } from './actionIcons';
import { formatScore, groupByTier, isFilled } from './ratingScaleModel';

const DEFAULT_LABELS = { overall: 'Overall', manual: 'Manual', calculated: 'Calculated', notRated: 'Not rated', weight: 'Weight' };

/**
 * The media details sidebar's view of a custom-scale rating: the overall score, then each criterion's value in
 * the same grouped rows as the Collection card. A manual score shows beside the calculated one it replaced.
 * `rating` is `{ criteria, values, computed, manual, overall }` from the server or the native API.
 */
export function RatingBreakdown({ rating, palette, variant = 'native', labels: supplied }) {
  if (!rating) return null;
  const labels = { ...DEFAULT_LABELS, ...supplied };
  const tiers = groupByTier(rating.criteria).filter(tier => tier.items.length);
  const overall = isFilled(rating.overall) ? formatScore(rating.overall) : labels.notRated;
  return <View style={{ gap: 16 }}>
    <CollectionGroup palette={palette} variant={variant}>
      <CollectionRow key="overall" icon={actionIcons.star} label={labels.overall} palette={palette}
        value={rating.manual ? `${overall} (${labels.manual.toLowerCase()})` : overall} />
      {rating.manual && isFilled(rating.computed)
        ? <CollectionRow key="calc" label={labels.calculated} palette={palette} value={formatScore(rating.computed)} /> : null}
    </CollectionGroup>
    {tiers.map(tier => <CollectionGroup key={tier.weight} palette={palette} variant={variant}
      title={tiers.length > 1 ? `${labels.weight} ${tier.weight}` : undefined}>
      {tier.items.map(criterion => <CollectionRow key={criterion.id} label={criterion.name} palette={palette}
        value={isFilled(rating.values?.[criterion.id]) ? formatScore(rating.values[criterion.id]) : '-'} />)}
    </CollectionGroup>)}
  </View>;
}
