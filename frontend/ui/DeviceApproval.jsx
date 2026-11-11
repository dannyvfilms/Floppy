import React, { useState } from 'react';
import { Pressable, StyleSheet, Text, TextInput, View, useWindowDimensions } from 'react-native';

const DEFAULT_PALETTE = {
  surface: '#27272a',
  surfaceStrong: '#3f3f46',
  surfaceMuted: '#52525b',
  border: '#3f3f46',
  text: '#fafafa',
  textSecondary: '#d4d4d8',
  textMuted: '#a1a1aa',
  accent: '#4f46e5',
  accentContrast: '#ffffff',
  dangerTint: 'rgba(239, 68, 68, 0.1)',
  dangerBorder: 'rgba(239, 68, 68, 0.4)',
  successTint: 'rgba(74, 222, 128, 0.1)',
  successBorder: 'rgba(74, 222, 128, 0.28)',
  warningTint: 'rgba(245, 158, 11, 0.1)',
  warningBorder: 'rgba(245, 158, 11, 0.4)',
  mono: 'Courier',
  focusStyle: {},
};

function Notice({ tone, colors, children }) {
  return <View style={[styles.notice, { backgroundColor: colors[`${tone}Tint`], borderColor: colors[`${tone}Border`] }]}>
    {children}
  </View>;
}

function Action({ label, kind, colors, onPress, disabled, stretch }) {
  const primary = kind === 'primary';
  return <Pressable
    accessibilityRole="button"
    disabled={disabled}
    onPress={onPress}
    style={({ focused }) => [
      styles.action,
      primary
        ? { backgroundColor: colors.accent, borderColor: 'transparent' }
        : { backgroundColor: 'transparent', borderColor: colors.border },
      stretch && styles.stretch,
      disabled && { opacity: 0.5 },
      focused && colors.focusStyle,
    ]}>
    <Text style={[styles.actionLabel, { color: primary ? colors.accentContrast : colors.textSecondary }]}>{label}</Text>
  </Pressable>;
}

/**
 * Presentation for the OAuth device approval page. The caller owns the posting:
 * `onContinue(code)` looks a code up, `onDecide('approve' | 'deny')` answers it.
 * `authorization` is { state: 'approved' | 'denied' | 'pending', clientName,
 * fullAccount, scopes: [{ label, description }] } or null.
 */
export function DeviceApprovalCard({
  userCode = '',
  error = '',
  success = '',
  authorization = null,
  busy = false,
  palette = {},
  onContinue,
  onDecide,
}) {
  const colors = { ...DEFAULT_PALETTE, ...palette };
  const [code, setCode] = useState(userCode);
  const stacked = useWindowDimensions().width < 640;
  const pending = authorization && !error && !success;
  const submitCode = () => onContinue?.(code.trim());
  return <View style={styles.page}>
    <View>
      <Text accessibilityRole="header" style={[styles.title, { color: colors.text }]}>Authorise Application</Text>
      <Text style={[styles.lede, { color: colors.textMuted }]}>
        Enter the code shown on your device, then review the permissions before allowing access.
      </Text>
    </View>

    <View style={[styles.card, { backgroundColor: colors.surface }]}>
      <View style={styles.codeBlock}>
        <Text style={[styles.label, { color: colors.text }]}>Device code</Text>
        <View style={[styles.codeRow, stacked ? styles.stacked : styles.inline]}>
          <TextInput
            accessibilityLabel="Device code"
            autoCapitalize="characters"
            autoComplete="one-time-code"
            autoCorrect={false}
            spellCheck={false}
            onChangeText={setCode}
            onSubmitEditing={submitCode}
            placeholder="ABCD-EFGH"
            placeholderTextColor={colors.textMuted}
            value={code}
            style={[styles.input, !stacked && styles.inputGrow, {
              backgroundColor: colors.surfaceStrong,
              borderColor: colors.border,
              color: colors.text,
              fontFamily: colors.mono,
            }]}
          />
          <Action label="Continue" kind="primary" colors={colors} onPress={submitCode} disabled={busy || !code.trim()} stretch={stacked} />
        </View>
      </View>

      {error ? <Notice tone="danger" colors={colors}>
        <Text accessibilityRole="alert" style={[styles.noticeText, { color: colors.text }]}>{error}</Text>
      </Notice> : null}

      {success ? <Notice tone="success" colors={colors}>
        <Text style={[styles.noticeText, { color: colors.text }]}>{success} You can return to your device.</Text>
      </Notice> : null}

      {pending && authorization.state === 'approved' ? <Notice tone="success" colors={colors}>
        <Text style={[styles.noticeText, { color: colors.text }]}>This application has already been authorised. You can return to your device.</Text>
      </Notice> : null}

      {pending && authorization.state === 'denied' ? <View style={[styles.notice, { backgroundColor: colors.surfaceMuted, borderColor: colors.border }]}>
        <Text style={[styles.noticeText, { color: colors.text }]}>This application request has already been denied.</Text>
      </View> : null}

      {pending && authorization.state === 'pending' ? <View style={[styles.decision, { borderTopColor: colors.border }]}>
        <View>
          <Text style={[styles.small, { color: colors.textMuted }]}>Application</Text>
          <Text style={[styles.client, { color: colors.text }]}>{authorization.clientName}</Text>
        </View>

        {authorization.fullAccount ? <Notice tone="warning" colors={colors}>
          <Text style={[styles.noticeText, { color: colors.text }]}>
            <Text style={styles.bold}>Approving signs the Floppy app into your account with full access.</Text>
            {' '}It can do everything you can do when signed in, including changing your account, connections and tokens.
          </Text>
          <Text style={[styles.noticeText, styles.noticeGap, { color: colors.text }]}>Only approve if you started this sign-in from the Floppy app yourself.</Text>
        </Notice> : <>
          <Notice tone="warning" colors={colors}>
            <Text style={[styles.noticeText, { color: colors.text }]}>
              <Text style={styles.bold}>Unverified application.</Text>
              {' '}Floppy cannot check who made it. The name above is whatever the app chose for itself.
            </Text>
          </Notice>
          <View>
            <Text accessibilityRole="header" style={[styles.permissions, { color: colors.text }]}>Requested permissions</Text>
            <View style={styles.scopeList}>
              {(authorization.scopes || []).map(item => <View key={item.label} style={[styles.scope, { backgroundColor: colors.surfaceStrong }]}>
                <Text style={[styles.scopeLabel, { color: colors.text }]}>{item.label}</Text>
                <Text style={[styles.scopeText, { color: colors.textMuted }]}>{item.description}</Text>
              </View>)}
            </View>
          </View>
        </>}

        <View style={styles.actions}>
          <Action label="Allow" kind="primary" colors={colors} disabled={busy} onPress={() => onDecide?.('approve')} />
          <Action label="Deny" kind="secondary" colors={colors} disabled={busy} onPress={() => onDecide?.('deny')} />
        </View>
      </View> : null}
    </View>

    <Text style={[styles.footer, { color: colors.textMuted }]}>
      Only approve a code you requested from a device or application you recognise. Floppy never gives the application your password.
    </Text>
  </View>;
}

const styles = StyleSheet.create({
  page: { width: '100%', maxWidth: 672, alignSelf: 'center', gap: 24 },
  title: { fontSize: 30, lineHeight: 36, fontWeight: '700' },
  lede: { fontSize: 14, lineHeight: 20, marginTop: 8 },
  card: { borderRadius: 8, padding: 24, gap: 24 },
  codeBlock: { gap: 12 },
  label: { fontSize: 14, lineHeight: 20, fontWeight: '500' },
  codeRow: { gap: 12 },
  stacked: { flexDirection: 'column' },
  inline: { flexDirection: 'row', alignItems: 'center' },
  input: { borderWidth: 1, borderRadius: 6, paddingHorizontal: 12, paddingVertical: 8, fontSize: 16, lineHeight: 24, letterSpacing: 0.8, textTransform: 'uppercase' },
  inputGrow: { flex: 1 },
  stretch: { alignSelf: 'stretch' },
  action: { borderWidth: 1, borderRadius: 6, paddingHorizontal: 15, paddingVertical: 7, alignItems: 'center', justifyContent: 'center', alignSelf: 'flex-start' },
  actionLabel: { fontSize: 16, lineHeight: 24, fontWeight: '400' },
  notice: { borderWidth: 1, borderRadius: 6, paddingHorizontal: 16, paddingVertical: 12 },
  noticeText: { fontSize: 14, lineHeight: 20 },
  noticeGap: { marginTop: 8 },
  bold: { fontWeight: '700' },
  decision: { borderTopWidth: 1, paddingTop: 24, gap: 16 },
  small: { fontSize: 14, lineHeight: 20 },
  client: { fontSize: 20, lineHeight: 28, fontWeight: '600', marginTop: 4 },
  permissions: { fontSize: 16, lineHeight: 24, fontWeight: '500', marginBottom: 12 },
  scopeList: { gap: 12 },
  scope: { borderRadius: 6, padding: 12 },
  scopeLabel: { fontSize: 14, lineHeight: 20, fontWeight: '500' },
  scopeText: { fontSize: 12, lineHeight: 16, marginTop: 4 },
  actions: { flexDirection: 'row', flexWrap: 'wrap', gap: 12, paddingTop: 8 },
  footer: { fontSize: 12, lineHeight: 16 },
});
