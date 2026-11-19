import React from 'react';
import { View } from 'react-native';
import { MediaCard } from './MediaCard';
import { listCardModel } from './cardModels';

// Maps a list hub record onto the shared media-card model. The card keeps the
// shared artwork, badge and action behaviour; the list-specific metadata arrives
// as corner chips and a metadata line so the presentation stays in one place.
export function ListCard({ list, palette, width = 240, onOpen, onAction, hideMetadata = false }) {
  const model = listCardModel(list, { hideMetadata });
  return (
    <View>
      <MediaCard
        model={model}
        palette={palette}
        width={width}
        onOpen={onOpen}
        onAction={onAction}
      />
    </View>
  );
}
