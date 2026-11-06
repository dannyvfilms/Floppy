import React from 'react';
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { palette, spacing } from '../theme';

export function Screen({ title, subtitle, children, scroll = true, onBack, chrome = true }) {
  const body = scroll
    ? <ScrollView contentContainerStyle={styles.content} keyboardShouldPersistTaps="handled">{children}</ScrollView>
    : <View style={styles.content}>{children}</View>;
  return <View style={styles.screen}>
    {chrome ? <View style={styles.header}>
      {onBack ? <Pressable accessibilityRole="button" accessibilityLabel="Back" onPress={onBack} style={styles.back}>
        <Text style={styles.backText}>Back</Text>
      </Pressable> : null}
      <View style={styles.heading}>
        <Text role="heading" aria-level={1} style={styles.title}>{title}</Text>
        {subtitle ? <Text style={styles.subtitle}>{subtitle}</Text> : null}
      </View>
    </View> : null}
    {body}
  </View>;
}

const styles = StyleSheet.create({
  screen: { flex: 1, minHeight: 0 },
  header: { paddingHorizontal: spacing.lg, paddingTop: spacing.sm, paddingBottom: spacing.md, gap: spacing.sm },
  heading: { gap: 2 },
  title: { color: palette.text, fontSize: 28, fontWeight: '700' },
  subtitle: { color: palette.textMuted, fontSize: 13 },
  back: { alignSelf: 'flex-start', paddingVertical: 4, paddingRight: 8 },
  backText: { color: palette.accent, fontSize: 14, fontWeight: '600' },
  content: { paddingHorizontal: spacing.lg, paddingBottom: spacing.xl, gap: spacing.lg },
  section: { gap: spacing.sm },
  sectionTitle: { color: palette.text, fontSize: 17, fontWeight: '600' },
  sectionCopy: { color: palette.textMuted, fontSize: 12 },
});

export function Section({ title, copy, children }) {
  return <View style={styles.section}>
    <Text style={styles.sectionTitle}>{title}</Text>
    {copy ? <Text style={styles.sectionCopy}>{copy}</Text> : null}
    {children}
  </View>;
}
