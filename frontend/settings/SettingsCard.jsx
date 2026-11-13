import React from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { Chip } from './Chip';

/** Shared presentation only. Native consumers supply concrete theme colors and children.
 * The Django adapter uses framed=false: its server-owned body is a sibling of this root.
 */
export function SettingsCard({ title, badge, info_label, info_title, onInfo, palette,
  children, headerAction, icon, contentGap, headingLevel, framed = true, testID = 'settings-card' }) {
  const page = palette.pageCards;
  const access = page === 'access';
  return (
    <View testID={testID} style={framed ? [styles.card, {
      borderColor: palette.border, backgroundColor: palette.background,
      borderRadius: palette.radius ?? 18,
      ...(page ? { borderWidth: 0, padding: access ? 20 : 24, gap: contentGap ?? 16 } : {}),
    }] : styles.content}>
      {title || badge || headerAction || icon ? <View style={styles.heading} testID="settings-card-heading">
        {icon || null}
        <Text role="heading" aria-level={headingLevel ?? (access ? 3 : page ? 2 : 4)} style={[styles.title, { color: palette.text, fontFamily: palette.fontFamily },
          page && { fontSize: access ? 16 : 20, lineHeight: access ? 24 : 28, fontWeight: access ? '500' : '600' }]}>
          {title}
        </Text>
        {headerAction ?? (badge && <Chip label={badge} palette={palette} onPress={onInfo}
          accessibilityLabel={info_label} accessibilityHint={info_title}
          hasPopup={onInfo ? 'dialog' : undefined} testID="settings-card-badge" />)}
      </View> : null}
      {children}
    </View>
  );
}

const styles = StyleSheet.create({
  content: { gap: 12, minWidth: 0 },
  card: { borderWidth: 1, padding: 16, gap: 12 },
  heading: { flexDirection: 'row', flexWrap: 'nowrap', minWidth: 0, alignItems: 'flex-start', justifyContent: 'space-between', gap: 12 },
  title: { fontSize: 16, fontWeight: '500', lineHeight: 24, flexGrow: 1, flexShrink: 1, flexBasis: 0, minWidth: 0 },
});
