import React from 'react';
import { View } from 'react-native';
import { PreferencesForm } from '../ui/PreferencesForm';
import { SettingsPage } from './SettingsView';

export const settingsPreferencesCopy = {
  title: 'Preferences',
  copy: '',
};

// The preference fields, groups and save state are shared; the server/native
// adapter supplies the option catalog, current values and persistence intent.
export function SettingsPreferencesView({
  SaveBar,
  sections = [],
  values = {},
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
  csrf,
  fieldErrors = {},
  formError,
  onSectionLink,
}) {
  const copy = { ...settingsPreferencesCopy, ...(labels || {}) };
  return <View><SettingsPage title={copy.title} copy={copy.copy} palette={palette} heading={heading}>
    {content || <>
    <PreferencesForm SaveBar={SaveBar} sections={sections} values={values} initialValues={initialValues}
      onChange={onChange} onSave={onSave} validate={validate} labels={labels}
      palette={palette} buttonPalette={buttonPalette} disabled={disabled}
      csrf={csrf} fieldErrors={fieldErrors} formError={formError} onSectionLink={onSectionLink} />
    </>}
  </SettingsPage></View>;
}
