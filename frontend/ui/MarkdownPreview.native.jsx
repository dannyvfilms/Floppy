import { View } from 'react-native';
import { MarkdownPreview as UniversalMarkdownPreview } from './MarkdownPreview.jsx';

// Native platform entry. The explicit .jsx import avoids resolving back here.
export function MarkdownPreview(props) {
  void View;
  return <UniversalMarkdownPreview {...props} />;
}
