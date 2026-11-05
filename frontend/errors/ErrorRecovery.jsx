import React from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { Chip } from '../settings/Chip';
import { SettingsCard } from '../settings/SettingsCard';
import { Button } from '../ui/Button';
import { CopyBlock } from '../ui/CopyBlock';

const defaultLabels = {
  copy: 'Copy',
  copied: 'Copied',
  reportIssue: 'Report the issue',
  home: 'Back to Home',
  login: 'Log In',
  retry: 'Try Again',
  checks: 'Quick checks',
  traceback: 'Traceback',
  reportNote: 'Copy this block when opening a ticket so the traceback and request details are preserved.',
};

const statusColors = {
  400: '#f97316',
  403: '#f87171',
  404: '#6366f1',
  500: '#ef4444',
};

function cardPalette(palette) {
  return {
    text: palette.text,
    border: palette.border,
    background: palette.surface,
    badgeBorder: palette.border,
    badgeBackground: palette.surfaceStrong,
    badgeText: palette.textSecondary,
    badgeHover: palette.surfaceMuted,
    focusStyle: palette.focusStyle,
  };
}

function actionPalette(palette) {
  return {
    primary: {
      background: palette.accentStrong,
      pressed: palette.accent,
      hovered: palette.accent,
      text: '#ffffff',
      border: 'transparent',
    },
    surface: {
      background: palette.surfaceStrong,
      pressed: palette.surfaceMuted,
      hovered: palette.surfaceMuted,
      text: palette.text,
      border: palette.border,
    },
    'ghost-danger': {
      background: 'transparent',
      pressed: 'rgba(220, 38, 38, 0.2)',
      hovered: 'rgba(220, 38, 38, 0.2)',
      text: palette.danger,
      border: 'transparent',
    },
    radius: 6,
    focusStyle: palette.focusStyle,
  };
}

export function ErrorStatusSelector({ options, selected, onSelect, palette, accessibilityLabel }) {
  return <View accessibilityRole="group" accessibilityLabel={accessibilityLabel} style={styles.statusRow}>
    {options.map(option => {
      const active = option.value === selected;
      return <Chip key={option.value} label={option.label} pill
        pressed={active} accessibilityRole="button" accessibilityLabel={option.accessibilityLabel || option.label}
        onPress={() => onSelect?.(option.value)}
        palette={{
          badgeBorder: active ? palette.accent : palette.border,
          badgeBackground: active ? palette.accentStrong : palette.surfaceStrong,
          badgeText: active ? '#ffffff' : palette.textSecondary,
          badgeHover: active ? palette.accent : palette.surfaceMuted,
          focusStyle: palette.focusStyle,
        }} />;
    })}
  </View>;
}

export function ErrorReportPanel({
  report,
  title = defaultLabels.traceback,
  note = defaultLabels.reportNote,
  copyLabel = defaultLabels.copy,
  copiedLabel = defaultLabels.copied,
  onCopy,
  palette,
  testID,
}) {
  return <SettingsCard title={title} badge="Diagnostic" palette={cardPalette(palette)}>
    <CopyBlock text={report} note={note} copyLabel={copyLabel} copiedLabel={copiedLabel}
      onCopy={onCopy} palette={palette} testID={testID} />
  </SettingsCard>;
}

export function ErrorRecovery({
  status,
  heading,
  message,
  checks,
  checksTitle = defaultLabels.checks,
  support,
  report,
  reportTitle = defaultLabels.traceback,
  reportNote = defaultLabels.reportNote,
  labels = {},
  palette,
  onCopyReport,
  onReportIssue,
  onRetry,
  onLogin,
  onGoHome,
}) {
  const copy = { ...defaultLabels, ...labels };
  const buttons = actionPalette(palette);
  const actions = [onRetry, onLogin, onGoHome].filter(Boolean).length;

  return <View style={styles.stack}>
    <View style={styles.hero}>
      <Text style={[styles.status, { color: statusColors[status] || palette.accent }]}>{status}</Text>
      <Text role="heading" aria-level={2} style={[styles.heading, { color: palette.text }]}>{heading}</Text>
      <Text style={[styles.message, { color: palette.textMuted }]}>{message}</Text>
    </View>

    {checks?.length ? <SettingsCard title={checksTitle} badge={String(status)} palette={cardPalette(palette)}>
      <View style={styles.checkList}>
        {checks.map(check => <View key={check} style={styles.checkRow}>
          <View style={[styles.bullet, { backgroundColor: palette.textMuted }]} />
          <Text style={[styles.checkText, { color: palette.textMuted }]}>{check}</Text>
        </View>)}
      </View>
    </SettingsCard> : null}

    {support ? <SettingsCard title={support.title} badge={support.badge || 'Provider note'} palette={cardPalette(palette)}>
      <Text style={[styles.supportBody, { color: palette.textSecondary }]}>{support.body}</Text>
      {support.linkLabel && support.onOpen ? <View style={styles.inlineAction}>
        <Button label={support.linkLabel} tone="surface" onPress={support.onOpen} palette={buttons} />
      </View> : null}
    </SettingsCard> : null}

    <ErrorReportPanel report={report} title={reportTitle} note={reportNote}
      copyLabel={copy.copy} copiedLabel={copy.copied} onCopy={onCopyReport} palette={palette} />

    {onReportIssue ? <View style={styles.inlineAction}>
      <Button label={copy.reportIssue} tone="ghost-danger" onPress={onReportIssue} palette={buttons} />
    </View> : null}

    {actions ? <View style={styles.actionRow}>
      {onRetry ? <Button label={copy.retry} onPress={onRetry} palette={buttons} /> : null}
      {onLogin ? <Button label={copy.login} tone="surface" onPress={onLogin} palette={buttons} /> : null}
      {onGoHome ? <Button label={copy.home} tone={actions > 1 ? 'surface' : 'primary'} onPress={onGoHome} palette={buttons} /> : null}
    </View> : null}
  </View>;
}

const styles = StyleSheet.create({
  stack: { gap: 16 },
  statusRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  hero: { gap: 8, alignItems: 'center', paddingVertical: 8 },
  status: { fontSize: 56, fontWeight: '800', lineHeight: 60 },
  heading: { fontSize: 24, fontWeight: '700', textAlign: 'center' },
  message: { fontSize: 14, lineHeight: 21, textAlign: 'center' },
  checkList: { gap: 8 },
  checkRow: { flexDirection: 'row', alignItems: 'flex-start', gap: 8 },
  bullet: { width: 5, height: 5, borderRadius: 3, marginTop: 7 },
  checkText: { flex: 1, fontSize: 13, lineHeight: 19 },
  supportBody: { fontSize: 13, lineHeight: 20 },
  inlineAction: { flexDirection: 'row' },
  actionRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
});
