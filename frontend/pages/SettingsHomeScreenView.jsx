import React from 'react';
import { View } from 'react-native';
import { HomeScreenEditor } from '../settings/HomeScreenEditor';
import { SettingsPage } from './SettingsView';

export const settingsHomeCopy = {
  title: 'Home Screen',
  copy: 'These groups are the rows on the home screen. Drag to reorder and click to edit.',
};

// Home rows, filters, status, sort and display options. Section order and copy
// live here; the adapter owns sections, list choices and persistence intent.
export function SettingsHomeView({
  sections = [],
  initialSections,
  listChoices = [],
  mediaTypeChipStyles = [],
  showMediaTypeHeaders = false,
  mediaTypeChipsEnabled = false,
  mediaTypeChipStyle,
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
  const copy = { ...settingsHomeCopy, ...(labels || {}) };
  return <View><SettingsPage title={copy.title} copy={copy.copy} palette={palette} heading={heading}>
    {content || <>
    <HomeScreenEditor sections={sections} initialSections={initialSections}
      listChoices={listChoices} mediaTypeChipStyles={mediaTypeChipStyles}
      showMediaTypeHeaders={showMediaTypeHeaders}
      mediaTypeChipsEnabled={mediaTypeChipsEnabled} mediaTypeChipStyle={mediaTypeChipStyle}
      onChange={onChange} onSave={onSave} validate={validate} labels={labels}
      palette={palette} buttonPalette={buttonPalette} disabled={disabled} />
    </>}
  </SettingsPage></View>;
}
