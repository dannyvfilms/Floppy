import React, { useEffect, useRef, useState } from 'react';
import { AccessibilityInfo, Animated, Easing, StyleSheet, View } from 'react-native';

export const progressFallbackPalette = {
  text: '#fafafa',
  textSecondary: '#d4d4d8',
  textMuted: '#a1a1aa',
  surface: '#27272a',
  surfaceStrong: '#3f3f46',
  surfaceBorder: '#3f3f46',
  surfaceMuted: '#52525b',
  surfaceHover: '#3f3f46',
  fill: '#10b981',
  glow: '#a7f3d0',
  glowShadow: '#6ee7b7',
  watchedBorder: 'rgba(16, 185, 129, 0.4)',
  watchedBg: 'rgba(16, 185, 129, 0.1)',
  watchedText: '#10b981',
  upcomingBorder: '#3f3f46',
  droppedBackground: '#52525b',
  droppedText: '#a1a1aa',
  focusStyle: {},
};

function clamp(percent) {
  return Math.max(0, Math.min(100, Number(percent) || 0));
}

function ProgressGlow({ offset, width, palette }) {
  const opacity = useRef(new Animated.Value(1)).current;
  const [reducedMotion, setReducedMotion] = useState(false);
  useEffect(() => {
    let active = true;
    AccessibilityInfo.isReduceMotionEnabled().then(value => { if (active) setReducedMotion(value); });
    const subscription = AccessibilityInfo.addEventListener('reduceMotionChanged', setReducedMotion);
    return () => {
      active = false;
      subscription.remove();
    };
  }, []);
  useEffect(() => {
    if (reducedMotion) {
      opacity.setValue(1);
      return undefined;
    }
    const animation = Animated.loop(Animated.sequence([
      Animated.timing(opacity, { toValue: 0.65, duration: 1200, easing: Easing.inOut(Easing.ease), useNativeDriver: true, isInteraction: false }),
      Animated.timing(opacity, { toValue: 1, duration: 1200, easing: Easing.inOut(Easing.ease), useNativeDriver: true, isInteraction: false }),
    ]));
    animation.start();
    return () => animation.stop();
  }, [opacity, reducedMotion]);
  return <Animated.View pointerEvents="none" style={[styles.glow, {
    left: `${clamp(offset)}%`,
    width: `${clamp(width)}%`,
    backgroundColor: palette.glow,
    shadowColor: palette.glowShadow,
    opacity,
  }]} />;
}

/**
 * A watched-once bar with an optional current-pass glow.
 *
 * Presentation only: the caller supplies the percentage, the pass window and
 * semantic theme values.
 */
export function ProgressBar({ percent = 0, rewatch = null, height = 8, palette, label }) {
  const colors = { ...progressFallbackPalette, ...palette };
  const value = clamp(percent);
  const glow = rewatch && clamp(rewatch.width) > 0;
  return <View accessibilityRole="progressbar"
    accessibilityLabel={label}
    accessibilityValue={{ min: 0, max: 100, now: value }}
    style={[styles.track, { height, borderRadius: height / 2, backgroundColor: colors.surfaceMuted }]}>
    <View style={[styles.fill, { width: `${value}%`, borderRadius: height / 2, backgroundColor: colors.fill }]} />
    {glow ? <ProgressGlow offset={rewatch.offset} width={rewatch.width} palette={colors} /> : null}
  </View>;
}

const styles = StyleSheet.create({
  track: { position: 'relative', width: '100%' },
  fill: { height: '100%' },
  glow: {
    position: 'absolute',
    top: 0,
    bottom: 0,
    borderRadius: 9999,
    shadowOpacity: 0.85,
    shadowRadius: 6,
    shadowOffset: { width: 0, height: 0 },
    elevation: 3,
  },
});
