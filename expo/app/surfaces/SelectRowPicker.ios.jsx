import React from 'react';
import { Host, HStack, Image, Menu, Picker, Text } from '@expo/ui/swift-ui';
import { buttonStyle, font, foregroundStyle, pickerStyle, tag } from '@expo/ui/swift-ui/modifiers';

// The iOS select for grouped rows (Calendar Links, Add Copy): a system Menu so the closed row can say "Upcoming" while the Liquid Glass menu
// lists the full names with the current one checked. A Picker alone can only show
// the selected item's own label.
export function renderSelectRowPicker({ label = 'Calendar Type', value, options, onChange, palette }) {
  const selected = options.find(option => option.value === value);
  const shown = selected?.displayLabel ?? (selected?.value ? selected.label : 'Select');
  return <Host matchContents>
    <Menu modifiers={[buttonStyle('plain')]}
      label={<HStack spacing={6}>
        <Text modifiers={[font({ size: 17 }), foregroundStyle(palette.textSecondary)]}>{shown}</Text>
        <Image systemName="chevron.up.chevron.down" size={13} color={palette.textSecondary} />
      </HStack>}>
      <Picker label={label} selection={value} onSelectionChange={onChange}
        modifiers={[pickerStyle('inline')]}>
        {options.map(option => <Text key={option.value} modifiers={[tag(option.value)]}>{option.label}</Text>)}
      </Picker>
    </Menu>
  </Host>;
}
