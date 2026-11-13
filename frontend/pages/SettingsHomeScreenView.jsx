import React from 'react';
import { View } from 'react-native';
import { HomeScreenEditor } from '../settings/HomeScreenEditor';
import { SettingsPage } from './SettingsView';

export const settingsHomeCopy = {
  title: 'Home Screen',
  copy: 'These groups are the rows on the home screen. Use the arrows to reorder, click to edit.',
};

// Home rows, filters, status, sort and display options. Section order and copy
// live here; the adapter owns sections, list choices and persistence intent.
export function SettingsHomeView({
  dragIcon,
  sections = [],
  initialSections,
  listChoices = [],
  mediaTypeChipStyles = [],
  showMediaTypeHeaders = false,
  mediaTypeChipsEnabled = false,
  mediaTypeChipStyle,
  segmentedAppearance = false,
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
      mediaTypeChipsEnabled={mediaTypeChipsEnabled} mediaTypeChipStyle={mediaTypeChipStyle} segmentedAppearance={segmentedAppearance} dragIcon={dragIcon}
      onChange={onChange} onSave={onSave} validate={validate} labels={heading ? { ...labels, copy: '' } : labels}
      palette={palette} buttonPalette={buttonPalette} disabled={disabled} />
    </>}
  </SettingsPage></View>;
}
