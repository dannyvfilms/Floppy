import React, { useEffect, useRef, useState } from 'react';
import { AccessibilityInfo, Animated, Easing } from 'react-native';

// Decorative: the caller owns any status announcement and supplies a theme color.
export function Spinner({ size = 16, color = '#6366f1' }) {
  const rotation = useRef(new Animated.Value(0)).current;
  const [reducedMotion, setReducedMotion] = useState(false);
  useEffect(() => {
    let active = true;
    AccessibilityInfo.isReduceMotionEnabled().then(value => { if (active) setReducedMotion(value); });
    const subscription = AccessibilityInfo.addEventListener('reduceMotionChanged', setReducedMotion);
    return () => { active = false; subscription.remove(); };
  }, []);
  useEffect(() => {
    rotation.setValue(0);
    const animation = Animated.loop(Animated.timing(rotation, { toValue: 1, duration: reducedMotion ? 3000 : 1000, easing: Easing.linear, useNativeDriver: true, isInteraction: false }));
    animation.start();
    return () => animation.stop();
  }, [rotation, reducedMotion]);
  return <Animated.View aria-hidden={true} accessible={false} accessibilityElementsHidden importantForAccessibility="no-hide-descendants"
    style={{ width: size, height: size, flexShrink: 0, borderRadius: size / 2, borderBottomWidth: size <= 12 ? 1 : 2,
      borderBottomColor: color, transform: [{ rotate: rotation.interpolate({ inputRange: [0, 1], outputRange: ['0deg', '360deg'] }) }] }} />;
}
