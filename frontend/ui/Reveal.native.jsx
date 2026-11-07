import { View } from 'react-native';
import { Reveal as UniversalReveal } from './Reveal.jsx';

// Native platform entry. The explicit .jsx import avoids resolving back here.
export function Reveal(props) {
  void View;
  return <UniversalReveal {...props} />;
}
