import React from 'react';
import { Image, View } from 'react-native';
import { SvgUri } from 'react-native-svg';

export function ProviderLogo({ source, style, label = '' }) {
  if (!source) return null;
  // RN Image handles raster artwork; native SVG needs its own renderer, as on web.
  return /\.svg(?:[?#]|$)/i.test(source)
    ? <View style={style} accessible={Boolean(label)} accessibilityLabel={label || undefined}>
      <SvgUri uri={source} width="100%" height="100%" />
    </View>
    : <Image source={{ uri: source }} resizeMode="contain" style={style}
      accessible={Boolean(label)} accessibilityLabel={label || undefined} />;
}
