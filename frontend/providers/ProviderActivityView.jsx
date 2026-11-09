import React, { useEffect, useRef, useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { ActivityList } from '../ui/controls/ActivityList';
import { Button } from '../ui/Button';
import { Chip } from '../settings/Chip';
import { Dialog } from '../ui/controls/Dialog';
import { Form, useForm } from '../ui/controls/Form';
import { SettingsCard } from '../settings/SettingsCard';

const DEFAULT_PALETTE = {
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
  accentText: '#ffffff',
  danger: '#ef4444',
  success: '#10b981',
  warning: '#f59e0b',
  badgeBorder: '#3f3f46',
  badgeBackground: '#3f3f46',
  badgeText: '#d4d4d8',
  badgeHover: '#52525b',
  radius: 6,
};

const DEFAULT_BUTTON_PALETTE = {
  primary: { background: '#4f46e5', pressed: '#4338ca', hovered: '#4338ca', text: '#ffffff', border: 'transparent' },
  surface: { background: '#3f3f46', pressed: '#52525b', hovered: '#52525b', text: '#fafafa', border: '#3f3f46' },
  'danger-solid': { background: '#dc2626', pressed: '#b91c1c', hovered: '#b91c1c', text: '#ffffff', border: 'transparent' },
  radius: 6,
};

const DEFAULT_LABELS = {
  loading: 'Loading import activity…',
  loadError: 'Could not load import activity.',
  retry: 'Retry',
  schedulesTitle: 'Active Periodic Imports',
  noSchedules: 'No periodic imports configured',
  removeSchedule: 'Remove schedule',
  username: 'Username',
  mode: 'Mode',
  lastImport: 'Last Import',
  nextImport: 'Next Import',
  historyTitle: 'Import History',
  historyWindow: 'Showing import activity from the last 7 days.',
  noHistory: 'No imports in the last 7 days',
  importLabel: 'Import',
  cancelImport: 'Cancel import',
  cancelConfirm: 'Cancel this import?',
  showTraceback: 'Show traceback',
  showDetails: 'Show details',
  copy: 'Copy',
  copied: 'Copied!',
  copyError: 'Could not copy details.',
  previous: 'Previous',
  next: 'Next',
  runsTitle: 'Recent Import Runs',
  runsWindow: 'Counts and undo options for supported imports.',
  created: 'Created',
  updated: 'Updated',
  skipped: 'Skipped',
  failed: 'Failed',
  remaining: 'Remaining',
  undoImport: 'Undo this import',
  removeItemsConfirm: 'Remove the items this import created? This cannot be undone.',
  cleanupTitle: 'Imported Media by Source',
  cleanupWindow: 'Permanently delete everything of a media type imported from this source.',
  deleteAll: 'Delete all',
  deleteAllConfirm: 'Permanently delete all items of this media type imported from AniList? This cannot be undone.',
  detailsTitle: 'Import details',
  close: 'Close',
};

function resolveLabels(defaults, model, labels, t) {
  const translate = typeof t === 'function' ? t : text => model?.labels?.[text] ?? text;
  const translated = {};
  for (const [key, text] of Object.entries(defaults)) translated[key] = translate(text);
  return { ...translated, ...(model?.labels || {}), ...(labels || {}) };
}

function chipPalette(colors, tone) {
  if (tone === 'success') return { ...colors, badgeBorder: colors.success, badgeBackground: 'rgba(16, 185, 129, 0.15)', badgeText: '#a7f3d0' };
  if (tone === 'danger') return { ...colors, badgeBorder: colors.danger, badgeBackground: 'rgba(239, 68, 68, 0.15)', badgeText: '#fecaca' };
  if (tone === 'warning') return { ...colors, badgeBorder: colors.warning, badgeBackground: 'rgba(245, 158, 11, 0.15)', badgeText: '#fde68a' };
  if (tone === 'info') return { ...colors, badgeBorder: colors.accent, badgeBackground: 'rgba(99, 102, 241, 0.15)', badgeText: '#c7d2fe' };
  return colors;
}

function statusTone(status) {
  if (status === 'SUCCESS') return 'success';
  if (status === 'FAILURE') return 'danger';
  if (status === 'STARTED') return 'info';
  return 'neutral';
}

function progressPercent(current, total) {
  if (!total) return 0;
  return Math.max(0, Math.min(100, Math.round((Number(current) / Number(total)) * 100)));
}

function Section({ title, description, colors, children }) {
  return <SettingsCard title={title} palette={colors}>
    {description ? <Text style={[styles.description, { color: colors.textMuted }]}>{description}</Text> : null}
    {children}
  </SettingsCard>;
}

// The universal Form owns transport, so its buttons ask the form context to
// submit instead of relying on browser submit semantics.
function SubmitButton({ label, tone, palette }) {
  const form = useForm();
  return <Button label={label} tone={tone} palette={palette}
    busy={form.isSubmitting} disabled={form.isSubmitting}
    onPress={() => form.submit()} />;
}

/**
 * Universal provider activity tab. The adapter owns the activity request,
 * paging destination, clipboard and form transport; this component only keeps
 * the transient snapshot, polling, expanded-detail and copy-feedback state.
 *
 * onFetch({ page, signal }) -> { schedules, results, hasMore, active, runs, cleanup }
 * onPageChange(nextPage), onCopy(text), onSubmit({ action, csrf, returnTo, values, event }),
 * onConfirm(message) and optional onRetry() are supplied by the platform adapter.
 */
export function ProviderActivityView({
  model = {},
  t,
  labels,
  palette = {},
  buttonPalette = {},
  page: pageProp,
  initialData = null,
  pollInterval = 5000,
  onFetch,
  onPageChange,
  onCopy,
  onSubmit,
  onConfirm,
  onRetry,
}) {
  const colors = { ...DEFAULT_PALETTE, ...palette };
  const buttons = { ...DEFAULT_BUTTON_PALETTE, ...buttonPalette };
  const copy = resolveLabels(DEFAULT_LABELS, model, labels, t);
  const [data, setData] = useState(initialData);
  const [internalPage, setInternalPage] = useState(1);
  const [error, setError] = useState(false);
  const [retry, setRetry] = useState(0);
  const [openDetails, setOpenDetails] = useState(() => new Set());
  const [detail, setDetail] = useState(null);
  const [copied, setCopied] = useState('');
  const copyTimer = useRef(null);
  const onFetchRef = useRef(onFetch);
  onFetchRef.current = onFetch;
  const dataRef = useRef(data);
  dataRef.current = data;
  const page = pageProp ?? internalPage;

  useEffect(() => () => clearTimeout(copyTimer.current), []);

  useEffect(() => {
    if (openDetails.size) return undefined;
    const loader = onFetchRef.current;
    if (typeof loader !== 'function') {
      if (!dataRef.current) setError(true);
      return undefined;
    }
    const controller = new AbortController();
    let timer;
    async function load() {
      try {
        const next = await loader({ page, signal: controller.signal });
        if (controller.signal.aborted) return;
        if (!next) throw new Error('Activity response missing');
        setData(next);
        setError(false);
        if (next.active) timer = setTimeout(load, pollInterval);
      } catch {
        if (!controller.signal.aborted) setError(true);
      }
    }
    load();
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [page, retry, openDetails.size, pollInterval]);

  function changePage(nextPage) {
    if (nextPage < 1) return;
    setData(null);
    setError(false);
    if (pageProp === undefined) setInternalPage(nextPage);
    onPageChange?.(nextPage);
  }

  function retryLoad() {
    setError(false);
    setRetry(value => value + 1);
    onRetry?.();
  }

  function openDetail(result) {
    setOpenDetails(previous => {
      const next = new Set(previous);
      next.add(result.id);
      return next;
    });
    setDetail(result);
  }

  function closeDetail() {
    if (!detail) return;
    const id = detail.id;
    setDetail(null);
    setOpenDetails(previous => {
      const next = new Set(previous);
      next.delete(id);
      return next;
    });
  }

  async function copyDetails(result) {
    try {
      if (typeof onCopy !== 'function') throw new Error('Clipboard adapter missing');
      await onCopy(result.errors);
      setCopied(result.id);
      clearTimeout(copyTimer.current);
      copyTimer.current = setTimeout(() => setCopied(''), 2000);
    } catch {
      setCopied('error');
    }
  }

  const schedules = data?.schedules || [];
  const results = data?.results || [];
  const runs = data?.runs || [];
  const cleanup = data?.cleanup || [];
  const paging = page > 1 || Boolean(data?.hasMore);
  const pagingLocked = openDetails.size > 0;

  return <View testID="provider-activity" style={styles.container}>
    {error ? <View accessibilityRole="alert" style={[styles.alert, { borderColor: colors.danger }]}>
      <Text style={[styles.copy, { color: colors.textSecondary }]}>{copy.loadError}</Text>
      <Button label={copy.retry} tone="surface" onPress={retryLoad} palette={buttons} />
    </View> : null}
    {!data && !error ? <Text accessibilityLiveRegion="polite" style={[styles.copy, { color: colors.textMuted }]}>
      {copy.loading}
    </Text> : null}

    {data ? <>
      <Section title={copy.schedulesTitle} colors={colors}>
        {schedules.length ? <ActivityList palette={colors}>
          {schedules.map((schedule, index) => <View key={schedule.id}
            style={[styles.row, index > 0 && { borderTopWidth: 1, borderTopColor: colors.border }]}>
            <View style={styles.rowHeading}>
              <Text style={[styles.rowTitle, { color: colors.text }]}>{schedule.schedule}</Text>
              <Form key={schedule.name} action={schedule.action} csrf={model.csrf} returnTo={model.next}
                defaultValues={{ task_name: schedule.name }}
                onSubmit={onSubmit} onConfirm={onConfirm}>
                <SubmitButton label={copy.removeSchedule} tone="danger-solid" palette={buttons} />
              </Form>
            </View>
            {schedule.username ? <Text style={[styles.copy, { color: colors.textSecondary }]}>
              {copy.username}: {schedule.username}
            </Text> : null}
            <Text style={[styles.copy, { color: colors.textMuted }]}>{copy.mode}: {schedule.mode}</Text>
            <Text style={[styles.copy, { color: colors.textMuted }]}>{copy.lastImport}: {schedule.lastRun || '—'}</Text>
            <Text style={[styles.copy, { color: colors.textMuted }]}>{copy.nextImport}: {schedule.nextRun || '—'}</Text>
          </View>)}
        </ActivityList> : <Text style={[styles.copy, { color: colors.textMuted }]}>{copy.noSchedules}</Text>}
      </Section>

      <Section title={copy.historyTitle} description={copy.historyWindow} colors={colors}>
        {results.length ? <ActivityList palette={colors}>
          {results.map((result, index) => <View key={result.id}
            style={[styles.row, index > 0 && { borderTopWidth: 1, borderTopColor: colors.border }]}>
            <View style={styles.rowHeading}>
              <Chip label={result.statusLabel} palette={chipPalette(colors, statusTone(result.status))} />
              <Text style={[styles.meta, { color: colors.textSecondary }]}>{result.date}</Text>
            </View>
            {result.summary ? <Text style={[styles.copy, { color: colors.textSecondary }]}>{result.summary}</Text> : null}
            {result.status === 'STARTED' && result.current != null ? <View style={styles.progressBlock}>
              <Text style={[styles.copy, { color: colors.textMuted }]}>
                {result.progressLabel || copy.importLabel}: {result.current}{result.total ? ` / ${result.total}` : ''}
              </Text>
              {result.total ? <View accessibilityRole="progressbar"
                accessibilityLabel={result.progressLabel || copy.importLabel}
                accessibilityValue={{ min: 0, max: Number(result.total), now: Number(result.current) }}
                style={[styles.progressTrack, { backgroundColor: colors.surfaceStrong }]}>
                <View style={[styles.progressFill, {
                  backgroundColor: colors.accent,
                  width: `${progressPercent(result.current, result.total)}%`,
                }]} />
              </View> : null}
            </View> : null}
            {result.cancelAction ? <Form action={result.cancelAction} csrf={model.csrf} returnTo={model.next}
              confirm={copy.cancelConfirm} onSubmit={onSubmit} onConfirm={onConfirm}>
              <SubmitButton label={copy.cancelImport} tone="danger-solid" palette={buttons} />
            </Form> : null}
            {result.errors ? <View style={styles.actions}>
              <Button label={result.status === 'FAILURE' ? copy.showTraceback : copy.showDetails}
                tone="surface" onPress={() => openDetail(result)} palette={buttons} />
            </View> : null}
          </View>)}
        </ActivityList> : <Text style={[styles.copy, { color: colors.textMuted }]}>{copy.noHistory}</Text>}
        {copied === 'error' ? <Text accessibilityRole="alert" style={[styles.copy, { color: colors.danger }]}>
          {copy.copyError}
        </Text> : null}
        {paging ? <View style={styles.pagination}>
          <Button label={copy.previous} tone="surface"
            disabled={page === 1 || pagingLocked} onPress={() => changePage(page - 1)} palette={buttons} />
          <Text style={[styles.pageLabel, { color: colors.textSecondary }]}>{page}</Text>
          <Button label={copy.next} tone="surface"
            disabled={!data.hasMore || pagingLocked} onPress={() => changePage(page + 1)} palette={buttons} />
        </View> : null}
      </Section>

      {runs.length ? <Section title={copy.runsTitle} description={copy.runsWindow} colors={colors}>
        <ActivityList palette={colors}>
          {runs.map((run, index) => <View key={run.id}
            style={[styles.row, index > 0 && { borderTopWidth: 1, borderTopColor: colors.border }]}>
            <View style={styles.rowHeading}>
              <Chip label={run.statusLabel} palette={chipPalette(colors, statusTone(run.status))} />
              <Text style={[styles.meta, { color: colors.textSecondary }]}>{run.date}</Text>
            </View>
            <Text style={[styles.copy, { color: colors.textMuted }]}>
              {copy.created}: {run.created} · {copy.updated}: {run.updated} · {copy.skipped}: {run.skipped} · {copy.failed}: {run.failed}
              {run.remaining != null ? ` · ${copy.remaining}: ${run.remaining}` : ''}
            </Text>
            <Form action={run.action} csrf={model.csrf} returnTo={model.next}
              confirm={run.status === 'running' ? copy.cancelConfirm : copy.removeItemsConfirm}
              onSubmit={onSubmit} onConfirm={onConfirm}>
              <SubmitButton label={run.status === 'running' ? copy.cancelImport : copy.undoImport}
                tone="danger-solid" palette={buttons} />
            </Form>
          </View>)}
        </ActivityList>
      </Section> : null}

      {cleanup.length ? <Section title={copy.cleanupTitle} description={copy.cleanupWindow} colors={colors}>
        <ActivityList palette={colors}>
          {cleanup.map((row, index) => <View key={row.mediaType}
            style={[styles.cleanupRow, index > 0 && { borderTopWidth: 1, borderTopColor: colors.border }]}>
            <Text style={[styles.copy, { color: colors.textSecondary }]}>{row.mediaLabel} · {row.count}</Text>
            <Form action={row.action} csrf={model.csrf} returnTo={model.next}
              confirm={copy.deleteAllConfirm} onSubmit={onSubmit} onConfirm={onConfirm}>
              <SubmitButton label={copy.deleteAll} tone="danger-solid" palette={buttons} />
            </Form>
          </View>)}
        </ActivityList>
      </Section> : null}
    </> : null}

    <Dialog open={Boolean(detail)} title={detail?.statusLabel || copy.detailsTitle}
      closeLabel={copy.close} onClose={closeDetail} palette={colors}
      actions={detail ? [
        <Button key="copy" label={copied === detail.id ? copy.copied : copy.copy} tone="surface"
          onPress={() => copyDetails(detail)} palette={buttons} />,
        <Button key="close" label={copy.close} onPress={closeDetail} palette={buttons} />,
      ] : null}>
      {detail?.errors ? <Text selectable style={[styles.errorText, { color: colors.textSecondary }]}>
        {detail.errors}
      </Text> : null}
      {copied === 'error' ? <Text accessibilityRole="alert" style={[styles.copy, { color: colors.danger }]}>
        {copy.copyError}
      </Text> : null}
    </Dialog>
  </View>;
}

const styles = StyleSheet.create({
  container: { gap: 12 },
  alert: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', gap: 8, borderWidth: 1, borderRadius: 8, padding: 12 },
  description: { fontSize: 12, lineHeight: 17 },
  copy: { fontSize: 12, lineHeight: 17 },
  meta: { fontSize: 12, lineHeight: 17 },
  row: { gap: 4, paddingVertical: 10, paddingHorizontal: 4 },
  rowHeading: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 8 },
  rowTitle: { flexShrink: 1, fontSize: 14, fontWeight: '600' },
  progressBlock: { gap: 4, paddingTop: 2 },
  progressTrack: { height: 6, borderRadius: 3, overflow: 'hidden' },
  progressFill: { height: 6 },
  actions: { flexDirection: 'row', flexWrap: 'wrap', gap: 8, paddingTop: 2 },
  pagination: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 12, paddingTop: 4 },
  pageLabel: { fontSize: 12 },
  cleanupRow: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', justifyContent: 'space-between', gap: 8, paddingVertical: 10, paddingHorizontal: 4 },
  errorText: { fontSize: 12, lineHeight: 18 },
});
