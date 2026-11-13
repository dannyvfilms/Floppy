import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Pressable, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';

const defaultPalette = {
  surface: '#27272a',
  surfaceStrong: '#3f3f46',
  surfaceMuted: '#52525b',
  border: '#52525b',
  text: '#fafafa',
  textSecondary: '#d4d4d8',
  textMuted: '#a1a1aa',
  accent: '#6366f1',
  disabled: '#71717a',
};

const defaultLabels = {
  create: name => `Create "${name}"`,
};

// A press on a suggestion must beat the input blur that precedes it. Closing on
// blur is deferred by this much and cancelled when an option is chosen.
const blurCommitDelay = 140;

/**
 * Free-text field that suggests existing values as you type and offers to create
 * a new one inline. The caller owns the value: `onChange` receives the raw text on
 * every keystroke, `onCommit` receives the settled value when an option is chosen,
 * Enter selects the active suggestion, or the field loses focus.
 */
export function ComboField({
  label,
  id,
  value = '',
  options = [],
  onChange,
  onCommit,
  createLabel,
  disabled = false,
  placeholder,
  maxLength,
  palette = {},
  accessibilityLabel,
  testID,
}) {
  const colors = useMemo(() => ({ ...defaultPalette, ...palette }), [palette]);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const blurTimer = useRef(null);
  const latestValue = useRef(value ?? '');
  const committedValue = useRef(null);
  // The blur commit runs after a delay. Keep the callback current so it
  // cannot replay preferences from before a sibling field changed.
  const onCommitRef = useRef(onCommit);
  onCommitRef.current = onCommit;
  const text = value ?? '';
  latestValue.current = text;

  const typed = text.trim();
  const query = typed.toLocaleLowerCase();
  const items = useMemo(() => {
    const matches = options
      .filter(name => name.toLocaleLowerCase().includes(query))
      .map(name => ({ key: `option:${name}`, name, label: name, create: false }));
    if (typed && !options.some(name => name.toLocaleLowerCase() === query)) {
      const labelForCreate = createLabel || defaultLabels.create;
      matches.push({ key: `create:${typed}`, name: typed, label: labelForCreate(typed), create: true });
    }
    return matches;
  }, [createLabel, options, query, typed]);

  const current = items.length ? Math.min(active, items.length - 1) : -1;
  const optionsId = id ? `${id}-options` : undefined;
  const listOpen = open && !disabled && items.length > 0;

  useEffect(() => () => clearBlurTimer(), []);

  function clearBlurTimer() {
    if (blurTimer.current !== null) {
      clearTimeout(blurTimer.current);
      blurTimer.current = null;
    }
  }

  function choose(item) {
    clearBlurTimer();
    latestValue.current = item.name;
    committedValue.current = item.name;
    onChange?.(item.name);
    onCommit?.(item.name);
    setOpen(false);
  }

  function handleChange(next) {
    clearBlurTimer();
    latestValue.current = next;
    onChange?.(next);
    setActive(0);
    setOpen(true);
  }

  function handleFocus() {
    if (disabled) return;
    clearBlurTimer();
    setOpen(true);
  }

  function handleBlur() {
    if (disabled) return;
    clearBlurTimer();
    blurTimer.current = setTimeout(() => {
      blurTimer.current = null;
      setOpen(false);
      const settled = latestValue.current;
      if (settled !== committedValue.current) {
        committedValue.current = settled;
        onCommitRef.current?.(settled);
      }
    }, blurCommitDelay);
  }

  function handleKeyPress(event) {
    if (disabled) return;
    const key = event?.nativeEvent?.key ?? event?.key;
    if (key === 'ArrowDown' || key === 'ArrowUp') {
      if (!items.length) return;
      event.preventDefault?.();
      if (!open) {
        setOpen(true);
        return;
      }
      setActive(index => (Math.max(0, index) + (key === 'ArrowDown' ? 1 : -1) + items.length) % items.length);
    } else if (key === 'Enter') {
      if (listOpen && items[current]) {
        event.preventDefault?.();
        choose(items[current]);
      }
    } else if (key === 'Escape') {
      event.preventDefault?.();
      setOpen(false);
    }
  }

  return <View style={[styles.field, listOpen && styles.fieldOpen]} testID={testID}>
    <Text nativeID={id ? `${id}-label` : undefined} style={[styles.label, { color: colors.textMuted }]}>{label}</Text>
    <View style={styles.control}>
      <TextInput
        nativeID={id}
        accessibilityLabel={accessibilityLabel || label}
        accessibilityState={{ disabled, expanded: listOpen }}
        role="combobox"
        aria-autocomplete="list"
        aria-controls={listOpen ? optionsId : undefined}
        aria-expanded={listOpen}
        aria-activedescendant={listOpen && optionsId ? `${optionsId}-${current}` : undefined}
        autoCapitalize="none"
        autoComplete="off"
        autoCorrect={false}
        blurOnSubmit={false}
        editable={!disabled}
        maxLength={maxLength}
        onChangeText={handleChange}
        onBlur={handleBlur}
        onFocus={handleFocus}
        onKeyPress={handleKeyPress}
        placeholder={placeholder}
        placeholderTextColor={colors.textMuted}
        returnKeyType="done"
        style={[styles.input, {
          borderColor: colors.border,
          backgroundColor: colors.surface,
          color: colors.textSecondary,
          opacity: disabled ? 0.5 : 1,
        }]}
        value={text}
      />
      {listOpen ? <View
        nativeID={optionsId}
        role="listbox"
        aria-label={label}
        style={[styles.options, { backgroundColor: colors.surfaceStrong, borderColor: colors.border }]}>
        <ScrollView keyboardShouldPersistTaps="handled" nestedScrollEnabled style={styles.optionsScroll}>
          {items.map((item, index) => {
            const selected = index === current;
            return <Pressable
              key={item.key}
              nativeID={optionsId ? `${optionsId}-${index}` : undefined}
              role="option"
              aria-selected={selected}
              accessibilityRole="button"
              accessibilityLabel={item.label}
              accessibilityState={{ selected }}
              focusable={false}
              onPressIn={clearBlurTimer}
              onPress={() => choose(item)}
              style={({ hovered, pressed }) => [styles.option,
                (hovered || pressed) && { backgroundColor: colors.surfaceMuted },
                selected && { backgroundColor: colors.surface },
              ]}>
              <Text numberOfLines={1} style={[styles.optionText, { color: item.create ? colors.accent : colors.textSecondary }]}>
                {item.label}
              </Text>
            </Pressable>;
          })}
        </ScrollView>
      </View> : null}
    </View>
  </View>;
}

const styles = StyleSheet.create({
  field: { gap: 4 },
  fieldOpen: { zIndex: 2 },
  control: { position: 'relative' },
  label: { fontSize: 12, fontWeight: '600' },
  input: {
    borderWidth: 1,
    borderRadius: 8,
    paddingHorizontal: 12,
    paddingVertical: 9,
    fontSize: 14,
  },
  options: {
    position: 'absolute',
    top: '100%',
    left: 0,
    right: 0,
    marginTop: 4,
    borderWidth: 1,
    borderRadius: 8,
    overflow: 'hidden',
    zIndex: 50,
  },
  optionsScroll: { maxHeight: 240 },
  option: { paddingHorizontal: 12, paddingVertical: 9 },
  optionText: { fontSize: 14 },
});
