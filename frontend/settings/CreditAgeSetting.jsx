import React from 'react';
import { View } from 'react-native';
import { SelectField } from '../ui/SelectField';

const DEFAULT_LABELS = {
  label: 'Age at event',
  show: 'Show',
  hide: 'Hide',
};

/** A focused shared control for age labels on person-credit cards. */
export function CreditAgeSetting({
  enabled = true,
  labels,
  palette,
  disabled = false,
  onChange,
  id = 'person-credit-age',
}) {
  const copy = { ...DEFAULT_LABELS, ...(labels || {}) };
  return <View>
    <SelectField
      id={id}
      label={copy.label}
      options={[
        { value: 'show', label: copy.show },
        { value: 'hide', label: copy.hide },
      ]}
      value={enabled ? 'show' : 'hide'}
      disabled={disabled}
      palette={palette}
      onChange={event => onChange?.(event.target.value === 'show')}
    />
  </View>;
}
