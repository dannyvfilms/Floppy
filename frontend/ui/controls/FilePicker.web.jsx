import React from 'react';

const defaultPalette = {
  background: '#3f3f46',
  text: '#fafafa',
  border: '#52525b',
  radius: 8,
};

/** Browser slot. Keeps a real hidden file input so form submission, browser
 * selection and file-change tests keep working; the wrapping label supplies the
 * visible button and its accessible name.
 */
export function FilePicker({
  label,
  onChange,
  accept,
  multiple = false,
  disabled = false,
  palette = {},
  name,
  id,
  testID,
  required = false,
}) {
  const colors = { ...defaultPalette, ...palette };
  const themed = Object.keys(palette).length > 0;
  return <label
    className="ui-button ui-file-picker"
    aria-disabled={disabled || undefined}
    data-testid={testID}
    style={themed ? {
      backgroundColor: colors.background,
      color: colors.text,
      borderColor: colors.border,
      borderRadius: colors.radius ?? 8,
      opacity: disabled ? 0.5 : 1,
    } : undefined}>
    <input
      id={id}
      name={name}
      className="ui-sr-only"
      type="file"
      accept={accept}
      multiple={multiple}
      disabled={disabled}
      required={required}
      aria-label={label}
      onChange={event => onChange?.(event)}
    />
    <span>{label}</span>
  </label>;
}
