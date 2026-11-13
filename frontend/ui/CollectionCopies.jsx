import { Modal } from './Modal';
import React, { useState } from 'react';
import { Pressable, ScrollView, StyleSheet, Text, View, useWindowDimensions } from 'react-native';
import { Badge } from './Badge';
import { actionIcons } from './actionIcons';
import { Button } from './Button';
import { Icon } from './Icon';
import { sectionSpacing } from './sectionSpacing';
import { DateTimePicker } from './DateTimePicker';
import { SelectField } from './SelectField';
import { FormError, FormField, FormHeader, FormSelect, FormTextField } from './MediaCardFormControls';

const DEFAULT_PALETTE = {
  text: '#fafafa',
  textSecondary: '#d4d4d8',
  textMuted: '#a1a1aa',
  surface: '#27272a',
  surfaceStrong: '#3f3f46',
  surfaceMuted: '#52525b',
  border: '#3f3f46',
  accent: '#6366f1',
  accentStrong: '#4f46e5',
  accentContrast: '#ffffff',
  danger: '#f87171',
  success: '#34d399',
  warning: '#fbbf24',
  radius: 10,
  radiusSmall: 6,
  overlay: 'rgba(9, 9, 11, 0.72)',
  focusStyle: {},
};

const DEFAULT_LABELS = {
  title: 'Collection Entry',
  existing: 'Existing Entries',
  addCopy: 'Add Copy',
  yes: 'Yes',
  addAnother: 'Add Another Copy',
  editCopy: 'Edit Copy',
  save: 'Save',
  cancel: 'Cancel',
  remove: 'Remove',
  edit: 'Edit',
  collected: 'Collected',
  noCopies: 'No owned copies recorded.',
  format: 'Format',
  empty: 'No copies yet.',
  completeness: 'Completeness',
  partial: 'Partial',
  full: 'Full',
  copyLabel: 'Copy',
  seasonScope: 'Apply collection to',
  thisItem: 'This item only',
  season: 'A season',
  episodes: 'Every episode',
  seasonNumber: 'Season',
  cascade: 'Saving creates one copy for every episode in the selected scope.',
  cascadeItem: 'Saving adds a copy for this item only.',
  cascadeSeason: 'Saving adds one copy for every episode in this season.',
  cascadeEpisodes: 'Saving adds one copy for every episode in the show.',
  required: 'This field is required.',
  invalidNumber: 'Enter a number.',
  minimum: 'Must be at least zero.',
  ownerOnly: 'Only the collection owner can edit copies.',
  close: 'Close',
  saved: 'Copy saved.',
};

function mergePalette(palette) {
  return { ...DEFAULT_PALETTE, ...(palette || {}) };
}

function mergeLabels(labels) {
  return { ...DEFAULT_LABELS, ...(labels || {}) };
}

function qualityLine(copy) {
  return [copy.mediaType, copy.resolution ? collectionResolution(copy.resolution) : '', copy.hdr, copy.audioCodec, copy.audioChannels]
    .filter(Boolean).join(' · ');
}

export function CollectionSectionHeading({ title, palette: suppliedPalette, variant = 'native' }) {
  const palette = mergePalette(suppliedPalette);
  return <Text style={[styles.contextLabel, variant === 'web' && styles.contextLabelWeb, { color: palette.textMuted }]}>{title}</Text>;
}

function CollectionSection({ title, palette, variant = 'native', children }) {
  return <View style={styles.contextSection}>
    <CollectionSectionHeading title={title} palette={palette} variant={variant} />
    {children}
  </View>;
}

// Both collection cards use one surface; web retains its compact dialog treatment.
function CollectionCardSurface({ children, footer, palette, variant = 'native', padded = true, contentRef }) {
  return <View style={[styles.collectionSurface, padded && styles.collectionSurfacePadded,
    variant === 'web' && styles.collectionSurfaceWeb,
    { backgroundColor: palette.surface, borderColor: palette.border }]}>
    <View ref={contentRef} style={padded ? styles.collectionSurfaceContent : variant === 'web'
      ? [styles.entryGroupWebContent, footer && { paddingBottom: 0 }] : undefined}>{children}</View>
    {footer}
  </View>;
}

export function CollectionEntryGroup({ children, footer, contentRef, palette: suppliedPalette, variant = 'native' }) {
  return <CollectionCardSurface palette={mergePalette(suppliedPalette)} variant={variant} padded={false} contentRef={contentRef} footer={footer}>{children}</CollectionCardSurface>;
}

export function CollectionShowMore({ expanded, onPress, remaining, palette: suppliedPalette, variant = 'native' }) {
  const palette = mergePalette(suppliedPalette);
  return <Pressable accessibilityRole="button" accessibilityState={{ expanded }}
    onPress={onPress} style={[styles.copyMore,
      // Web's server-rendered final row has no bottom margin; the other rows do.
      variant === 'web' && expanded && { paddingTop: 24 }]}>
    <Text style={[styles.contextMore, { color: palette.accent }]}>{expanded ? 'Show less' : `Show ${remaining} more`}</Text>
  </Pressable>;
}

export function collectionSeasonEpisodes(episodes = []) {
  return episodes.map(episode => ({
    id: String(episode.id),
    label: `S${String(episode.season_number).padStart(2, '0')}E${String(episode.episode_number ?? 0).padStart(2, '0')} · ${episode.title}`,
    resolution: episode.resolutions.length ? episode.resolutions.map(collectionResolution).join(', ') : 'Missing',
  }));
}

export function CollectionEpisodeList({ episodes = [], palette: suppliedPalette, variant = 'native' }) {
  const palette = mergePalette(suppliedPalette);
  return <View style={[styles.copyEpisodes, variant === 'web' && styles.copyEpisodesWeb, { borderColor: palette.border }]}>
    {episodes.map(episode => <View key={episode.id} style={styles.contextItemRow}>
      <Text numberOfLines={1} style={[styles.contextItemLabel, { color: palette.text }]}>{episode.label}</Text>
      <Text numberOfLines={1} style={[styles.contextItemResolutions, { color: palette.textMuted }]}>{episode.resolution}</Text>
    </View>)}
  </View>;
}

export function CollectionEpisodeToggle({ expanded = false, onPress, palette: suppliedPalette, label = 'episodes' }) {
  const palette = mergePalette(suppliedPalette);
  return <Pressable accessibilityRole="button" accessibilityState={{ expanded }}
    accessibilityLabel={`${expanded ? 'Hide' : 'Show'} ${label}`} onPress={onPress} style={styles.iconButton}>
    <View style={expanded ? { transform: [{ rotate: '180deg' }] } : undefined}><Icon spec={actionIcons.chevronDown} color={palette.textMuted} size={18} /></View>
  </Pressable>;
}


function CopyRow({ copy, labels, palette, canMutate, onEdit, onRemove, separator, expanded, onToggle }) {
  const detail = qualityLine(copy);
  return <View style={separator ? { borderTopWidth: StyleSheet.hairlineWidth, borderColor: palette.border } : undefined}>
    <View style={styles.copyRow}>
    <View style={styles.copyBody}>
      <View style={styles.copyTitleRow}>
        <Text style={[styles.copyTitle, { color: palette.text }]}>{copy.label || labels.copyLabel}</Text>
        {copy.completeness?.isPartial ? <Badge
          label={`${copy.completeness.collected}/${copy.completeness.total} · ${labels.partial}`}
          size="xs" nowrap palette={{
            outline: { color: palette.warning, borderColor: palette.border, borderWidth: 1 },
          }} /> : null}
      </View>
      {copy.sourceLabels?.length ? <Text style={[styles.copyMeta, { color: palette.textMuted }]}>{`Source: ${copy.sourceLabels.join(' · ')}`}</Text> : null}
      {copy.qualityLabel || detail ? <Text style={[styles.copyDetail, { color: palette.textSecondary }]}>{copy.qualityLabel || detail}</Text> : null}
      {copy.customSummary ? <Text style={[styles.copyMeta, { color: palette.textMuted }]}>{copy.customSummary}</Text> : null}
      {copy.purchasePrice || copy.purchaseLocation ? <Text style={[styles.copyMeta, { color: palette.textMuted }]}>
        {[copy.purchasePrice, copy.purchaseLocation].filter(Boolean).join(' · ')}
      </Text> : null}
      {copy.collectedAt ? <Text style={[styles.copyMeta, { color: palette.textMuted }]}>
        {labels.collected}: {copy.collectedAtLabel || copy.collectedAt}
      </Text> : null}
    </View>
    {(canMutate || copy.episodes?.length) ? <View style={styles.copyActions}>
      {copy.episodes?.length ? <CollectionEpisodeToggle expanded={expanded} onPress={onToggle} palette={palette} label={`episodes for ${copy.label}`} /> : null}
      {canMutate && onEdit ? <Pressable accessibilityRole="button" accessibilityLabel={`${labels.edit} ${copy.label || labels.copyLabel}`}
        onPress={() => onEdit(copy)} style={styles.iconButton}>
        <Icon spec={actionIcons.edit} color={palette.accent} size={16} style={[styles.iconText, { color: palette.accent }]}>{'✎'}</Icon>
      </Pressable> : null}
      {canMutate && onRemove ? <Pressable accessibilityRole="button" accessibilityLabel={`${labels.remove} ${copy.label || labels.copyLabel}`}
        onPress={() => onRemove(copy)} style={styles.iconButton}>
        <Icon spec={actionIcons.trash} color={palette.danger} size={16} style={[styles.iconText, { color: palette.danger }]}>{'⌫'}</Icon>
      </Pressable> : null}
    </View> : null}
    </View>
    {expanded ? <CollectionEpisodeList episodes={copy.episodes} palette={palette} /> : null}
  </View>;
}

export function CollectionCopySummary({ copies = [], labels: suppliedLabels, palette: suppliedPalette, canMutate = false, onEdit, onRemove, initialLimit }) {
  const [showAll, setShowAll] = useState(false);
  const [expandedIds, setExpandedIds] = useState([]);
  const labels = mergeLabels(suppliedLabels);
  const palette = mergePalette(suppliedPalette);
  if (!copies.length) return <Text style={[styles.emptyCopy, { color: palette.textMuted }]}>{labels.noCopies}</Text>;
  return <CollectionEntryGroup palette={palette}>
    {(showAll || !initialLimit ? copies : copies.slice(0, initialLimit)).map((copy, index) => <CopyRow key={copy.id} copy={copy} labels={labels} palette={palette}
      separator={index > 0} canMutate={canMutate} onEdit={onEdit} onRemove={onRemove}
      expanded={expandedIds.includes(copy.id)} onToggle={() => setExpandedIds(current => current.includes(copy.id) ? current.filter(id => id !== copy.id) : [...current, copy.id])} />)}
    {initialLimit && copies.length > initialLimit ? <CollectionShowMore expanded={showAll}
      onPress={() => setShowAll(value => !value)} remaining={copies.length - initialLimit} palette={palette} /> : null}
  </CollectionEntryGroup>;
}

function CheckboxField({ label, value, onChange, palette, editable, help, yes = 'Yes' }) {
  return <FormField label={label} palette={palette}>
    <Pressable accessibilityRole="checkbox" accessibilityLabel={label}
      accessibilityState={{ checked: !!value, disabled: !editable }}
      disabled={!editable} onPress={() => onChange?.(!value)}
      style={({ pressed }) => [styles.checkboxRow, {
        borderColor: value ? palette.accent : palette.border,
        backgroundColor: value ? `${palette.accent}22` : palette.surfaceStrong,
        opacity: editable ? (pressed ? 0.7 : 1) : 0.6,
      }]}>
      <View style={[styles.checkboxBox, { borderColor: value ? palette.accent : palette.border, backgroundColor: value ? palette.accent : 'transparent' }]}>
        {value ? <Text style={[styles.checkboxCheck, { color: palette.accentContrast }]}>✓</Text> : null}
      </View>
      <Text style={[styles.checkboxLabel, { color: palette.textSecondary }]}>{yes}</Text>
    </Pressable>
    {help ? <Text style={[styles.help, { color: palette.textMuted }]}>{help}</Text> : null}
  </FormField>;
}

function MediumFields({ fields = [], values, errors, labels, palette, canMutate, onChange, popover }) {
  return <View style={styles.fieldsGrid}>
    {fields.map(field => {
      if (field.type === 'select') {
        return <View key={field.name} style={styles.fieldCell}>
          <FormField label={field.label} required={field.required} error={errors[field.name]}
            palette={palette}>
            <SelectField labelHidden filter popover={popover} multiple={field.multiple} label={field.label} value={values[field.name] ?? ''}
              options={field.options || []} palette={palette} disabled={!canMutate}
              onChange={event => onChange?.(field.name, event.target.value)} />
          </FormField>
        </View>;
      }
      if (field.type === 'checkbox') {
        return <View key={field.name} style={styles.fieldCell}>
          <CheckboxField label={field.label} value={!!values[field.name]}
            palette={palette} editable={canMutate} yes={labels.yes}
            onChange={value => onChange?.(field.name, value)} />
        </View>;
      }
      if (field.type === 'datetime') {
        return <View key={field.name} style={styles.fieldCell}>
          <FormField label={field.label} error={errors[field.name]} palette={palette}>
            <DateTimePicker value={values[field.name] ?? ''} trackTime
              onChange={value => onChange?.(field.name, value)} palette={palette} />
          </FormField>
        </View>;
      }
      return <View key={field.name} style={styles.fieldCell}>
        <FormTextField label={field.label}
          value={values[field.name] ?? ''} required={field.required}
          error={errors[field.name]} placeholder={field.placeholder}
          keyboardType={field.type === 'number' ? 'decimal-pad' : 'default'}
          editable={canMutate} palette={palette}
          onChangeText={value => onChange?.(field.name, value)} />
      </View>;
    })}
  </View>;
}

export function CollectionCopyEditor({
  fields = [],
  values = {},
  errors = {},
  labels: suppliedLabels,
  palette: suppliedPalette,
  canMutate = false,
  onChange,
  popover = false,
  children,
}) {
  const labels = mergeLabels(suppliedLabels);
  const palette = mergePalette(suppliedPalette);
  if (!canMutate) return <Text style={[styles.readOnly, { color: palette.textMuted, borderColor: palette.border }]}>
    {labels.ownerOnly}
  </Text>;
  return <View style={styles.editor}>
    <MediumFields fields={fields} values={values} errors={errors} labels={labels}
      palette={palette} canMutate={canMutate} onChange={onChange} popover={popover} />
    {children}
  </View>;
}

export function CollectionSeasonCascade({
  scope = 'item',
  seasons = [],
  selectedSeason,
  labels: suppliedLabels,
  palette: suppliedPalette,
  canMutate = false,
  onScopeChange,
  onSeasonChange,
}) {
  const labels = mergeLabels(suppliedLabels);
  const palette = mergePalette(suppliedPalette);
  if (!seasons.length) return null;
  const scopeOptions = [
    { value: 'item', label: labels.thisItem },
    { value: 'season', label: labels.season },
    { value: 'episodes', label: labels.episodes },
  ];
  const seasonOptions = seasons.map(season => ({
    value: String(season.number),
    label: season.label || `Season ${season.number}`,
  }));
  const note = scope === 'season' ? labels.cascadeSeason
    : scope === 'episodes' ? labels.cascadeEpisodes
      : labels.cascadeItem;
  return <View style={[styles.cascade, { borderColor: palette.border, backgroundColor: palette.surfaceStrong }]}>
    <FormSelect label={labels.seasonScope} value={scope} options={scopeOptions}
      palette={palette} onChange={value => onScopeChange?.(value)} />
    {scope === 'season' ? <FormSelect label={labels.seasonNumber}
      value={String(selectedSeason ?? seasonOptions[0]?.value ?? '')}
      options={seasonOptions} palette={palette}
      onChange={value => onSeasonChange?.(value)} /> : null}
    <Text style={[styles.cascadeNote, { color: palette.textMuted }]}>{note}</Text>
  </View>;
}

function collectionResolution(value) {
  if (!value) return 'Unknown';
  const resolution = String(value).match(/(?:^|_)(2160p|1080p|720p|576p|480p|4k|8k)(?:$|_)/i);
  if (resolution) return resolution[1].toLowerCase();
  return String(value).replace(/_/g, ' ').replace(/\b(hd|sd|uhd)\b/gi, part => part.toUpperCase());
}

// Props-only presentation shared by native and web adapters.
export function CollectionContextCard({ context, palette: suppliedPalette, variant = 'native' }) {
  const [expanded, setExpanded] = useState(false);
  const [itemsExpanded, setItemsExpanded] = useState(false);
  const [showAllItems, setShowAllItems] = useState(false);
  const palette = mergePalette(suppliedPalette);
  const copies = context?.copies || [];
  const groups = new Map();
  const items = new Map();
  if (Array.isArray(context?.resolutionCounts)) {
    context.resolutionCounts.forEach(({ resolution, count }) => {
      const label = collectionResolution(resolution);
      groups.set(label, (groups.get(label) || 0) + count);
    });
  }
  copies.forEach(copy => {
    if (!Array.isArray(context?.resolutionCounts)) {
      const resolution = collectionResolution(copy.resolution);
      groups.set(resolution, (groups.get(resolution) || 0) + 1);
    }
    const item = items.get(copy.item_id) || { title: copy.item__title, copies: [] };
    item.copies.push(copy);
    items.set(copy.item_id, item);
  });
  const itemRows = new Map();
  copies.forEach(copy => {
    const season = copy.item__season_number;
    const episode = copy.item__episode_number;
    const key = season == null ? `item:${copy.item_id}` : `${season}:${episode ?? ''}`;
    const row = itemRows.get(key) || {
      key, season, episode,
      label: season == null ? copy.item__title : `${`S${String(season).padStart(2, '0')}${episode == null ? '' : `E${String(episode).padStart(2, '0')}`}`} · ${copy.item__title}`,
      resolutions: [],
    };
    const resolution = collectionResolution(copy.resolution);
    row.resolutions.push(resolution);
    itemRows.set(key, row);
  });
  const sortedItems = [...itemRows.values()].sort((a, b) =>
    (a.season ?? -1) - (b.season ?? -1) || (a.episode ?? -1) - (b.episode ?? -1));
  const colors = ['#3486e8', '#df5b26', '#1c9e76', '#d99700', '#999792'];
  const stats = context?.stats;
  const totalEpisodes = stats?.total_episodes || 0;
  const percent = totalEpisodes ? Math.min(100, Math.floor((stats.collected_episodes || 0) / totalEpisodes * 100)) : null;
  const title = stats?.total_seasons != null
    ? `${stats.collected_seasons || 0} of ${stats.total_seasons} seasons`
    : `${copies.length} ${copies.length === 1 ? 'copy' : 'copies'}`;
  const showItems = [...items.values()].some(item => item.copies.length > 1)
    || [...itemRows.values()].some(row => row.resolutions.length > 1);
  return <CollectionSection title="Summary" palette={palette} variant={variant}>
    <CollectionCardSurface palette={palette} variant={variant}>
      <Pressable accessibilityRole="button" accessibilityState={{ expanded }}
        accessibilityLabel={`${title}, ${expanded ? 'collapse' : 'expand'} collection breakdown`}
        onPress={() => setExpanded(value => !value)} style={styles.contextSummary}>
        <View style={styles.contextHeader}>
          <Text style={[styles.contextTitle, { color: palette.text }]}>{context?.error ? 'Collection unavailable' : context ? title : 'Loading collection…'}</Text>
          <View style={styles.contextDisclosure}>
            {percent != null ? <Text style={[styles.contextMeta, { color: palette.textMuted }]}>{percent}%</Text> : null}
            <View style={expanded ? { transform: [{ rotate: '180deg' }] } : undefined}><Icon spec={actionIcons.chevronDown} size={18} color={palette.textMuted} /></View>
          </View>
        </View>
      <View style={[styles.contextBar, { backgroundColor: palette.surfaceStrong }]}>
        <View style={{ width: `${percent ?? (copies.length ? 100 : 0)}%`, flexDirection: 'row' }}>
          {[...groups].map(([name, count], index) => <View key={name} style={{ flex: count, backgroundColor: colors[index % colors.length] }} />)}
        </View>
      </View>
      <Text style={[styles.contextMeta, { color: palette.textMuted }]}>
        {totalEpisodes ? `${stats.collected_episodes || 0} of ${totalEpisodes} episodes collected` : `${copies.length} ${copies.length === 1 ? 'copy' : 'copies'} collected`}
      </Text>
      </Pressable>
      {expanded ? <View style={[styles.contextBreakdown, { borderColor: palette.border }]}>
        {!copies.length ? <Text style={[styles.contextMeta, { color: palette.textMuted }]}>No owned copies recorded.</Text> : null}
        {[...groups].map(([name, count], index) => <View key={name} style={styles.contextRow}>
          <View style={[styles.contextSwatch, { backgroundColor: colors[index % colors.length] }]} />
          <Text style={[styles.contextRowLabel, { color: palette.text }]}>{name}</Text>
          <Text style={[styles.contextMeta, { color: palette.textMuted }]}>{count}</Text>
        </View>)}
        {totalEpisodes > 0 ? <View style={styles.contextRow}>
          <View style={[styles.contextSwatch, { backgroundColor: palette.surfaceStrong }]} />
          <Text style={[styles.contextRowLabel, { color: palette.text }]}>Missing</Text>
          <Text style={[styles.contextMeta, { color: palette.textMuted }]}>{Math.max(0, totalEpisodes - (stats.collected_episodes || 0))}</Text>
        </View> : null}
        {showItems && totalEpisodes > 0 ? <Text style={[styles.contextMeta, { color: palette.textMuted }]}>Resolution reflects the latest copy of each episode.</Text> : null}
        {showItems ? <View style={styles.contextItems}>
          <View style={[styles.contextDivider, { backgroundColor: palette.textMuted }]} />
          <Pressable accessibilityRole="button" accessibilityState={{ expanded: itemsExpanded }}
            accessibilityLabel={`${itemsExpanded ? 'Hide' : 'Show'} ${copies.length} collected items`}
            onPress={() => setItemsExpanded(value => !value)} style={styles.contextHeader}>
            <Text style={[styles.contextRowLabel, { color: palette.text }]}>Collected items</Text>
            <View style={styles.contextDisclosure}>
              <Text style={[styles.contextMeta, { color: palette.textMuted }]}>{copies.length}</Text>
              <View style={itemsExpanded ? { transform: [{ rotate: '180deg' }] } : undefined}>
                <Icon spec={actionIcons.chevronDown} size={18} color={palette.textMuted} />
              </View>
            </View>
          </Pressable>
          {itemsExpanded ? <>
            {(showAllItems ? sortedItems : sortedItems.slice(0, 5)).map(row => <View key={row.key} style={styles.contextItemRow}>
              <Text numberOfLines={1} style={[styles.contextItemLabel, { color: palette.text }]}>{row.label}</Text>
              <Text numberOfLines={1} style={[styles.contextItemResolutions, { color: palette.textMuted }]}>{row.resolutions.join(', ')}</Text>
            </View>)}
            {sortedItems.length > 5 ? <Pressable accessibilityRole="button"
              onPress={() => setShowAllItems(value => !value)}>
              <Text style={[styles.contextMore, { color: palette.accent }]}>{showAllItems ? 'Show less' : `Show ${sortedItems.length - 5} more`}</Text>
            </Pressable> : null}
          </> : null}
        </View> : null}
      </View> : null}
    </CollectionCardSurface>
  </CollectionSection>;
}

export function CollectionCopyDialog({
  visible = false,
  embedded = false,
  item,
  context,
  showExisting = true,
  copies = [],
  copyLimit,
  fields = [],
  values = {},
  errors = {},
  labels: suppliedLabels,
  palette: suppliedPalette,
  canMutate = false,
  scope = 'item',
  seasons = [],
  selectedSeason,
  editingId = null,
  busy = false,
  saveNote = '',
  onClose,
  onChange,
  onScopeChange,
  onSeasonChange,
  onSave,
  onEdit,
  onRemove,
  children,
}) {
  const labels = mergeLabels(suppliedLabels);
  const palette = mergePalette(suppliedPalette);
  const viewport = useWindowDimensions();
  if (!item) return null;
  const completeness = item.completeness;
  const content = <>
        <ScrollView style={styles.dialogScroll} contentContainerStyle={[styles.dialogContent, embedded && { gap: sectionSpacing(viewport.width) }]}
          keyboardShouldPersistTaps="handled">
          {context !== undefined ? <CollectionContextCard context={context} palette={palette} /> : null}
          {!embedded ? <View style={styles.itemHeader}>
            <Text style={[styles.itemTitle, { color: palette.text }]}>{item.title}</Text>
            <Text style={[styles.itemMeta, { color: palette.textSecondary }]}>
              {[item.mediaTypeLabel || item.mediaType, item.format, item.resolution].filter(Boolean).join(' · ')}
            </Text>
            {completeness?.total ? <View style={styles.badgeRow}>
              <Badge label={completeness.isPartial
                ? `${completeness.collected}/${completeness.total} · ${labels.partial}`
                : `${completeness.total}/${completeness.total} · ${labels.full}`}
                size="sm" nowrap palette={{
                  outline: { color: completeness.isPartial ? palette.warning : palette.success, borderColor: palette.border, borderWidth: 1 },
                }} />
            </View> : null}
          </View> : null}

          {showExisting ? <CollectionSection title={labels.existing} palette={palette}>
            <CollectionCopySummary copies={copies} labels={labels} palette={palette}
              canMutate={canMutate} onEdit={onEdit} onRemove={onRemove} initialLimit={copyLimit} />
          </CollectionSection> : null}

          <Text style={[styles.sectionTitle, { color: palette.textMuted }]}>
            {editingId ? labels.editCopy : copies.length ? labels.addAnother : labels.addCopy}
          </Text>
          <CollectionCopyEditor fields={fields} values={values} errors={errors}
            labels={labels} palette={palette} canMutate={canMutate} onChange={onChange} popover={embedded} />
          {canMutate ? <CollectionSeasonCascade scope={scope} seasons={seasons} selectedSeason={selectedSeason}
            labels={labels} palette={palette} canMutate={canMutate}
            onScopeChange={onScopeChange} onSeasonChange={onSeasonChange} /> : null}
          {children}

          <FormError message={errors.form} palette={palette} />
          {saveNote ? <Text accessibilityLiveRegion="polite" style={[styles.saveNote, { color: palette.success }]}>
            {saveNote}
          </Text> : null}
        </ScrollView>
        <View style={[styles.dialogFooter, { borderColor: palette.border }]}>
          <Button label={labels.cancel} tone="surface" palette={palette} onPress={onClose} />
          {canMutate ? <Button label={editingId ? labels.save : labels.addCopy}
            palette={palette} busy={busy} disabled={busy} onPress={onSave} /> : null}
        </View>
  </>;
  if (embedded) return <View style={styles.embedded}>{content}</View>;
  return <Modal visible={visible} transparent animationType="fade" onRequestClose={onClose}>
    <View style={[styles.overlay, { backgroundColor: palette.overlay }]}>
      <Pressable accessibilityRole="button" accessibilityLabel={labels.close}
        style={StyleSheet.absoluteFill} onPress={onClose} />
      <View style={[styles.dialog, { backgroundColor: palette.surface, borderColor: palette.border }]}>
        <FormHeader title={labels.title} closeLabel={labels.close} onClose={onClose} palette={palette} />
        {content}
      </View>
    </View>
  </Modal>;
}

const styles = StyleSheet.create({
  contextSection: { gap: 10 },
  contextLabel: { fontSize: 15, paddingLeft: 16 },
  // Web dialogs use the same compact corners and bordered surfaces as other web cards.
  contextLabelWeb: { paddingLeft: 0, fontSize: 12, fontWeight: '600', textTransform: 'uppercase', letterSpacing: 0.5 },
  collectionSurfaceWeb: { borderRadius: 8, borderWidth: 1 },
  contextSummary: { gap: 12 },
  contextDisclosure: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  collectionSurface: { borderRadius: 24, overflow: 'hidden' },
  collectionSurfacePadded: { padding: 16 },
  collectionSurfaceContent: { gap: 12 },
  contextHeader: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 8 },
  contextTitle: { fontSize: 17, flexShrink: 1 },
  contextMeta: { fontSize: 13 },
  contextBar: { height: 8, borderRadius: 4, overflow: 'hidden', flexDirection: 'row' },
  contextBreakdown: { borderTopWidth: 1, paddingTop: 12, gap: 10 },
  contextRow: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  contextSwatch: { width: 8, height: 8, borderRadius: 2 },
  contextRowLabel: { flex: 1, fontSize: 14 },
  contextItemRow: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  contextItemLabel: { flex: 1, fontSize: 14 },
  contextItemResolutions: { flexShrink: 1, textAlign: 'right', fontSize: 13 },
  contextMore: { fontSize: 14 },
  contextItems: { gap: 10 },
  contextDivider: { height: 1, opacity: 0.4, marginBottom: 2 },
  copyMore: { paddingHorizontal: 16, paddingBottom: 16 },
  copyEpisodes: { marginHorizontal: 16, paddingTop: 12, paddingBottom: 16, borderTopWidth: StyleSheet.hairlineWidth, gap: 10 },
  copyEpisodesWeb: { marginHorizontal: 0, marginTop: 12 },
  copyList: { gap: 8 },
  entryGroupWebContent: { padding: 16 },
  copyRow: { flexDirection: 'row', alignItems: 'center', gap: 12, padding: 16 },
  copyBody: { flex: 1, minWidth: 0, gap: 3 },
  copyTitleRow: { flexDirection: 'row', alignItems: 'center', flexWrap: 'wrap', gap: 6 },
  copyTitle: { fontSize: 16, fontWeight: '600' },
  copyDetail: { fontSize: 12, lineHeight: 17 },
  copyMeta: { fontSize: 11, lineHeight: 16 },
  copyActions: { flexDirection: 'row', gap: 2 },
  iconButton: { width: 32, height: 32, alignItems: 'center', justifyContent: 'center' },
  iconText: { fontSize: 17 },
  emptyCopy: { fontSize: 12, paddingVertical: 4 },
  editor: { gap: 14 },
  fieldsGrid: { flexDirection: 'row', flexWrap: 'wrap', columnGap: 16, rowGap: 16 },
  fieldCell: { flexGrow: 1, flexBasis: 240, minWidth: 0 },
  checkboxRow: { flexDirection: 'row', alignItems: 'center', gap: 10, borderWidth: 1, borderRadius: 8, minHeight: 44, paddingHorizontal: 10 },
  checkboxBox: { width: 18, height: 18, borderWidth: 1, borderRadius: 4, alignItems: 'center', justifyContent: 'center' },
  checkboxCheck: { fontSize: 12, fontWeight: '700' },
  checkboxLabel: { fontSize: 13, fontWeight: '600' },
  help: { fontSize: 12, lineHeight: 17 },
  readOnly: { borderWidth: 1, borderRadius: 8, padding: 10, fontSize: 12, lineHeight: 17 },
  cascade: { borderWidth: 1, borderRadius: 10, padding: 12, gap: 12 },
  cascadeNote: { fontSize: 12, lineHeight: 17 },
  overlay: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 16 },
  dialog: { width: '100%', maxWidth: 620, maxHeight: '88%', borderWidth: 1, borderRadius: 14, padding: 16 },
  embedded: { flex: 1, paddingHorizontal: 16 },
  dialogScroll: { flexGrow: 0 },
  dialogContent: { gap: 16, paddingBottom: 8 },
  itemHeader: { gap: 4 },
  itemTitle: { fontSize: 18, fontWeight: '700' },
  itemMeta: { fontSize: 12 },
  badgeRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 6, marginTop: 2 },
  sectionTitle: { fontSize: 11, fontWeight: '700', letterSpacing: 0.6, textTransform: 'uppercase' },
  saveNote: { fontSize: 12, fontWeight: '600' },
  dialogFooter: { flexDirection: 'row', justifyContent: 'flex-end', gap: 8, borderTopWidth: 1, paddingTop: 12, marginTop: 8 },
});
