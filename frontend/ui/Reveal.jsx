import React, { useEffect, useRef, useState } from 'react';
import { Animated, Easing, View } from 'react-native';

// Keep the children mounted while collapsing so native matches the web reveal.
export function Reveal({ open, children, duration = 200 }) {
  const [height, setHeight] = useState(0);
  const progress = useRef(new Animated.Value(open ? 1 : 0)).current;
  useEffect(() => {
    const animation = Animated.timing(progress, { toValue: open ? 1 : 0,
      duration, easing: Easing.out(Easing.cubic), useNativeDriver: false });
    animation.start();
    return () => animation.stop();
  }, [open, duration, progress]);
  return <Animated.View pointerEvents={open ? 'auto' : 'none'}
    accessibilityElementsHidden={!open} importantForAccessibility={open ? 'auto' : 'no-hide-descendants'}
    style={{ height: Animated.multiply(progress, height), overflow: 'hidden' }}>
    <View onLayout={event => setHeight(event.nativeEvent.layout.height)}
      style={{ position: 'absolute', left: 0, right: 0, top: 0 }}>{children}</View>
  </Animated.View>;
}
