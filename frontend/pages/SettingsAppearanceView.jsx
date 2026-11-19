import React from 'react';
import { View } from 'react-native';
import { AppearanceEditor } from '../settings/AppearanceEditor';
import { SettingsPage } from './SettingsView';

export const settingsAppearanceCopy = {
  title: 'Appearance',
  copy: '',
};

// Theme presets, custom palette and detail-page ordering stay in one shared
// editor; the adapter owns current values and the save transport.
export function SettingsAppearanceView({
  swatches,
  themeIcon,
  SaveBar,
  presets = {},
  colors = {},
  effects = {},
  families = {},
  values = { theme: 'system', palette: {}, layouts: {} },
  initialValues,
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
  const copy = { ...settingsAppearanceCopy, ...(labels || {}) };
  return <View><SettingsPage title={copy.title} copy={copy.copy} palette={palette} heading={heading}>
    {content || <>
    <AppearanceEditor SaveBar={SaveBar} swatches={swatches} themeIcon={themeIcon} presets={presets} colors={colors} effects={effects} families={families}
      values={values} initialValues={initialValues} onChange={onChange} onSave={onSave}
      validate={validate} labels={labels} palette={palette} buttonPalette={buttonPalette}
      disabled={disabled} />
    </>}
  </SettingsPage></View>;
}
