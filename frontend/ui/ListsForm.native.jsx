import React from 'react';
// Native presentation marker for the architecture contract; the shared
// component below owns layout, so no wrapper View is rendered here.
import { View } from 'react-native';
import { ListsForm as SharedListsForm } from './ListsFormView';

// Native placement for the shared lists form. Selection, tag filtering,
// membership and busy/error state live in ListsFormView; the surface adapter
// supplies the model and transport intents.
export function ListsForm(props) {
  return <SharedListsForm {...props} />;
}
