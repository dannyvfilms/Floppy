import { View } from 'react-native';
import { MediaCard as UniversalMediaCard } from './MediaCard';

// Native implementation of the shared card. The universal MediaCard already
// owns the React Native shell; this platform entry keeps every surface on the
// same `MediaCard` import while the browser resolves MediaCard.web.jsx instead.
export function MediaCard(props) {
  void View;
  return <UniversalMediaCard {...props} />;
}
