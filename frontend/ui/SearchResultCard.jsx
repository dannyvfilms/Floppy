import React from 'react';
import { View } from 'react-native';
import { MediaCard } from './MediaCard';

// Native keeps the shared card's own frame; the browser wrapper adds the
// release card's extra layout element (see SearchResultCard.web.jsx).
export function SearchResultCard({ model, width, labels, palette, actions,
  onAction, onRate, renderRating, renderActionIcon }) {
  return <View><MediaCard
    model={model}
    width={width}
    labels={labels}
    palette={palette}
    actions={actions}
    onAction={onAction}
    onRate={onRate}
    renderRating={renderRating}
    renderActionIcon={renderActionIcon}
  /></View>;
}
