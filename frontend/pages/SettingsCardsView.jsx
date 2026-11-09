import React from 'react';
import { View } from 'react-native';
import { CardsEditor } from '../settings/CardsEditor';
import { SettingsPage } from './SettingsView';

export const settingsCardsCopy = {
  title: 'Media Cards',
  copy: 'Choose how cards look for each media type. Add properties below; up to three can share a line.',
};

// Card configuration and live preview for every media type. The adapter owns
// the editor catalog, saved profiles and persistence intent.
export function SettingsCardsView({
  catalog = [],
  saved = {},
  initialSaved,
  initialTouchActions = false,
  active,
  touchActions = false,
  onChange,
  onSave,
  validate,
  labels = {},
  content = null,
  heading = true,
  palette = {},
  buttonPalette = {},
  disabled = false,
}) {
  const copy = { ...settingsCardsCopy, ...(labels || {}) };
  return <View><SettingsPage title={copy.title} copy={copy.copy} palette={palette} heading={heading}>
    {content || <>
    <CardsEditor catalog={catalog} saved={saved} initialSaved={initialSaved}
      initialTouchActions={initialTouchActions} active={active}
      touchActions={touchActions} onChange={onChange} onSave={onSave} validate={validate}
      labels={labels} palette={palette} buttonPalette={buttonPalette} disabled={disabled} />
    </>}
  </SettingsPage></View>;
}
