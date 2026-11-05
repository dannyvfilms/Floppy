import React from 'react';
import { View } from 'react-native';
import { ArtworkImage as SharedArtworkImage } from './ArtworkImage.jsx';

export function ArtworkImage(props) {
  return <View><SharedArtworkImage {...props} /></View>;
}
