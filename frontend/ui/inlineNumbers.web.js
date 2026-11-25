import { useWindowDimensions } from 'react-native';

// Desktop web (the app shell's 1024 px breakpoint and up) types numbers into inputs, like the old score field.
// Mobile web keeps the pills and wheels the phone layout uses.
const DESKTOP_MIN_WIDTH = 1024;

export function useInlineNumbers() {
  const { width } = useWindowDimensions();
  return width >= DESKTOP_MIN_WIDTH;
}
