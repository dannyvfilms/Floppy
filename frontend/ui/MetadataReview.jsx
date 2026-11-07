import React, { useMemo, useState } from 'react';
import { Image, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { Button } from './Button';
import { SelectField } from './SelectField';
import { TextField } from './TextField';

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
  accentText: '#ffffff',
  success: '#34d399',
  successSoft: 'rgba(52, 211, 153, 0.2)',
  warning: '#fbbf24',
  warningSoft: 'rgba(251, 191, 36, 0.2)',
  accentSoft: 'rgba(99, 102, 241, 0.2)',
  danger: '#f87171',
  dangerSoft: 'rgba(248, 113, 113, 0.2)',
  overlay: 'rgba(0, 0, 0, 0.6)',
  radius: 8,
  focusStyle: {},
};

const DEFAULT_LABELS = {
  title: 'Episode ordering',
  lead: 'Choose how this series is numbered in your library. Your viewing history is reviewed before anything changes.',
  currentOrder: 'Current order:',
  originalNumbering: 'Original numbering',
  matched: 'Matched',
  suggested: 'Suggested',
  needs: 'Needs choice',
  chosen: 'Chosen',
  archived: 'Archived',
  combined: 'Combined',
  current: 'Current',
  reviewChanges: 'Review changes',
  undo: 'Undo ordering change',
  revertHelp: 'The order before the latest change.',
  revertBlocked: "Can't be restored automatically because viewings were added or edited after the change.",
  noOrders: 'No episode orders are available. Configure a provider credential and a verified series provider identity in metadata settings.',
  allViewings: 'All viewings',
  needsChoice: 'Needs choice',
  acceptAll: 'Accept all suggestions',
  suggestionWarning: 'Some suggestions only share a season and episode number with the old episode. Split or merged episodes shift later numbers, so check them before accepting.',
  movingTo: 'Moving to the selected order',
  reviewHelp: 'Pick the episode each viewing belongs to under the new numbering. Matches by identity, air date and title are filled in for you; check anything marked Suggested or Needs choice.',
  noDate: 'No date',
  emptyViewings: 'This series has no viewings to move.',
  score: 'Score:',
  removeEpisode: 'Remove episode',
  chooseEpisode: 'Choose episode',
  addOrChange: 'Add or change',
  useSuggestion: 'Use suggestion:',
  options: 'Options',
  archiveLabel: 'Archive under the original order, excluding it from active progress',
  combineLabel: 'Combine with another viewing and use its episode, dates, score, notes and status',
  keepSeparate: 'Keep as a separate viewing',
  searchPlaceholder: 'Search by number, title or air date',
  apply: 'Apply episode ordering',
  cancel: 'Cancel',
  needsRemaining: 'viewings still need an episode, or can be archived.',
  combinedUses: 'Uses the episode, dates, score and status of',
  archiveNote: 'Kept under the original order and left out of active progress.',
  moveTracking: 'Move tracking',
  confirmation: 'Confirm the move',
  moveCopy: 'Moving keeps your status, ratings, notes and every watched episode, and only changes which provider supplies its seasons and episodes.',
  matchedOn: 'Matched on',
  trackedSeasons: 'Tracked seasons',
  watchedEpisodes: 'Watched episodes',
  missingTitle: 'The destination is missing some of what you track, so this show cannot be moved yet.',
  missing: 'Missing:',
  moveTo: 'Move',
  back: 'Back',
  useMatch: 'Use this match',
  noMatches: 'No matches found. Try a different search.',
  moveIntro: 'Confirm the exact title before moving your tracking identity.',
  moving: 'Moving...',
  saving: 'Saving...',
  loading: 'Reading the match results...',
  error: 'The change could not be completed.',
};

function mergePalette(palette) {
  return { ...FALLBACK_PALETTE, ...(palette || {}) };
}

function mergeLabels(labels) {
  return { ...DEFAULT_LABELS, ...(labels || {}) };
}

function statusTone(key, palette) {
  if (key === 'matched' || key === 'chosen') {
    return { backgroundColor: palette.successSoft, borderColor: palette.success, color: palette.text };
  }
  if (key === 'suggested') {
    return { backgroundColor: palette.accentSoft, borderColor: palette.accent, color: palette.text };
  }
  if (key === 'needs') {
    return { backgroundColor: palette.warningSoft, borderColor: palette.warning, color: palette.text };
  }
  return { backgroundColor: palette.surface, borderColor: palette.border, color: palette.textMuted };
}

function StatusPill({ label, tone, palette }) {
  const appearance = statusTone(tone, palette);
  return <View style={[styles.pill, { backgroundColor: appearance.backgroundColor, borderColor: appearance.borderColor }]}>
    <Text numberOfLines={1} style={[styles.pillText, { color: appearance.color }]}>{label}</Text>
  </View>;
}

function Warning({ children, palette, alert = false }) {
  return <View accessibilityRole={alert ? 'alert' : undefined}
    style={[styles.warning, { borderColor: palette.warning, backgroundColor: palette.warningSoft }]}>
    <Text style={[styles.warningText, { color: palette.textSecondary }]}>{children}</Text>
  </View>;
}

function SectionHeading({ children, palette, level = 2 }) {
  return <Text accessibilityRole="header" aria-level={level} style={[styles.heading, { color: palette.text }]}>
    {children}
  </Text>;
}

function buttonPalette(palette) {
  return {
    primary: {
      background: palette.accentStrong,
      pressed: palette.accent,
      hovered: palette.accent,
      text: palette.accentText,
      border: palette.accentStrong,
    },
    surface: {
      background: palette.surface,
      pressed: palette.surfaceMuted,
      hovered: palette.surfaceMuted,
      text: palette.text,
      border: palette.border,
    },
    'ghost-danger': {
      background: 'transparent',
      pressed: palette.dangerSoft,
      hovered: palette.dangerSoft,
      text: palette.danger,
      border: 'transparent',
    },
    radius: palette.radius,
    focusStyle: palette.focusStyle,
  };
}

function choiceRows(watches) {
  const rows = {};
  (watches || []).forEach(watch => {
    rows[String(watch.id)] = {
      ...watch,
      selected: [...(watch.selected || [])],
      pending: watch.pending || null,
      kind: watch.kind || 'needs',
      archive: Boolean(watch.archive),
      combine: watch.combine ? String(watch.combine) : String(watch.id),
      touched: false,
    };
  });
  return rows;
}

function isCombined(row) {
  return String(row.combine) !== String(row.id);
}

function hasFollowers(rows, id) {
  const own = String(id);
  return Object.keys(rows).some(other => other !== own && String(rows[other].combine) === own);
}

function canArchive(rows, id) {
  const row = rows[String(id)];
  return row && !isCombined(row) && !hasFollowers(rows, id);
}

function combineTargets(rows, id) {
  const own = String(id);
  if (hasFollowers(rows, id)) return [];
  return Object.keys(rows).filter(other => other !== own
    && !isCombined(rows[other])
    && !rows[other].archive);
}

function statusKey(row, rows) {
  if (row.archive) return 'archived';
  if (isCombined(row)) return 'combined';
  if (!row.selected.length) return row.pending ? 'suggested' : 'needs';
  return row.touched ? 'chosen' : row.kind;
}

function WatchRow({
  watch,
  rows,
  setRows,
  labels,
  palette,
  openPicker,
  setOpenPicker,
  query,
  setQuery,
  openOptions,
  setOpenOptions,
  episodes,
}) {
  const row = rows[String(watch.id)];
  const combined = isCombined(row);
  const combinedLabel = combined ? rows[String(row.combine)]?.label : '';
  const archiveAllowed = canArchive(rows, watch.id);
  const choices = combineTargets(rows, watch.id);
  const tone = statusKey(row, rows);
  const statusLabel = labels[tone] || labels.needs;

  function togglePicker() {
    setOpenOptions(null);
    setOpenPicker(current => current === watch.id ? null : watch.id);
    setQuery('');
  }

  function toggleEpisode(episodeId) {
    setRows(current => {
      const next = { ...current };
      const target = { ...next[String(watch.id)] };
      target.touched = true;
      target.selected = target.selected.includes(episodeId)
        ? target.selected.filter(value => value !== episodeId)
        : [...target.selected, episodeId];
      next[String(watch.id)] = target;
      return next;
    });
  }

  function removeEpisode(episodeId) {
    setRows(current => {
      const next = { ...current };
      const target = { ...next[String(watch.id)] };
      target.touched = true;
      target.selected = target.selected.filter(value => value !== episodeId);
      next[String(watch.id)] = target;
      return next;
    });
  }

  function acceptSuggestion() {
    if (!row.pending) return;
    setRows(current => {
      const next = { ...current };
      const target = { ...next[String(watch.id)] };
      target.selected = [target.pending];
      target.touched = true;
      next[String(watch.id)] = target;
      return next;
    });
  }

  function switchArchive(value) {
    if (!archiveAllowed && value) return;
    setRows(current => {
      const next = { ...current };
      const target = { ...next[String(watch.id)] };
      target.archive = value;
      if (value) target.combine = String(watch.id);
      next[String(watch.id)] = target;
      return next;
    });
  }

  function switchCombine(value) {
    setRows(current => {
      const next = { ...current };
      const target = { ...next[String(watch.id)] };
      target.combine = value;
      if (value !== String(watch.id)) target.archive = false;
      next[String(watch.id)] = target;
      return next;
    });
  }

  const foundEpisodes = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return episodes;
    return episodes.filter(episode => `${episode.code} ${episode.title} ${episode.airDate || ''}`
      .toLowerCase().includes(needle));
  }, [episodes, query]);

  const combineOptions = [
    { value: String(watch.id), label: labels.keepSeparate },
    ...choices.map(id => ({ value: String(id), label: rows[String(id)]?.label || id })),
  ];

  const meta = [watch.dateLabel || labels.noDate];
  if (watch.score !== null && watch.score !== undefined) meta.push(`${labels.score} ${watch.score}`);
  if (watch.status) meta.push(watch.status);

  return <View style={[styles.watch, { backgroundColor: palette.surfaceStrong, borderColor: palette.border }]}>
    <View style={styles.watchGrid}>
      <View style={styles.watchInfo}>
        <Text style={[styles.watchTitle, { color: palette.text }]}>{watch.label}</Text>
        <Text style={[styles.meta, { color: palette.textMuted }]}>{meta.join(' · ')}</Text>
        {watch.notes ? <Text numberOfLines={2} style={[styles.meta, { color: palette.textMuted }]}>{watch.notes}</Text> : null}
      </View>

      <View style={styles.watchChooser}>
        {combined ? <Text style={[styles.meta, { color: palette.textMuted }]}>
          {`${labels.combinedUses} ${combinedLabel}`}
        </Text> : null}
        {row.archive ? <Text style={[styles.meta, { color: palette.textMuted }]}>{labels.archiveNote}</Text> : null}
        {!row.archive && !combined ? <View style={styles.chipRow}>
          {row.selected.map(episodeId => {
            const episode = episodes.find(item => item.id === episodeId);
            const label = episode ? `${episode.code} ${episode.title}` : episodeId;
            return <View key={episodeId} style={[styles.episodeChip, { backgroundColor: palette.surface, borderColor: palette.border }]}>
              <Text style={[styles.episodeChipText, { color: palette.text }]}>{label}</Text>
              <Pressable accessibilityRole="button" accessibilityLabel={labels.removeEpisode}
                onPress={() => removeEpisode(episodeId)} style={({ pressed }) => [styles.remove, pressed && { opacity: 0.6 }]}>
                <Text style={[styles.removeText, { color: palette.textMuted }]}>×</Text>
              </Pressable>
            </View>;
          })}
          <Button label={row.selected.length ? labels.addOrChange : labels.chooseEpisode}
            tone="surface" onPress={togglePicker} palette={buttonPalette(palette)} />
          {row.pending && !row.selected.length ? <Pressable accessibilityRole="button" onPress={acceptSuggestion}
            style={({ pressed }) => pressed && { opacity: 0.7 }}>
            <Text style={[styles.link, { color: palette.accent }]}>
              {`${labels.useSuggestion} ${episodes.find(item => item.id === row.pending)?.code || row.pending}`}
            </Text>
          </Pressable> : null}
        </View> : null}

        {openPicker === watch.id ? <View style={[styles.picker, {
          backgroundColor: palette.background, borderColor: palette.border,
        }]}>
          <TextField label={labels.searchPlaceholder} labelHidden value={query}
            placeholder={labels.searchPlaceholder} accessibilityLabel={labels.searchPlaceholder}
            onChangeText={setQuery} palette={palette} />
          <ScrollView style={styles.pickerList} keyboardShouldPersistTaps="handled" nestedScrollEnabled>
            {foundEpisodes.map(episode => {
              const selected = row.selected.includes(episode.id);
              return <Pressable key={episode.id} accessibilityRole="button"
                accessibilityState={{ selected }}
                accessibilityLabel={`${episode.code} ${episode.title}`}
                onPress={() => toggleEpisode(episode.id)}
                style={({ pressed }) => [styles.pickerRow, {
                  backgroundColor: selected ? palette.surfaceStrong : palette.background,
                }, pressed && { opacity: 0.75 }]}>
                <Text style={[styles.pickerCode, { color: palette.text }]}>{episode.code}</Text>
                <Text numberOfLines={1} style={[styles.pickerTitle, { color: palette.textSecondary }]}>{episode.title}</Text>
                <Text style={[styles.pickerDate, { color: palette.textMuted }]}>{episode.airDate || ''}</Text>
                {selected ? <Text style={[styles.check, { color: palette.accent }]}>✓</Text> : null}
              </Pressable>;
            })}
          </ScrollView>
        </View> : null}
      </View>

      <View style={styles.watchState}>
        <StatusPill label={statusLabel} tone={tone} palette={palette} />
        <Pressable accessibilityRole="button" onPress={() => {
          setOpenPicker(null);
          setOpenOptions(current => current === watch.id ? null : watch.id);
        }} style={({ pressed }) => pressed && { opacity: 0.7 }}>
          <Text style={[styles.link, { color: palette.textMuted }]}>{labels.options}</Text>
        </Pressable>
      </View>
    </View>

    {openOptions === watch.id ? <View style={[styles.options, { borderColor: palette.border }]}>
      <Pressable accessibilityRole="checkbox" accessibilityLabel={labels.archiveLabel}
        accessibilityState={{ checked: row.archive, disabled: !archiveAllowed }}
        disabled={!archiveAllowed} onPress={() => switchArchive(!row.archive)}
        style={({ pressed }) => [styles.checkRow, pressed && archiveAllowed && { opacity: 0.7 }]}>
        <View style={[styles.checkBox, {
          borderColor: archiveAllowed ? palette.border : palette.surfaceMuted,
          backgroundColor: row.archive ? palette.accent : 'transparent',
          opacity: archiveAllowed ? 1 : 0.45,
        }]}>
          {row.archive ? <Text style={[styles.checkMark, { color: palette.accentText }]}>✓</Text> : null}
        </View>
        <Text style={[styles.checkLabel, {
          color: archiveAllowed ? palette.textSecondary : palette.textMuted,
          opacity: archiveAllowed ? 1 : 0.6,
        }]}>{labels.archiveLabel}</Text>
      </Pressable>
      <View style={styles.combineField}>
        <Text style={[styles.checkLabel, { color: palette.textSecondary }]}>{labels.combineLabel}</Text>
        <SelectField label={labels.combineLabel} labelHidden name={`combine-${watch.id}`}
          value={row.combine} options={combineOptions} disabled={row.archive}
          onChange={({ target }) => switchCombine(target.value)} palette={palette} />
      </View>
    </View> : null}
  </View>;
}

function EpisodeReview({ model, labels, palette, onApply, onRevert, onCancel }) {
  const review = model.review || {};
  const [rows, setRows] = useState(() => choiceRows(review.watches));
  const [filter, setFilter] = useState('all');
  const [openPicker, setOpenPicker] = useState(null);
  const [openOptions, setOpenOptions] = useState(null);
  const [query, setQuery] = useState('');

  const rowList = Object.values(rows);
  const needsCount = rowList.filter(row => !row.archive && !isCombined(row) && !row.selected.length).length;
  const pendingCount = rowList.filter(row => !row.archive && !isCombined(row)
    && !row.selected.length && row.pending).length;
  const episodes = review.episodes || [];
  const seasons = review.seasons || [];

  function visible(id) {
    return filter === 'all' || (!rows[String(id)].archive && !isCombined(rows[String(id)])
      && !rows[String(id)].selected.length);
  }

  function acceptAll() {
    setRows(current => {
      const next = { ...current };
      Object.keys(next).forEach(id => {
        const row = next[id];
        if (!row.archive && !isCombined(row) && !row.selected.length && row.pending) {
          next[id] = { ...row, selected: [row.pending], touched: true };
        }
      });
      return next;
    });
  }

  function apply() {
    onApply?.({
      orderId: review.orderId,
      token: review.token,
      rows: rowList.map(row => ({
        id: row.id,
        selected: row.selected,
        combine: row.combine,
        archive: row.archive,
      })),
    });
  }

  return <View style={styles.stack}>
    <View style={[styles.card, { backgroundColor: palette.surfaceStrong, borderColor: palette.border }]}>
      <View>
        <SectionHeading palette={palette}>{review.label || labels.movingTo}</SectionHeading>
        <Text style={[styles.copy, { color: palette.textMuted }]}>{labels.reviewHelp}</Text>
      </View>
      <View style={styles.toolbar}>
        <View style={[styles.segmented, { borderColor: palette.border }]}>
          <Pressable accessibilityRole="button" accessibilityState={{ selected: filter === 'all' }}
            onPress={() => setFilter('all')} style={[styles.segment, filter === 'all' && { backgroundColor: palette.surfaceMuted }]}>
            <Text style={[styles.segmentText, { color: filter === 'all' ? palette.text : palette.textMuted }]}>{labels.allViewings}</Text>
          </Pressable>
          <Pressable accessibilityRole="button" accessibilityState={{ selected: filter === 'needs' }}
            onPress={() => setFilter('needs')} style={[styles.segment, filter === 'needs' && { backgroundColor: palette.surfaceMuted }]}>
            <Text style={[styles.segmentText, { color: filter === 'needs' ? palette.text : palette.textMuted }]}>
              {`${labels.needsChoice} (${needsCount})`}
            </Text>
          </Pressable>
        </View>
        {pendingCount > 0 ? <Button label={`${labels.acceptAll} (${pendingCount})`} tone="surface"
          onPress={acceptAll} palette={buttonPalette(palette)} /> : null}
        {model.canRevert ? <Button label={labels.undo} tone="surface"
          onPress={onRevert} palette={buttonPalette(palette)} /> : null}
      </View>
      {pendingCount > 0 ? <Warning palette={palette}>{labels.suggestionWarning}</Warning> : null}
    </View>

    {seasons.length ? seasons.map(season => <View key={season.number} style={styles.stack}>
      <SectionHeading level={3} palette={palette}>{season.label}</SectionHeading>
      {(season.watches || []).filter(id => visible(id)).map(id => <WatchRow key={id} watch={rows[String(id)]}
        rows={rows} setRows={setRows} labels={labels} palette={palette}
        openPicker={openPicker} setOpenPicker={setOpenPicker} query={query} setQuery={setQuery}
        openOptions={openOptions} setOpenOptions={setOpenOptions} episodes={episodes} />)}
    </View>) : <Text style={[styles.empty, { color: palette.textMuted }]}>{labels.emptyViewings}</Text>}

    <View style={styles.actions}>
      <Button label={labels.apply} disabled={needsCount > 0} onPress={apply} palette={buttonPalette(palette)} />
      <Button label={labels.cancel} tone="surface" onPress={onCancel} palette={buttonPalette(palette)} />
      {needsCount > 0 ? <Text style={[styles.copy, { color: palette.textSecondary }]}>
        {`${needsCount} ${labels.needsRemaining}`}
      </Text> : null}
    </View>
  </View>;
}

export function EpisodeOrdering({
  model = {},
  labels,
  palette,
  onOpenItem,
  onReview,
  onRevert,
  onApply,
  onCancel,
}) {
  const colors = mergePalette(palette);
  const copy = mergeLabels(labels);
  if (model.mode === 'review') {
    return <View style={styles.stack}>
      <EpisodeHeader model={model} labels={copy} palette={colors} onOpenItem={onOpenItem} />
      {(model.providerErrors || []).map(error => <Warning key={error} palette={colors}>{error}</Warning>)}
      <EpisodeReview model={model} labels={copy} palette={colors}
        onApply={onApply} onRevert={onRevert} onCancel={onCancel} />
    </View>;
  }
  return <View style={styles.stack}>
    <EpisodeHeader model={model} labels={copy} palette={colors} onOpenItem={onOpenItem} />
    {(model.providerErrors || []).map(error => <Warning key={error} palette={colors}>{error}</Warning>)}
    {model.hasActiveOrder ? <View style={[styles.card, {
      backgroundColor: colors.surfaceStrong, borderColor: colors.border,
    }]}>
      <View style={styles.revertCopy}>
        <Text style={[styles.watchTitle, { color: colors.text }]}>{model.revertLabel || copy.originalNumbering}</Text>
        <Text style={[styles.meta, { color: colors.textMuted }]}>
          {model.canRevert ? copy.revertHelp : copy.revertBlocked}
        </Text>
      </View>
      {model.canRevert ? <Button label={copy.undo} tone="surface" onPress={onRevert}
        palette={buttonPalette(colors)} /> : null}
    </View> : null}
    {(model.orderGroups || []).length ? model.orderGroups.map(group => <View key={group.provider} style={styles.stack}>
      <SectionHeading palette={colors}>{group.provider}</SectionHeading>
      {(group.choices || []).map(choice => <View key={`${choice.provider}-${choice.key}`}
        style={[styles.choiceRow, { backgroundColor: colors.surfaceStrong, borderColor: colors.border }]}>
        <View style={styles.choiceCopy}>
          <Text style={[styles.watchTitle, { color: colors.text }]}>{choice.label}</Text>
          {choice.current ? <StatusPill label={copy.current} tone="matched" palette={colors} /> : null}
        </View>
        <Button label={copy.reviewChanges} tone="surface" onPress={() => onReview?.(choice)}
          palette={buttonPalette(colors)} />
      </View>)}
    </View>) : <Text style={[styles.empty, { color: colors.textMuted }]}>{copy.noOrders}</Text>}
  </View>;
}

function EpisodeHeader({ model, labels, palette, onOpenItem }) {
  return <View style={styles.header}>
    {model.itemTitle ? <Pressable accessibilityRole="link" onPress={() => onOpenItem?.()}
      style={({ pressed }) => pressed && { opacity: 0.65 }}>
      <Text style={[styles.backLink, { color: palette.textMuted }]}>{`‹ ${model.itemTitle}`}</Text>
    </Pressable> : null}
    <SectionHeading level={1} palette={palette}>{labels.title}</SectionHeading>
    <Text style={[styles.copy, { color: palette.textMuted }]}>{labels.lead}</Text>
    <Text style={[styles.copy, { color: palette.textSecondary }]}>
      {`${labels.currentOrder} ${model.currentOrderLabel || labels.originalNumbering}`}
    </Text>
  </View>;
}

export function TvProviderSwitch({ model = {}, labels, palette, onMove, onCancel, onBack }) {
  const colors = mergePalette(palette);
  const copy = mergeLabels(labels);
  const missing = model.missing || [];
  return <View style={styles.stack}>
    <View style={styles.header}>
      <SectionHeading level={1} palette={colors}>{copy.moveTracking}</SectionHeading>
      {model.itemTitle ? <Text style={[styles.leadTitle, { color: colors.textSecondary }]}>{model.itemTitle}</Text> : null}
    </View>
    {model.error ? <View style={styles.stack}>
      <View accessibilityRole="alert" style={[styles.card, { backgroundColor: colors.dangerSoft, borderColor: colors.danger }]}>
        <Text style={[styles.copy, { color: colors.text }]}>{model.error}</Text>
      </View>
      <Button label={copy.back} tone="surface" onPress={onBack} palette={buttonPalette(colors)} />
    </View> : <View style={styles.stack}>
      <Text style={[styles.copy, { color: colors.textSecondary }]}>{model.copy || copy.moveCopy}</Text>
      <View style={[styles.summary, { backgroundColor: colors.surfaceStrong, borderColor: colors.border }]}>
        <View style={styles.summaryCell}>
          <Text style={[styles.summaryLabel, { color: colors.textMuted }]}>
            {`${copy.matchedOn} ${model.targetLabel || ''}`}
          </Text>
          <Text style={[styles.summaryValue, { color: colors.text }]}>{model.targetTitle || ''}</Text>
        </View>
        <View style={styles.summaryCell}>
          <Text style={[styles.summaryLabel, { color: colors.textMuted }]}>{copy.trackedSeasons}</Text>
          <Text style={[styles.summaryValue, { color: colors.text }]}>{model.seasons ?? 0}</Text>
        </View>
        <View style={styles.summaryCell}>
          <Text style={[styles.summaryLabel, { color: colors.textMuted }]}>{copy.watchedEpisodes}</Text>
          <Text style={[styles.summaryValue, { color: colors.text }]}>{model.episodes ?? 0}</Text>
        </View>
      </View>
      {missing.length ? <View accessibilityRole="alert" style={[styles.card, {
        backgroundColor: colors.warningSoft, borderColor: colors.warning,
      }]}>
        <Text style={[styles.summaryValue, { color: colors.text }]}>
          {model.missingTitle || `${model.targetLabel || ''} ${copy.missingTitle}`}
        </Text>
        <Text style={[styles.copy, { color: colors.textSecondary }]}>{`${copy.missing} ${missing.join(', ')}`}</Text>
      </View> : null}
      <View style={styles.actions}>
        <Button label={model.moveLabel || copy.moveTo} disabled={missing.length > 0}
          onPress={onMove} palette={buttonPalette(colors)} />
        <Button label={copy.cancel} tone="surface" onPress={onCancel} palette={buttonPalette(colors)} />
      </View>
    </View>}
  </View>;
}

export function MetadataMatchResults({
  model = {},
  labels,
  palette,
  busyId,
  error,
  onChoose,
}) {
  const colors = mergePalette(palette);
  const copy = mergeLabels(labels);
  const results = model.results || [];
  const shownError = error || model.error;

  if (shownError) {
    return <View accessibilityRole="alert" style={[styles.error, {
      backgroundColor: colors.dangerSoft, borderColor: colors.danger,
    }]}>
      <Text style={[styles.copy, { color: colors.text }]}>{shownError}</Text>
    </View>;
  }
  if (!results.length) {
    if (model.variant === 'libraryMove' ? !model.query : !model.provider) return null;
    return <Text style={[styles.empty, { color: colors.textMuted }]}>{copy.noMatches}</Text>;
  }

  return <View style={styles.stack}>
    {model.variant === 'libraryMove' ? <Text style={[styles.copy, { color: colors.textMuted }]}>{copy.moveIntro}</Text> : null}
    <View style={[styles.card, { backgroundColor: colors.surface, borderColor: colors.border, padding: 0 }]}>
      {results.map(result => {
        const busy = busyId === result.id;
        return <View key={result.id} style={[styles.resultRow, { borderColor: colors.border }]}>
          {result.image ? <Image source={{ uri: result.image }} accessible={false}
            style={[styles.resultImage, model.variant === 'libraryMove' ? styles.resultImageWide : null]} /> : <View style={[styles.resultImage, styles.resultPlaceholder, {
              backgroundColor: colors.surfaceStrong, borderColor: colors.border,
            }]}>
            <Text style={[styles.resultInitial, { color: colors.textMuted }]}>{(result.title || '?').slice(0, 1)}</Text>
          </View>}
          <View style={styles.resultCopy}>
            <Text numberOfLines={1} style={[styles.watchTitle, { color: colors.text }]}>{result.title}</Text>
            <Text numberOfLines={1} style={[styles.meta, { color: colors.textMuted }]}>{result.meta || ''}</Text>
          </View>
          <Button label={busy
            ? (model.variant === 'libraryMove' ? copy.moving : copy.saving)
            : (result.actionLabel || (model.variant === 'libraryMove' ? copy.moveTo : copy.useMatch))}
            busy={busy} disabled={!!busy} onPress={() => onChoose?.(result)}
            palette={buttonPalette(colors)} />
        </View>;
      })}
    </View>
  </View>;
}

const styles = StyleSheet.create({
  stack: { gap: 12 },
  header: { gap: 6 },
  heading: { fontSize: 18, fontWeight: '700' },
  leadTitle: { fontSize: 16, fontWeight: '600' },
  copy: { fontSize: 13, lineHeight: 19 },
  meta: { fontSize: 12, lineHeight: 17 },
  empty: { fontSize: 13, lineHeight: 19 },
  card: { borderWidth: 1, borderRadius: 10, padding: 14, gap: 10 },
  warning: { borderWidth: 1, borderRadius: 10, paddingHorizontal: 12, paddingVertical: 10 },
  warningText: { fontSize: 12, lineHeight: 17 },
  pill: { alignSelf: 'flex-start', borderWidth: 1, borderRadius: 9999, paddingHorizontal: 8, paddingVertical: 3, maxWidth: 140 },
  pillText: { fontSize: 11, lineHeight: 15, fontWeight: '600' },
  backLink: { fontSize: 13, fontWeight: '600' },
  toolbar: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', gap: 8 },
  segmented: { flexDirection: 'row', borderWidth: 1, borderRadius: 6, overflow: 'hidden' },
  segment: { paddingHorizontal: 10, paddingVertical: 6 },
  segmentText: { fontSize: 12, fontWeight: '600' },
  choiceRow: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', justifyContent: 'space-between', borderWidth: 1, borderRadius: 8, paddingHorizontal: 12, paddingVertical: 10, gap: 10 },
  choiceCopy: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', gap: 8, flexShrink: 1 },
  revertCopy: { flexShrink: 1, gap: 3 },
  watch: { borderWidth: 1, borderRadius: 8, padding: 12, gap: 10 },
  watchGrid: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'flex-start', gap: 12 },
  watchInfo: { flexBasis: 190, flexGrow: 1, gap: 3, minWidth: 0 },
  watchChooser: { flexBasis: 240, flexGrow: 2, gap: 8, minWidth: 0, position: 'relative' },
  watchState: { flexBasis: 130, flexGrow: 1, flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', justifyContent: 'flex-end', gap: 10 },
  watchTitle: { fontSize: 14, fontWeight: '600' },
  chipRow: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', gap: 8 },
  episodeChip: { flexDirection: 'row', alignItems: 'center', gap: 4, borderWidth: 1, borderRadius: 6, paddingHorizontal: 8, paddingVertical: 4, maxWidth: '100%' },
  episodeChipText: { fontSize: 12, flexShrink: 1 },
  remove: { paddingHorizontal: 2 },
  removeText: { fontSize: 14, fontWeight: '700' },
  link: { fontSize: 12, fontWeight: '600' },
  picker: { position: 'absolute', left: 0, right: 0, top: 34, zIndex: 20, borderWidth: 1, borderRadius: 8, padding: 8, gap: 6 },
  pickerList: { maxHeight: 240 },
  pickerRow: { flexDirection: 'row', alignItems: 'center', gap: 8, paddingHorizontal: 8, paddingVertical: 8, borderRadius: 6 },
  pickerCode: { fontSize: 12, fontWeight: '700' },
  pickerTitle: { flex: 1, fontSize: 12 },
  pickerDate: { fontSize: 11 },
  check: { fontSize: 13, fontWeight: '700' },
  options: { borderTopWidth: 1, paddingTop: 10, gap: 10 },
  checkRow: { flexDirection: 'row', alignItems: 'flex-start', gap: 8 },
  checkBox: { width: 16, height: 16, borderWidth: 1, borderRadius: 3, alignItems: 'center', justifyContent: 'center', marginTop: 1 },
  checkMark: { fontSize: 11, fontWeight: '700', lineHeight: 12 },
  checkLabel: { flexShrink: 1, fontSize: 12, lineHeight: 17 },
  combineField: { gap: 4 },
  actions: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', gap: 10 },
  summary: { flexDirection: 'row', flexWrap: 'wrap', borderWidth: 1, borderRadius: 10, padding: 14, gap: 14 },
  summaryCell: { flexGrow: 1, flexBasis: 140, gap: 3 },
  summaryLabel: { fontSize: 12, lineHeight: 17 },
  summaryValue: { fontSize: 14, fontWeight: '700' },
  error: { borderWidth: 1, borderRadius: 8, paddingHorizontal: 12, paddingVertical: 10 },
  resultRow: { flexDirection: 'row', alignItems: 'center', gap: 12, borderBottomWidth: StyleSheet.hairlineWidth, paddingHorizontal: 10, paddingVertical: 9 },
  resultImage: { width: 34, height: 50, borderRadius: 5, backgroundColor: '#3f3f46' },
  resultImageWide: { width: 48, height: 36 },
  resultPlaceholder: { borderWidth: 1, alignItems: 'center', justifyContent: 'center' },
  resultInitial: { fontSize: 15, fontWeight: '700' },
  resultCopy: { flex: 1, gap: 2, minWidth: 0 },
});