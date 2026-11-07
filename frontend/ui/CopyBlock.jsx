import React, { useEffect, useState } from 'react';
import { ScrollView, StyleSheet, Text, View } from 'react-native';
import { Button } from './Button';

/** Copyable code/report block. Callers own the platform copy action and pass
 * the text to copy; this component owns the presentation and copied feedback.
 */
export function CopyBlock({
  text,
  label,
  note,
  copyLabel = 'Copy',
  copiedLabel = 'Copied',
  onCopy,
  palette,
  testID,
}) {
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!copied) return undefined;
    const timer = setTimeout(() => setCopied(false), 2000);
    return () => clearTimeout(timer);
  }, [copied]);

  async function copy() {
    if (!onCopy) return;
    const result = await onCopy(text);
    if (result !== false) setCopied(true);
  }

  const buttonPalette = {
    surface: {
      background: palette.surfaceStrong,
      pressed: palette.surfaceMuted,
      hovered: palette.surfaceMuted,
      text: palette.text,
      border: palette.border,
    },
    radius: 6,
    focusStyle: palette.focusStyle,
  };

  return <View style={styles.wrap} testID={testID}>
    {label ? <Text style={[styles.label, { color: palette.textSecondary }]}>{label}</Text> : null}
    {note ? <Text style={[styles.note, { color: palette.textMuted }]}>{note}</Text> : null}
    <View style={[styles.frame, { backgroundColor: palette.background, borderColor: palette.border }]}>
      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.scrollContent}>
        <Text selectable style={[styles.code, { color: palette.textSecondary }]}>{text}</Text>
      </ScrollView>
    </View>
    {onCopy ? <View style={styles.actions}>
      <Button label={copied ? copiedLabel : copyLabel} tone="surface" onPress={copy}
        accessibilityLabel={copied ? copiedLabel : copyLabel} palette={buttonPalette} />
    </View> : null}
  </View>;
}

const styles = StyleSheet.create({
  wrap: { gap: 8 },
  label: { fontSize: 13, fontWeight: '600' },
  note: { fontSize: 12, lineHeight: 17 },
  frame: { borderWidth: 1, borderRadius: 8, padding: 12 },
  scrollContent: { minWidth: '100%' },
  code: { fontSize: 12, lineHeight: 18, fontFamily: 'monospace' },
  actions: { flexDirection: 'row', justifyContent: 'flex-end' },
});
