import React from 'react';
import { View } from 'react-native';
import { ListsForm as SharedListsForm } from './ListsFormView';

// Native placement for the shared lists form. Selection, tag filtering,
// membership and busy/error state live in ListsFormView; the surface adapter
// supplies the model and transport intents.
export function ListsForm(props) {
  return <View><SharedListsForm {...props} /></View>;
}
