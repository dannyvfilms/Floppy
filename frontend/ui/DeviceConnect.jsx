import React, { useEffect, useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { Button } from './Button';
import { Spinner } from './Spinner';

const DEFAULT_PALETTE = {
  surface: '#27272a',
  codeBackground: '#18181b',
  text: '#fafafa',
  textSecondary: '#d4d4d8',
  textMuted: '#a1a1aa',
  border: '#3f3f46',
  surfaceStrong: '#3f3f46',
  surfaceHover: '#52525b',
  accent: '#4f46e5',
  accentContrast: '#ffffff',
  success: '#10b981',
  warning: '#f59e0b',
  danger: '#ef4444',
  radius: 8,
  focusStyle: {},
};

const DEFAULT_LABELS = {
  copy: 'Copy code',
  copied: 'Copied!',
  open: 'Open activation page',
  waiting: 'Waiting for you to authorize Floppy…',
  approved: 'Authorized. Returning to Floppy…',
  expired: 'The authorization code expired. Start again.',
  error: 'The authorization could not be completed. Try again.',
  cancel: 'Cancel',
  retry: 'Start again',
};

function mergePalette(palette) {
  return { ...DEFAULT_PALETTE, ...(palette || {}) };
}

function mergeLabels(labels) {
  return { ...DEFAULT_LABELS, ...(labels || {}) };
}

function buttonPalette(colors) {
  return {
    primary: {
      background: colors.accent,
      pressed: colors.accent,
      hovered: colors.accent,
      text: colors.accentContrast,
      border: 'transparent',
    },
    surface: {
      background: colors.surfaceStrong,
      pressed: colors.surfaceHover,
      hovered: colors.surfaceHover,
      text: colors.text,
      border: colors.border,
    },
    radius: colors.radius,
    focusStyle: colors.focusStyle,
  };
}

export function DeviceConnectCard({
  code = '',
  state = 'waiting',
  error = '',
  title = 'Connect Trakt',
  description = '',
  labels = {},
  palette = {},
  onCopy,
  onOpen,
  onCancel,
  onRetry,
}) {
  const colors = mergePalette(palette);
  const copy = mergeLabels(labels);
  const buttons = buttonPalette(colors);
  const [copied, setCopied] = useState(false);
  const waiting = state === 'waiting';
  const approved = state === 'approved';
  const expired = state === 'expired';
  const failed = state === 'error';

  useEffect(() => {
    if (!copied) return undefined;
    const timer = setTimeout(() => setCopied(false), 2000);
    return () => clearTimeout(timer);
  }, [copied]);

  async function copyCode() {
    try {
      await onCopy?.(code);
      setCopied(true);
    } catch (copyError) {
      setCopied(false);
    }
  }

  const status = failed
    ? error || copy.error
    : expired
      ? copy.expired
      : approved
        ? copy.approved
        : copy.waiting;
  const statusColor = failed ? colors.danger : expired ? colors.warning : approved ? colors.success : colors.textMuted;

  return <View style={styles.card}>
    <Text role="heading" aria-level={1} style={[styles.title, { color: colors.text }]}>{title}</Text>
    {description ? <Text style={[styles.description, { color: colors.textMuted }]}>{description}</Text> : null}

    <View style={[styles.codeBox, { backgroundColor: colors.codeBackground }]}>
      <Text selectable accessibilityLabel={`${copy.copy}: ${code}`}
        style={[styles.code, { color: colors.text }]}>{code}</Text>
    </View>

    <View style={styles.copyRow}>
      <Button label={copied ? copy.copied : copy.copy} tone="surface" onPress={copyCode} palette={buttons} />
    </View>

    <Button label={copy.open} width="full" disabled={!waiting}
      onPress={() => onOpen?.()} palette={buttons} />

    <View accessibilityLiveRegion="polite" style={styles.status}>
      {waiting ? <Spinner size={16} color={colors.accent} /> : null}
      <Text style={[styles.statusText, { color: statusColor }]}>{status}</Text>
    </View>

    <View style={styles.actions}>
      {(expired || failed) && onRetry ? <Button label={copy.retry} tone="surface" onPress={onRetry} palette={buttons} /> : null}
      {onCancel ? <Pressable accessibilityRole="button" accessibilityLabel={copy.cancel}
        onPress={onCancel} style={styles.cancel}>
        <Text style={[styles.cancelText, { color: colors.textMuted }]}>{copy.cancel}</Text>
      </Pressable> : null}
    </View>
  </View>;
}

const styles = StyleSheet.create({
  card: { gap: 12, borderRadius: 8, padding: 24, alignItems: 'stretch' },
  title: { fontSize: 24, fontWeight: '700', textAlign: 'center' },
  description: { fontSize: 13, lineHeight: 19, textAlign: 'center' },
  codeBox: { borderRadius: 6, paddingVertical: 16, paddingHorizontal: 12 },
  code: { fontSize: 28, fontWeight: '700', letterSpacing: 4, textAlign: 'center' },
  copyRow: { alignItems: 'center' },
  status: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 8 },
  statusText: { flexShrink: 1, fontSize: 13, textAlign: 'center' },
  actions: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', flexWrap: 'wrap', gap: 12 },
  cancel: { paddingVertical: 4, paddingHorizontal: 8 },
  cancelText: { fontSize: 12 },
});
