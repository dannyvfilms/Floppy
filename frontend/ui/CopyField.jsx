import React, { useEffect, useRef, useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { Button } from './Button';
import { Icon } from './Icon';
import { actionIcons } from './actionIcons';
import { ConfirmDialog } from '../settings/ConfirmDialog';

const defaultPalette = {
  text: '#fafafa',
  textSecondary: '#d4d4d8',
  textMuted: '#a1a1aa',
  surface: '#27272a',
  surfaceStrong: '#3f3f46',
  surfaceMuted: '#52525b',
  border: '#52525b',
  success: '#10b981',
  danger: '#ef4444',
  link: '#818cf8',
  radius: 8,
  focusStyle: {},
};

const defaultButtonPalette = {
  primary: { background: '#4f46e5', pressed: '#4338ca', hovered: '#4338ca', text: '#ffffff', border: 'transparent' },
  surface: { background: '#3f3f46', pressed: '#52525b', hovered: '#52525b', text: '#fafafa', border: '#3f3f46' },
  radius: 6,
  focusStyle: {},
};

/**
 * Copyable read-only value. The caller supplies the platform clipboard action;
 * a rejected or false result keeps the value visible and opens the manual
 * recovery instructions instead of losing the user's text.
 *
 * A credential is never passed as `value`: the adapter renders it in its own
 * `valueSlot` and reads it in `onCopy`, so secrets stay out of presentation
 * props (the same contract as the Access cards' tokenSlot/secretSlot).
 *
 * `variant="inline"` keeps the server copy control's look: the value fills the
 * row and a copy icon sits after it, turning into a check for three seconds
 * after a copy. `label` then only names the icon button for assistive tech.
 */
export function CopyField({
  label,
  value,
  valueSlot,
  variant = 'stacked',
  help,
  copyLabel = 'Copy',
  copiedLabel = 'Copied!',
  errorMessage = 'Could not copy automatically.',
  manualLabel = 'How to copy manually',
  retryLabel = 'Try again',
  closeLabel = 'Close',
  recoveryTitle = 'Copy manually',
  recoveryMessage = 'Select the value above and copy it with your usual shortcut, or tap and hold the value and choose Copy.',
  onCopy,
  disabled = false,
  palette = {},
  buttonPalette = {},
  testID,
}) {
  const colors = { ...defaultPalette, ...palette };
  const buttons = { ...defaultButtonPalette, ...buttonPalette };
  const [state, setState] = useState('idle');
  const [recoveryOpen, setRecoveryOpen] = useState(false);
  const timer = useRef(null);

  useEffect(() => () => clearTimeout(timer.current), []);

  const copy = async () => {
    if (disabled) return;
    clearTimeout(timer.current);
    setState('busy');
    try {
      const result = await onCopy?.(value);
      if (result === false || result === undefined) throw new Error('copy unavailable');
      setState('copied');
      timer.current = setTimeout(() => setState('idle'), 3000);
    } catch (error) {
      setState('error');
      setRecoveryOpen(true);
    }
  };

  const status = state === 'copied'
    ? <Text accessibilityLiveRegion="polite" style={[styles.status, { color: colors.success }]}>{copiedLabel}</Text>
    : state === 'error'
      ? <View style={styles.error}>
        <Text accessibilityLiveRegion="polite" style={[styles.errorText, { color: colors.danger }]}>{errorMessage}</Text>
        <View style={styles.errorActions}>
          <Button label={manualLabel} tone="surface" onPress={() => setRecoveryOpen(true)} palette={buttons} />
          <Button label={retryLabel} tone="surface" onPress={copy} palette={buttons} />
        </View>
      </View>
      : null;

  const recovery = <ConfirmDialog visible={recoveryOpen} title={recoveryTitle} message={recoveryMessage}
    confirmLabel={retryLabel} cancelLabel={closeLabel} palette={{ ...colors, overlay: 'rgba(0, 0, 0, 0.6)' }}
    buttonPalette={{ ...buttons, 'danger-solid': buttons.primary }}
    onCancel={() => setRecoveryOpen(false)}
    onConfirm={() => { setRecoveryOpen(false); copy(); }} />;

  if (variant === 'inline') {
    const copied = state === 'copied';
    const blocked = disabled || (!value && !valueSlot);
    const busy = state === 'busy';
    const unavailable = blocked || busy;
    return <View style={styles.field} testID={testID}>
      <View style={styles.inlineRow}>
        <View style={styles.inlineValue}>
          {valueSlot || <Text selectable accessibilityLabel={`${label}: ${value}`} style={[styles.value, { color: colors.textSecondary }]}>{value}</Text>}
        </View>
        <Pressable accessibilityRole="button"
          accessibilityLabel={copied ? copiedLabel : `${copyLabel} ${label}`}
          accessibilityState={{ disabled: unavailable, busy }}
          disabled={unavailable} onPress={unavailable ? undefined : copy}
          style={[styles.inlineButton, { opacity: blocked ? 0.5 : 1 }]}>
          {({ hovered }) => <Icon spec={copied ? actionIcons.check : actionIcons.copy} size={20}
            color={copied ? colors.copiedIcon || colors.success : hovered ? colors.link : colors.textMuted} />}
        </Pressable>
      </View>
      <Text accessibilityLiveRegion="polite" style={styles.visuallyHidden}>{copied ? copiedLabel : ''}</Text>
      {state === 'error' ? status : null}
      {recovery}
    </View>;
  }

  return <View style={styles.field} testID={testID}>
    <View style={styles.labelRow}>
      <Text style={[styles.label, { color: colors.textMuted }]}>{label}</Text>
      <Button label={copyLabel} tone="surface" busy={state === 'busy'} disabled={disabled || (!value && !valueSlot)}
        accessibilityLabel={`${copyLabel} ${label}`} onPress={copy} palette={buttons} />
    </View>
    {valueSlot || <View style={[styles.valueBox, { backgroundColor: colors.surface, borderColor: colors.border, borderRadius: colors.radius }]}>
      <Text selectable accessibilityLabel={`${label}: ${value}`} style={[styles.value, { color: colors.textSecondary }]}>{value}</Text>
    </View>}
    {help ? <Text style={[styles.help, { color: colors.textMuted }]}>{help}</Text> : null}
    {status}
    {recovery}
  </View>;
}

const styles = StyleSheet.create({
  field: { gap: 6 },
  labelRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 8 },
  label: { flexShrink: 1, fontSize: 12, fontWeight: '600' },
  valueBox: { borderWidth: 1, paddingHorizontal: 10, paddingVertical: 8, minWidth: 0 },
  value: { fontSize: 13, lineHeight: 18 },
  help: { fontSize: 12, lineHeight: 17 },
  status: { fontSize: 12, fontWeight: '600' },
  error: { gap: 6 },
  errorText: { fontSize: 12, lineHeight: 17 },
  errorActions: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  // Mirrors the server control: `flex items-center gap-2`, a `flex-1` value
  // and a `pr-3` icon.
  inlineRow: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  inlineValue: { flex: 1, minWidth: 0 },
  inlineButton: { paddingRight: 12 },
  visuallyHidden: { position: 'absolute', width: 1, height: 1, overflow: 'hidden', opacity: 0 },
});
