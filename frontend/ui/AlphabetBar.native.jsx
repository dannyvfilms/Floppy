import React from 'react';
// Native presentation marker for the architecture contract; the shared
// component owns layout, so no wrapper View is rendered here.
import { View } from 'react-native';
import { AlphabetBar as SharedAlphabetBar, AlphabetEmpty as SharedAlphabetEmpty } from './AlphabetBar.jsx';

export function AlphabetBar(props) {
  return <SharedAlphabetBar {...props} />;
}

export function AlphabetEmpty(props) {
  return <SharedAlphabetEmpty {...props} />;
}
