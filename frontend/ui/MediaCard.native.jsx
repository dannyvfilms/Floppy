import { View } from 'react-native';
import { MediaCard as UniversalMediaCard } from './MediaCard.jsx';

// Native implementation of the shared card. The explicit .jsx import avoids
// Metro resolving `./MediaCard` back to this platform adapter.
export function MediaCard(props) {
  void View;
  return <UniversalMediaCard {...props} />;
}
