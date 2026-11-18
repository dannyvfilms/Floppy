import React from 'react';
import { Image } from 'react-native';

export function ProviderLogo({ source, style, label = '' }) {
  return source ? <Image source={{ uri: source }} resizeMode="contain" style={style}
    accessible={Boolean(label)} accessibilityLabel={label || undefined} /> : null;
}
