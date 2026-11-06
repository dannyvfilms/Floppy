import React from 'react';
// Native presentation marker for the architecture contract; the shared
// component below owns layout, so no wrapper View is rendered here.
import { View } from 'react-native';
import { ArtworkImage as SharedArtworkImage } from './ArtworkImage.jsx';

export function ArtworkImage(props) {
  return <SharedArtworkImage {...props} />;
}
