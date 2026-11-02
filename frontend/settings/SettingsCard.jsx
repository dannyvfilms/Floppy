import React from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { Chip } from './Chip';

/** Shared presentation only. Native consumers supply concrete theme colors and children.
 * The Django adapter uses framed=false: its server-owned body is a sibling of this root.
 */
export function SettingsCard({ title, badge, info_label, info_title, onInfo, palette,
  children, headerAction, framed = true }) {
  return (
    <View style={framed ? [styles.card, {
      borderColor: palette.border, backgroundColor: palette.background,
    }] : styles.content}>
      <View style={styles.heading} testID="settings-card-heading">
        <Text role="heading" aria-level={4} style={[styles.title, { color: palette.text, fontFamily: palette.fontFamily }]}>
          {title}
        </Text>
        {headerAction ?? (badge && <Chip label={badge} palette={palette} onPress={onInfo}
          accessibilityLabel={info_label} accessibilityHint={info_title}
          hasPopup={onInfo ? 'dialog' : undefined} testID="settings-card-badge" />)}
      </View>
      {children}
    </View>
  );
}

const styles = StyleSheet.create({
  content: { gap: 12, minWidth: 0 },
  card: { borderWidth: 1, borderRadius: 8, padding: 16, gap: 12 },
  heading: { flexDirection: 'row', flexWrap: 'nowrap', minWidth: 0, alignItems: 'flex-start', justifyContent: 'space-between', gap: 12 },
  title: { fontSize: 16, fontWeight: '500', lineHeight: 24, flexGrow: 1, flexShrink: 1, flexBasis: 0, minWidth: 0 },
});
