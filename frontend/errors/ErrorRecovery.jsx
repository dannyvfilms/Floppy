import React from 'react';
import { Pressable, StyleSheet, Text, useWindowDimensions, View } from 'react-native';
import { Chip } from '../settings/Chip';
import { ErrorReportPanel } from './ErrorReportPanel';

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
  bugPrefix: 'If you believe this was a bug, please',
  bugLink: 'report the issue.',
};

const statusColors = {
  400: '#ff6900',
  403: '#ff6467',
  404: '#615fff',
  500: '#fb2c36',
};

const PRIMARY_BACKGROUND = '#4f39f6';
const PRIMARY_HOVER = '#432dd7';

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

function ActionButton({ label, onPress, icon, tone = 'primary', wide, palette }) {
  const primary = tone === 'primary';
  return <Pressable accessibilityRole="button" accessibilityLabel={label} onPress={onPress}
    style={({ pressed, hovered, focused }) => [styles.action, {
      backgroundColor: primary
        ? (pressed || hovered ? PRIMARY_HOVER : PRIMARY_BACKGROUND)
        : (pressed || hovered ? palette.surfaceMuted : palette.surfaceStrong),
      width: wide ? '100%' : undefined,
    }, focused && palette.focusStyle]}>
    {icon}
    <Text style={[styles.actionLabel, { color: primary ? '#ffffff' : palette.text }]}>{label}</Text>
  </Pressable>;
}

function InlineCode({ children, palette }) {
  return <Text style={{
    fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace',
    color: palette.text,
    backgroundColor: palette.surfaceStrong,
    borderRadius: 4,
    paddingHorizontal: 4,
  }}>{children}</Text>;
}

function ReverseProxyNote({ support, palette }) {
  const [detail, example = ''] = support.body.split(' For example, ');
  const [before, ...after] = detail.split('URLS');
  const exampleValue = example.replace(/\.$/, '');
  return <View style={[styles.sectionCard, { backgroundColor: palette.surface }]}>
    <Text style={[styles.sectionTitle, { color: palette.textSecondary }]}>{support.title}</Text>
    <Text style={[styles.checkLine, { color: palette.textMuted }]}>
      {before}{after.length ? <InlineCode palette={palette}>URLS</InlineCode> : null}{after.join('URLS')}
    </Text>
    {example
      ? <Text style={[styles.checkLine, { color: palette.textMuted, marginTop: 8 }]}>
        For example, <InlineCode palette={palette}>{exampleValue}</InlineCode>.
      </Text>
      : null}
  </View>;
}

function SupportNote({ support, icon, palette }) {
  if (support.title === 'Using a Reverse Proxy?' || (!support.linkLabel && /URLS/.test(support.body))) {
    return <ReverseProxyNote support={support} palette={palette} />;
  }
  return <View style={styles.supportCard}>
    <Text style={styles.supportTitle}>{support.title}</Text>
    <Text style={styles.supportBody}>{support.body}</Text>
    {support.linkLabel && support.onOpen
      ? <Pressable accessibilityRole="link" accessibilityLabel={support.linkLabel}
        onPress={support.onOpen} style={styles.supportLink}>
        <Text style={styles.supportLinkLabel}>{support.linkLabel}</Text>
        {icon}
      </Pressable>
      : null}
  </View>;
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
  icons = {},
  onCopyReport,
  onReportIssue,
  onRetry,
  onLogin,
  onGoHome,
  statusSize = 56,
  headingLevel = 2,
}) {
  const copy = { ...defaultLabels, ...labels };
  const { width } = useWindowDimensions();
  const stacked = width < 640;
  const headingMargin = status === 500 ? 12 : 8;
  const messageMargin = status === 400 ? 32 : status === 403 ? 12 : 16;
  const csrfReason = (checks || []).find(check => check.startsWith('CSRF reason:'));
  const checkItems = csrfReason ? checks.filter(check => check !== csrfReason) : checks;

  return <View style={styles.root}>
    <View style={styles.hero}>
      <Text style={[styles.status, {
        color: statusColors[status] || palette.accent,
        fontSize: statusSize,
        lineHeight: statusSize,
      }]}>{status}</Text>
      <Text role="heading" aria-level={headingLevel} style={[styles.heading, {
        color: palette.text, marginBottom: headingMargin,
      }]}>{heading}</Text>
      <Text style={[styles.message, {
        color: palette.textMuted, marginBottom: messageMargin,
      }]}>{message}</Text>

      {csrfReason ? <Text style={styles.csrfReason}>{csrfReason}</Text> : null}

      {checkItems?.length ? <View style={[styles.sectionCard, { backgroundColor: palette.surface }]}>
        <Text style={[styles.sectionTitle, { color: palette.textSecondary }]}>{checksTitle}</Text>
        {checkItems.map((check, index) => <Text key={check} style={[styles.checkLine, {
          color: palette.textMuted, marginTop: index ? 4 : 0,
        }]}>•  {check}</Text>)}
      </View> : null}

      {support ? <SupportNote support={support} icon={icons.support} palette={palette} /> : null}

      <ErrorReportPanel report={report} title={reportTitle} note={reportNote}
        copyLabel={copy.copy} copiedLabel={copy.copied}
        copyIcon={icons.copy} copiedIcon={icons.copied}
        onCopy={onCopyReport} palette={palette} testID="error-report" />

      {onReportIssue ? <Text style={[styles.bugLine, { color: palette.textMuted }]}>
        {copy.bugPrefix}{' '}
        <Text style={{ color: palette.accent }} accessibilityRole="link" onPress={onReportIssue}>
          {copy.bugLink}
        </Text>
      </Text> : null}
    </View>

    {onRetry || onLogin || onGoHome ? <View style={[styles.actionRow, stacked && styles.actionColumn]}>
      {onRetry ? <ActionButton label={copy.retry} onPress={onRetry} icon={icons.retry}
        wide={stacked} palette={palette} /> : null}
      {onLogin ? <ActionButton label={copy.login} onPress={onLogin} icon={icons.login}
        wide={stacked} palette={palette} /> : null}
      {onGoHome ? <ActionButton label={copy.home} onPress={onGoHome}
        tone={onRetry || onLogin ? 'surface' : 'primary'}
        icon={(onRetry || onLogin ? icons.homeSurface : icons.homePrimary) || icons.home}
        wide={stacked} palette={palette} /> : null}
    </View> : null}
  </View>;
}

const styles = StyleSheet.create({
  root: { width: '100%', minWidth: 0, textAlign: 'center' },
  hero: { width: '100%', minWidth: 0 },
  statusRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  status: { fontWeight: '700', textAlign: 'center' },
  heading: { marginTop: 16, marginBottom: 8, fontSize: 30, lineHeight: 36, fontWeight: '700', textAlign: 'center' },
  message: { marginBottom: 16, fontSize: 16, lineHeight: 24, textAlign: 'center' },
  csrfReason: { marginBottom: 12, fontSize: 14, lineHeight: 20, textAlign: 'center', color: '#fde68a' },
  sectionCard: { width: '100%', marginBottom: 16, padding: 16, borderRadius: 12, textAlign: 'left' },
  sectionTitle: { marginBottom: 8, fontSize: 16, lineHeight: 24, fontWeight: '500' },
  checkLine: { fontSize: 14, lineHeight: 20 },
  supportCard: {
    width: '100%',
    marginBottom: 16,
    padding: 16,
    textAlign: 'left',
    borderRadius: 12,
    borderWidth: 1,
    borderColor: 'rgba(251, 191, 36, 0.3)',
    backgroundColor: 'rgba(251, 191, 36, 0.1)',
  },
  supportTitle: {
    margin: 0,
    fontSize: 12,
    lineHeight: 16,
    fontWeight: '600',
    letterSpacing: 2.16,
    textTransform: 'uppercase',
    color: 'rgba(253, 230, 138, 0.8)',
  },
  supportBody: { marginTop: 8, fontSize: 14, lineHeight: 24, color: '#fffbeb' },
  supportLink: { flexDirection: 'row', alignItems: 'center', gap: 8, marginTop: 12 },
  supportLinkLabel: { fontSize: 14, lineHeight: 20, fontWeight: '500', color: '#fde68a' },
  bugLine: { marginBottom: 24, fontSize: 14, lineHeight: 20, textAlign: 'center' },
  actionRow: { flexDirection: 'row', flexWrap: 'wrap', justifyContent: 'center', alignItems: 'center', gap: 16 },
  actionColumn: { flexDirection: 'column', alignItems: 'stretch' },
  action: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 8,
    paddingVertical: 12,
    paddingHorizontal: 24,
    borderRadius: 12,
    borderWidth: 0,
  },
  actionLabel: { fontSize: 16, lineHeight: 24, fontWeight: '400' },
});
