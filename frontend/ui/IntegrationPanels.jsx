import React, { useEffect, useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { SettingsCard } from '../settings/SettingsCard';
import { Badge } from './Badge';
import { Button } from './Button';
import { BulkActionDialog } from './BulkActions';

const FALLBACK_PALETTE = {
  background: '#18181b',
  surface: '#27272a',
  surfaceStrong: '#3f3f46',
  surfaceMuted: '#52525b',
  border: '#3f3f46',
  text: '#fafafa',
  textSecondary: '#d4d4d8',
  textMuted: '#a1a1aa',
  accent: '#6366f1',
  accentStrong: '#4f46e5',
  success: '#10b981',
  warning: '#f59e0b',
  danger: '#ef4444',
  overlay: 'rgba(0, 0, 0, 0.6)',
  radius: 10,
  focusStyle: {},
};

const FALLBACK_LABELS = {
  requests: 'Requests',
  notRequested: 'Not requested in Seerr.',
  requestInSeerr: 'Request in Seerr',
  searchNow: 'Search now',
  copy: 'Copy',
  copied: 'Copied',
  activity: 'Activity',
  hasFile: 'Has file',
  downloading: 'Downloading',
  missing: 'Missing',
  notMonitored: 'Not monitored',
  episodesHaveFiles: '%s of %s episodes have files',
  added: 'Added %s',
  request: 'Request',
  requestAll: 'Request all missing seasons',
  requestTitle: 'Request in Seerr',
  status: 'Status',
  openSeerr: 'Open in Seerr',
  close: 'Close',
  requesting: 'Requesting',
  available: 'Available',
  partially_available: 'Partially available',
  processing: 'Processing',
  pending: 'Requested',
  blocklisted: 'Blocklisted',
  unknown: 'Not requested',
  noLibraryPanels: 'No Radarr or Sonarr instances have this title.',
  openIn: 'Open in %s',
  notFound: 'Not in %s',
};

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

function mergePalette(palette) {
  return { ...FALLBACK_PALETTE, ...(palette || {}) };
}

function mergeLabels(labels) {
  return { ...FALLBACK_LABELS, ...(labels || {}) };
}

function settingsPalette(colors) {
  return {
    border: colors.border,
    background: colors.surface,
    text: colors.text,
    fontFamily: undefined,
  };
}

function buttonPalette(colors) {
  return {
    primary: { background: colors.accentStrong, pressed: colors.accentStrong, hovered: colors.accentStrong, text: '#ffffff', border: 'transparent' },
    surface: { background: colors.surfaceStrong, pressed: colors.surfaceMuted, hovered: colors.surfaceMuted, text: colors.text, border: colors.border },
    radius: colors.radius,
    focusStyle: colors.focusStyle,
  };
}

function badgePalette(colors, tone, variant) {
  const color = {
    success: colors.success,
    info: colors.accent,
    warning: colors.warning,
    danger: colors.danger,
    neutral: colors.textMuted,
  }[tone] || colors.textMuted;
  // The web track modal draws status pills with a neutral border and toned text.
  return { outline: { color, borderColor: variant === 'web' ? colors.border : color, borderWidth: 1 } };
}

function toDate(value) {
  if (value instanceof Date) return value;
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

function formatDate(value) {
  const date = toDate(value);
  if (!date) return '';
  return `${MONTHS[date.getMonth()]} ${date.getDate()}, ${date.getFullYear()}`;
}

function formatShortDate(value) {
  const date = toDate(value);
  return date ? `${MONTHS[date.getMonth()]} ${date.getDate()}` : '';
}

function formatDateTime(value) {
  const date = toDate(value);
  if (!date) return '';
  return `${formatDate(date)}, ${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`;
}

function formatSize(value) {
  const size = Number(value);
  if (!Number.isFinite(size) || size <= 0) return '';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let amount = size;
  let index = 0;
  while (amount >= 1024 && index < units.length - 1) {
    amount /= 1024;
    index += 1;
  }
  // One decimal, like the server's filesizeformat ("48.4 GB").
  return index === 0 ? `${size} ${units[0]}` : `${amount.toFixed(1)} ${units[index]}`;
}

function OpenLink({ url, app, colors, copy, linkProps, onOpenUrl }) {
  if (!url) return null;
  const label = copy.openIn.replace('%s', app);
  // linkProps lets each platform decide how a link opens (the web adapter
  // renders a real anchor; native passes onOpenUrl to the system browser).
  return <Pressable accessibilityRole="link" accessibilityLabel={label}
    {...(linkProps?.(url) || {})} onPress={onOpenUrl ? () => onOpenUrl(url) : undefined}>
    {({ hovered }) => <Text style={[styles.linkText, { color: colors.link || colors.accent },
      hovered && styles.linkHovered]}>{label}</Text>}
  </Pressable>;
}

// Native groups each server in a SettingsCard; the web variant keeps the flat,
// divided sections the server-rendered track modal has always shown.
function PanelSection({ title, headerAction, colors, variant, first, compact = false, children }) {
  if (variant !== 'web') {
    return <SettingsCard title={title} headerAction={headerAction} palette={settingsPalette(colors)}>
      {children}
    </SettingsCard>;
  }
  return <View style={[styles.webSection, compact && styles.webSectionCompact, !first && { borderTopWidth: 1, borderTopColor: colors.border }]}>
    <View style={styles.webHeading}>
      <Text role="heading" aria-level={3} numberOfLines={1}
        style={[styles.webTitle, { color: colors.textMuted }]}>{title}</Text>
      {headerAction}
    </View>
    {children}
  </View>;
}

function arrStatus(status, labels) {
  if (status === 'has_file') return { label: labels.hasFile, tone: 'success' };
  if (status === 'downloading') return { label: labels.downloading, tone: 'info' };
  return { label: labels.missing, tone: 'warning' };
}

function seerrStatus(status, labels) {
  const label = labels[status] || labels.unknown;
  const tone = {
    available: 'success',
    partially_available: 'warning',
    processing: 'info',
    pending: 'warning',
    blocklisted: 'danger',
  }[status] || 'neutral';
  return { label, tone };
}

function StatusBadge({ label, tone, colors, variant }) {
  return <Badge label={label} size="sm" tone="outline" palette={badgePalette(colors, tone, variant)} />;
}

function SearchButton({ label, colors, variant, onPress }) {
  if (variant !== 'web') {
    return <Button label={label} tone="surface" size="sm" palette={buttonPalette(colors)} onPress={onPress} />;
  }
  // Matches the compact bordered button the web panel has always used.
  return <Pressable accessibilityRole="button" onPress={onPress}>
    {({ hovered }) => <View style={[styles.webButton, {
      borderRadius: colors.radius, borderColor: colors.border, backgroundColor: hovered ? colors.surfaceMuted : colors.surface,
    }]}><Text style={[styles.webButtonText, { color: colors.text }]}>{label}</Text></View>}
  </Pressable>;
}

function CopyPathRow({ path, colors, copy, variant, onCopy }) {
  const [copied, setCopied] = useState(false);
  useEffect(() => {
    if (!copied) return undefined;
    const timer = setTimeout(() => setCopied(false), 1500);
    return () => clearTimeout(timer);
  }, [copied]);
  function copyPath() {
    onCopy?.(path);
    setCopied(true);
  }
  const web = variant === 'web';
  return <View style={[styles.pathRow, web && [styles.webPathRow, { borderRadius: colors.radius }], { backgroundColor: colors.background }]}>
    <Text numberOfLines={1} style={[styles.pathText, variant === 'web' && styles.webMono, { color: colors.textSecondary }]}>{path}</Text>
    <Pressable accessibilityRole="button" accessibilityLabel={copied ? copy.copied : copy.copy}
      onPress={copyPath} style={styles.copyButton}>
      <Text style={[styles.copyText, web && styles.webCopyText, { color: colors.textMuted }]}>{copied ? copy.copied : copy.copy}</Text>
    </Pressable>
  </View>;
}

function DownloadRow({ download, colors }) {
  const percent = Math.max(0, Math.min(100, Number(download.percent) || 0));
  return <View style={styles.download}>
    <View style={styles.downloadHead}>
      <Text numberOfLines={1} style={[styles.downloadTitle, { color: colors.textSecondary }]}>{download.title}</Text>
      <Text style={[styles.downloadMeta, { color: colors.accent }]}>
        {percent}%{download.timeleft ? ` · ${download.timeleft}` : ''}
      </Text>
    </View>
    <View accessible accessibilityRole="progressbar"
      accessibilityLabel={`${download.title} ${percent}%`}
      accessibilityValue={{ min: 0, max: 100, now: percent }}
      style={[styles.progressTrack, { backgroundColor: colors.surfaceMuted }]}>
      <View style={[styles.progressFill, { width: `${percent}%`, backgroundColor: colors.accent }]} />
    </View>
  </View>;
}

function HistoryList({ history, colors, copy, variant }) {
  const [expanded, setExpanded] = useState(false);
  if (!history.length) return null;
  const first = history[0];
  return <View>
    <Pressable accessibilityRole="button" accessibilityState={{ expanded }}
      accessibilityLabel={`${copy.activity} (${history.length})`}
      onPress={() => setExpanded(current => !current)} style={[styles.historyToggle, variant === 'web' && styles.webHistoryToggle]}>
      {variant === 'web' ? <Text style={[styles.historyToggleText, { color: colors.textMuted }]}>
        <Text style={styles.webMarker}>{expanded ? '▼ ' : '▶ '}</Text>
        {copy.activity} ({history.length})
        <Text style={{ color: colors.textSecondary }}>{`  · ${first.label} ${formatShortDate(first.when)}`}</Text>
      </Text> : <Text style={[styles.historyToggleText, { color: colors.textMuted }]}>
        {copy.activity} ({history.length}) · {first.label} {formatDate(first.when)}
      </Text>}
    </Pressable>
    {expanded ? <View style={styles.historyRows}>
      {history.map((event, index) => {
        const tone = { ok: colors.success, bad: colors.danger, warn: colors.warning }[event.tone] || colors.accent;
        const detail = [event.quality, event.detail].filter(Boolean).join(' · ');
        return <View key={`${event.when || index}-${index}`} style={styles.historyRow}>
          <Text style={[styles.historyWhen, { color: colors.textMuted }]}>{formatDateTime(event.when)}</Text>
          <Text style={[styles.historyLabel, { color: tone }]}>{event.label}</Text>
          {detail ? <Text numberOfLines={1} style={[styles.historyDetail, { color: colors.textSecondary }]}>{detail}</Text> : null}
        </View>;
      })}
    </View> : null}
  </View>;
}

function ArrPanel({ panel, colors, copy, variant, first, onSearch, onCopy, linkProps, onOpenUrl }) {
  const status = arrStatus(panel.status, copy);
  const absent = panel.status === 'absent';
  const link = <OpenLink url={panel.url} app={panel.app} colors={colors} copy={copy}
    linkProps={linkProps} onOpenUrl={onOpenUrl} />;
  const headerAction = panel.error
    ? <Text accessibilityLiveRegion="assertive" style={[styles.headerError, { color: colors.danger }]}>{panel.error}</Text>
    : absent ? <View style={styles.headerActions}>
      <Text style={[styles.headerNote, { color: colors.textMuted }]}>{copy.notFound.replace('%s', panel.app)}</Text>
      {link}
    </View> : <View style={styles.headerActions}>
      {link}
      <StatusBadge label={status.label} tone={status.tone} colors={colors} variant={variant} />
      {panel.search ? <SearchButton label={copy.searchNow} colors={colors} variant={variant}
        onPress={() => onSearch?.(panel)} /> : null}
    </View>;
  const summary = Array.isArray(panel.summary)
    ? copy.episodesHaveFiles.replace('%s', panel.summary[0]).replace('%s', panel.summary[1])
    : '';
  const details = [
    summary,
    panel.quality,
    formatSize(panel.size),
    panel.added ? copy.added.replace('%s', formatDate(panel.added)) : '',
    panel.monitored === false ? copy.notMonitored : '',
  ].filter(Boolean).join(' · ');
  const title = panel.name && panel.name !== panel.app ? `${panel.app} · ${panel.name}` : panel.app;
  return <PanelSection title={title} headerAction={headerAction} colors={colors} variant={variant} first={first}>
    {panel.error || absent ? null : <>
      {details ? <Text style={[styles.detailText, variant === 'web' && styles.webText, { color: colors.textSecondary }]}>{details}</Text> : null}
      {panel.path ? <CopyPathRow path={panel.path} colors={colors} copy={copy} variant={variant} onCopy={onCopy} /> : null}
      {(panel.queue || []).map((download, index) => <DownloadRow key={`${download.title}-${index}`} download={download} colors={colors} />)}
      <HistoryList history={panel.history || []} colors={colors} copy={copy} variant={variant} />
    </>}
  </PanelSection>;
}

export function ArrLibraryPanels({
  panels = [],
  message = '',
  error = '',
  seerrRequests,
  seerrError = '',
  seerrUrl = '',
  labels,
  palette,
  variant = 'native',
  onSearch,
  onCopy,
  onOpenRequest,
  linkProps,
  onOpenUrl,
  emptyLabel,
}) {
  const colors = mergePalette(palette);
  const copy = mergeLabels(labels);
  const showRequests = seerrRequests !== undefined || Boolean(seerrError);
  const showEmpty = Boolean(emptyLabel) && !panels.length && !showRequests && !message && !error;
  const web = variant === 'web';
  return <View style={web ? null : styles.stack}>
    {message ? <Text accessibilityLiveRegion="polite" style={[styles.feedback, web && styles.webFeedback, { color: colors.success }]}>{message}</Text> : null}
    {error ? <Text accessibilityLiveRegion="assertive" style={[styles.feedback, web && styles.webFeedback, { color: colors.danger }]}>{error}</Text> : null}
    {panels.map((panel, index) => <ArrPanel key={panel.instance_id || `${panel.app}-${panel.name}-${index}`}
      panel={panel} colors={colors} copy={copy} variant={variant} first={index === 0}
      onSearch={onSearch} onCopy={onCopy} linkProps={linkProps} onOpenUrl={onOpenUrl} />)}
    {showRequests ? <SeerrRequestsCard requests={seerrRequests || []} error={seerrError}
      seerrUrl={seerrUrl} labels={copy} palette={colors} variant={variant} first={!panels.length}
      onOpenRequest={onOpenRequest} linkProps={linkProps} onOpenUrl={onOpenUrl} /> : null}
    {showEmpty ? <Text style={[styles.detailText, { color: colors.textMuted }]}>{emptyLabel}</Text> : null}
  </View>;
}

export function SeerrRequestsCard({
  requests = [], error = '', seerrUrl = '', labels, palette, variant = 'native', first = true,
  onOpenRequest, linkProps, onOpenUrl,
}) {
  const colors = mergePalette(palette);
  const copy = mergeLabels(labels);
  const link = <OpenLink url={seerrUrl} app="Seerr" colors={colors} copy={copy}
    linkProps={linkProps} onOpenUrl={onOpenUrl} />;
  const headerAction = seerrUrl || onOpenRequest ? <View style={styles.headerActions}>
    {link}
    {onOpenRequest ? <Button label={copy.requestInSeerr} tone="surface" size="sm"
      palette={buttonPalette(colors)} onPress={onOpenRequest} /> : null}
  </View> : null;
  return <PanelSection title={copy.requests} colors={colors} variant={variant} first={first} compact
    headerAction={headerAction}>
    {error ? <Text accessibilityLiveRegion="assertive" style={[styles.errorText, { color: colors.danger }]}>{error}</Text>
      : requests.length ? <View style={[styles.requestRows, variant === 'web' && styles.webRequestRows]}>
        {requests.map((request, index) => <View key={`${request.by}-${request.created || index}`} style={styles.requestRow}>
          <Text numberOfLines={1} style={[styles.requestBy, variant === 'web' && styles.webRequestBy, { color: colors.textSecondary }]}>{request.by || '-'}</Text>
          <Text style={[styles.requestWhen, variant === 'web' && styles.webRequestWhen, { color: colors.textMuted }]}>{formatDate(request.when || request.created)}</Text>
          <View style={variant === 'web' ? styles.webPushEnd : null}><StatusBadge label={request.status} tone="neutral" colors={colors} variant={variant} /></View>
        </View>)}
      </View> : <Text style={[styles.detailText, variant === 'web' && styles.webText, { color: colors.textMuted }]}>{copy.notRequested}</Text>}
  </PanelSection>;
}

export function SeerrStatusBadge({ status, labels, palette }) {
  const colors = mergePalette(palette);
  const copy = mergeLabels(labels);
  const view = seerrStatus(status, copy);
  return <StatusBadge label={view.label} tone={view.tone} colors={colors} />;
}

export function SeerrRequestDialog({
  open = false,
  summary,
  error = '',
  labels,
  palette,
  busy = false,
  busySeason = null,
  onRequestSeason,
  onRequestAll,
  onOpenSeerr,
  onClose,
}) {
  const colors = mergePalette(palette);
  const copy = mergeLabels(labels);
  const seasons = summary?.seasons || [];
  const confirmLabel = seasons.length ? copy.requestAll : copy.request;
  return <BulkActionDialog open={open} title={copy.requestTitle} confirmLabel={confirmLabel}
    cancelLabel={copy.close} labels={{ close: copy.close, cancelAction: copy.close }}
    busy={busy} confirmDisabled={!summary?.requestable}
    palette={colors} onConfirm={onRequestAll} onClose={onClose}>
    <View style={styles.stack}>
      {error ? <Text accessibilityLiveRegion="assertive" style={[styles.errorText, { color: colors.danger }]}>{error}</Text> : null}
      {summary ? seasons.length ? seasons.map(season => <View key={season.number} style={[styles.seasonRow, { backgroundColor: colors.background }]}>
        <Text numberOfLines={1} style={[styles.seasonName, { color: colors.text }]}>{season.name}</Text>
        {season.requestable ? <Button label={busySeason === season.number ? copy.requesting : copy.request}
          size="sm" disabled={busy} busy={busySeason === season.number} palette={buttonPalette(colors)}
          onPress={() => onRequestSeason?.(season.number)} />
          : <SeerrStatusBadge status={season.status} labels={copy} palette={colors} />}
      </View>) : <View style={styles.movieStatus}>
        <Text style={[styles.detailText, { color: colors.textSecondary }]}>{copy.status}</Text>
        <SeerrStatusBadge status={summary.status} labels={copy} palette={colors} />
      </View> : null}
      {onOpenSeerr ? <Button label={copy.openSeerr} tone="surface" palette={buttonPalette(colors)} onPress={onOpenSeerr} /> : null}
    </View>
  </BulkActionDialog>;
}

const styles = StyleSheet.create({
  stack: { gap: 12 },
  feedback: { fontSize: 13, lineHeight: 18 },
  errorText: { fontSize: 13, lineHeight: 18 },
  detailText: { fontSize: 13, lineHeight: 18 },
  webSection: { paddingVertical: 12, gap: 8 },
  webSectionCompact: { gap: 4 },
  webHeading: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 12 },
  webTitle: { flexShrink: 1, fontSize: 14, lineHeight: 20, fontWeight: '600', textTransform: 'uppercase', letterSpacing: 0.35 },
  webPathRow: { paddingVertical: 4 },
  webCopyText: { fontSize: 12, fontWeight: '400' },
  webHistoryToggle: { paddingVertical: 0 },
  webMarker: { fontSize: 9 },
  webText: { fontSize: 14, lineHeight: 20 },
  webMono: { fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace', fontSize: 12, lineHeight: 16 },
  webButton: { borderWidth: 1, paddingHorizontal: 12, paddingVertical: 4 },
  webButtonText: { fontSize: 12, lineHeight: 16 },
  webRequestRows: { gap: 4 },
  webRequestBy: { fontSize: 14, lineHeight: 20, minWidth: 0 },
  webRequestWhen: { fontSize: 12, lineHeight: 16 },
  webPushEnd: { marginLeft: 'auto' },
  webFeedback: { paddingBottom: 8, fontSize: 14, lineHeight: 20 },
  headerError: { fontSize: 12, lineHeight: 16 },
  headerNote: { fontSize: 12, lineHeight: 16 },
  linkText: { fontSize: 12, lineHeight: 16 },
  linkHovered: { textDecorationLine: 'underline' },
  headerActions: { flexDirection: 'row', alignItems: 'center', gap: 8, flexWrap: 'wrap', justifyContent: 'flex-end' },
  pathRow: { flexDirection: 'row', alignItems: 'center', gap: 8, borderRadius: 6, paddingHorizontal: 8, paddingVertical: 6 },
  pathText: { flex: 1, fontSize: 11 },
  copyButton: { paddingVertical: 2, paddingHorizontal: 4 },
  copyText: { fontSize: 11, fontWeight: '600' },
  download: { gap: 4 },
  downloadHead: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 8 },
  downloadTitle: { flex: 1, fontSize: 12 },
  downloadMeta: { fontSize: 12 },
  progressTrack: { height: 4, borderRadius: 2, overflow: 'hidden' },
  progressFill: { height: '100%' },
  historyToggle: { alignSelf: 'flex-start', paddingVertical: 2 },
  historyToggleText: { fontSize: 12 },
  historyRows: { gap: 4, marginTop: 4 },
  historyRow: { flexDirection: 'row', alignItems: 'baseline', gap: 8, flexWrap: 'wrap' },
  historyWhen: { fontSize: 11, minWidth: 86 },
  historyLabel: { fontSize: 11, fontWeight: '600', minWidth: 68 },
  historyDetail: { fontSize: 11, flexShrink: 1 },
  requestRows: { gap: 6 },
  requestRow: { flexDirection: 'row', alignItems: 'center', gap: 8, flexWrap: 'wrap' },
  requestBy: { fontSize: 13, minWidth: 72 },
  requestWhen: { fontSize: 11 },
  seasonRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 8, borderRadius: 6, paddingHorizontal: 10, paddingVertical: 8 },
  seasonName: { flex: 1, fontSize: 13 },
  movieStatus: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 8 },
});
