import React from 'react';
import { Image, StyleSheet, Text, View } from 'react-native';

// Deliberately read-only: this is a contract experiment, not the web MediaCard.
export function NativeProofLabel({ text, color }) {
  return <Text style={[styles.label, { color }]}>{text}</Text>;
}

export function NativeProofCard({ title, image, palette }) {
  return <View style={[styles.card, { backgroundColor: palette.background, borderColor: palette.border }]}>
    {image ? <Image accessibilityLabel={title} source={{ uri: image }} style={styles.image} /> :
      <View style={[styles.image, { backgroundColor: palette.placeholder }]} />}
    <View style={styles.body}><NativeProofLabel text={title} color={palette.text} /></View>
  </View>;
}

const styles = StyleSheet.create({
  card: { width: 160, borderWidth: 1, borderRadius: 8, overflow: 'hidden' },
  image: { width: '100%', aspectRatio: 2 / 3 },
  body: { padding: 12 },
  label: { fontSize: 14, fontWeight: '600' },
});
