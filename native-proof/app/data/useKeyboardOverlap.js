import { useEffect, useState } from 'react';
import { Keyboard } from 'react-native';

// How far the keyboard covers the bottom of the window, for the Search suggestion window.
export function useKeyboardOverlap() {
  const [height, setHeight] = useState(0);
  useEffect(() => {
    // The keyboard may already be up when the field mounts, so read it as well as listen.
    const current = Keyboard.metrics?.();
    if (current?.height) setHeight(current.height);
    const shown = Keyboard.addListener('keyboardDidShow', event => setHeight(event.endCoordinates?.height || 0));
    const hidden = Keyboard.addListener('keyboardDidHide', () => setHeight(0));
    return () => { shown.remove(); hidden.remove(); };
  }, []);
  return height;
}
