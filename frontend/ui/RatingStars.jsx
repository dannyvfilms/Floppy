import React, { useState } from 'react';
import { Pressable, Text, View } from 'react-native';

/**
 * Shared star row for every rating popup. Presentation and hover/selection only:
 * the surface adapter owns the write, the CSRF token and any popup state.
 * Selecting the current value again clears it (`onSelect(null)`).
 */
export function RatingStars({ scaleMax, value, label, renderStar, onSelect, palette }) {
  const [hover, setHover] = useState(null);
  const shown = hover ?? value;
  return <View role="group" accessibilityLabel={label}
    style={{ flexDirection: 'row', justifyContent: 'space-between', marginBottom: 4 }}
    onPointerLeave={() => setHover(null)}>
    {Array.from({ length: scaleMax }, (_, index) => {
      const star = index + 1;
      const lit = shown !== null && shown !== undefined && star <= shown;
      return <Pressable key={star} role="button" accessibilityLabel={`${label} ${star}/${scaleMax}`}
        aria-pressed={value === star}
        onPress={() => onSelect(value === star ? null : star)}
        onHoverIn={() => setHover(star)}
        style={({ focused }) => [{ alignItems: 'center', cursor: 'pointer' },
          focused && palette.focusStyle]}>
        <View style={{ color: lit ? palette.lit : palette.unlit }}>{renderStar(lit)}</View>
        <Text style={{ fontSize: 12, marginTop: 4, color: palette.muted }}>{star}</Text>
      </Pressable>;
    })}
  </View>;
}
