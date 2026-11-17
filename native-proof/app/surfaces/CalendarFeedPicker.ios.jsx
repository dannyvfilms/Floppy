import React from 'react';
import { Host, HStack, Image, Menu, Picker, Text } from '@expo/ui/swift-ui';
import { buttonStyle, font, foregroundStyle, pickerStyle, tag } from '@expo/ui/swift-ui/modifiers';

// A system Menu so the closed row can say "Upcoming" while the Liquid Glass menu
// lists the full names with the current one checked. A Picker alone can only show
// the selected item's own label.
export function renderCalendarFeedPicker({ value, options, onChange, palette }) {
  const selected = options.find(option => option.value === value);
  return <Host matchContents>
    <Menu modifiers={[buttonStyle('plain')]}
      label={<HStack spacing={6}>
        <Text modifiers={[font({ size: 17 }), foregroundStyle(palette.textSecondary)]}>{selected?.displayLabel}</Text>
        <Image systemName="chevron.up.chevron.down" size={13} color={palette.textSecondary} />
      </HStack>}>
      <Picker label="Calendar Type" selection={value} onSelectionChange={onChange}
        modifiers={[pickerStyle('inline')]}>
        {options.map(option => <Text key={option.value} modifiers={[tag(option.value)]}>{option.label}</Text>)}
      </Picker>
    </Menu>
  </Host>;
}
