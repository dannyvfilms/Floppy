import React from 'react';
import { Text } from 'react-native';
import { SelectField } from '../../../frontend/ui/SelectField';

// Android uses the shared accessible dropdown (iOS supplies a system menu in
// SelectRowPicker.ios.jsx). This file keeps the .jsx extension so Metro does
// not resolve it ahead of the .ios.jsx variant.
export function renderSelectRowPicker({ label = 'Calendar Type', value, options, onChange, palette }) {
  const selected = options.find(option => option.value === value);
  return <SelectField label={label} labelHidden value={value} options={options}
    displayValue={selected?.displayLabel} palette={palette} popover
    accessibilityLabel={`${label}: ${selected?.label ?? ''}`}
    onChange={event => onChange(event.target.value)}
    triggerStyle={{ borderWidth: 0, backgroundColor: 'transparent', paddingHorizontal: 0, paddingVertical: 0 }}
    triggerTextStyle={{ color: palette.textSecondary, fontSize: 16 }}
    indicator={<Text style={{ color: palette.textMuted, fontSize: 13, lineHeight: 8, textAlign: 'center' }}>{'⌃\n⌄'}</Text>} />;
}
