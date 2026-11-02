import React from 'react';
import { Pressable, Text, View } from 'react-native';
import { Chip } from '../settings/Chip';

/** Shared presentation; the surface adapter owns URLs, forms and navigation. */
export function AlphabetBar({ options, label, palette, onNavigate }) {
  return <View accessibilityRole="navigation" accessibilityLabel={label} style={{ height: '100%', minHeight: 0 }}>
    {options.map(option => <Pressable key={option.value} role="link" href={option.href}
      dataSet={{ alphabetInitial: option.value }}
      aria-current={option.selected ? 'true' : undefined} accessibilityLabel={option.accessibilityLabel}
      onPress={event => onNavigate(event, option)}
      style={({ focused, hovered }) => [{ flex: 1, minHeight: 0, alignItems: 'center', justifyContent: 'center' },
        palette.interactiveStyle, focused && palette.focusStyle, hovered && { backgroundColor: palette.badgeHover }]}>
      <Text numberOfLines={1} style={{ color: option.selected ? palette.selectedText : palette.mutedText,
        fontFamily: palette.fontFamily, fontSize: option.caption ? palette.captionSize : palette.letterSize,
        lineHeight: palette.letterSize, fontWeight: option.selected ? '600' : '400', textAlign: 'center' }}>{option.label}</Text>
    </Pressable>)}
  </View>;
}

export function AlphabetEmpty({ title, clearLabel, option, palette, onNavigate }) {
  return <View style={{ alignItems: 'center', gap: 16, padding: 48 }}>
    <Text role="heading" aria-level={3} style={{ color: palette.badgeText, fontFamily: palette.fontFamily, fontSize: 20, lineHeight: 24, fontWeight: '600' }}>{title}</Text>
    <Chip label={clearLabel} href={option.href} palette={palette} onPress={event => onNavigate(event, option)} />
  </View>;
}

