import { Modal } from './Modal';
import React, { useState } from 'react';
import { Pressable, ScrollView, StyleSheet, Switch, Text, TextInput, View, useWindowDimensions } from 'react-native';
import { Badge } from './Badge';
import { actionIcons } from './actionIcons';
import { Button } from './Button';
import { Icon } from './Icon';
import { sectionSpacing } from './sectionSpacing';
import { cardTypography } from './cardTypography';
import { CardRow } from './CardRow';
import { DateTimePicker } from './DateTimePicker';
import { SelectField } from './SelectField';
import { FormError, FormHeader, FormSelect } from './MediaCardFormControls';

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
function CollectionCardSurface({ children, footer, palette, variant = 'native', padded = true, contentRef, flushY = false }) {
  return <View style={[styles.collectionSurface, padded && styles.collectionSurfacePadded,
    variant === 'web' && styles.collectionSurfaceWeb,
    { backgroundColor: palette.surface, borderColor: palette.border }]}>
    <View ref={contentRef} style={padded ? styles.collectionSurfaceContent : variant === 'web'
      ? [styles.entryGroupWebContent, flushY && styles.entryGroupFlushY, footer && { paddingBottom: 0 }] : undefined}>{children}</View>
    {footer}
  </View>;
}

// flushY: rows already carry their own 50 pt height, so web drops the card's top and bottom padding.
export function CollectionEntryGroup({ children, footer, contentRef, flushY = false, palette: suppliedPalette, variant = 'native' }) {
  return <CollectionCardSurface palette={mergePalette(suppliedPalette)} variant={variant} padded={false} contentRef={contentRef} footer={footer} flushY={flushY}>{children}</CollectionCardSurface>;
}

// Grouped-card rows shared by Calendar Links and the Add Copy form: one card per
// group, 50 pt rows with a leading icon + label and a trailing control, hairline dividers.
// Expo uses the rounded surface with a 16 pt side inset; web keeps the compact bordered surface.
export function CollectionGroup({ title, palette: suppliedPalette, variant = 'native', children }) {
  const palette = mergePalette(suppliedPalette);
  const rows = React.Children.toArray(children).filter(Boolean);
  // Dividers line up with the labels, so they only indent when the rows carry icons.
  const inset = rows.some(row => row.props?.icon) ? 28 : 0;
  return <View style={styles.groupSection}>
    {title ? <CollectionSectionHeading title={title} palette={palette} variant={variant} /> : null}
    <CollectionEntryGroup palette={palette} variant={variant} flushY>
      <View style={variant === 'native' && styles.groupRows}>
        {rows.map((row, index) => <View key={row.key ?? index}>
          {index ? <View style={[styles.rowDivider, { backgroundColor: palette.textMuted, marginLeft: inset }]} /> : null}
          {row}
        </View>)}
      </View>
    </CollectionEntryGroup>
  </View>;
}

function RowLabel({ icon, label, palette }) {
  return <View style={styles.rowLabel}>
    {icon ? <Icon spec={icon} color={palette.textMuted} size={20} /> : null}
    <Text style={[styles.rowLabelText, { color: palette.text }]}>{label}</Text>
  </View>;
}

// Label on the left, any control or value on the right; a value + onPress makes the row a
// button, and chevron marks a row that opens something. `multiline` lets long values wrap.
export function CollectionRow({ icon, label, value, onPress, chevron = false, multiline = false, palette: suppliedPalette, children, accessibilityLabel }) {
  const palette = mergePalette(suppliedPalette);
  const content = <>
    <RowLabel icon={icon} label={label} palette={palette} />
    {value !== undefined ? <Text style={[styles.rowValue, { color: palette.textSecondary }]}>{value}</Text> : null}
    {children}
    {chevron ? <Icon spec={actionIcons.chevronRight} color={palette.textMuted} size={16} /> : null}
  </>;
  const rowStyle = [styles.groupRow, multiline && styles.groupRowMultiline];
  if (!onPress) return <View style={rowStyle}>{content}</View>;
  return <Pressable accessibilityRole="button" accessibilityLabel={accessibilityLabel || label} onPress={onPress}
    style={({ pressed }) => [rowStyle, pressed && { opacity: 0.72 }]}>{content}</Pressable>;
}

export function CollectionSwitchRow({ icon, label, value, onValueChange, disabled = false, palette: suppliedPalette, variant = 'native' }) {
  const palette = mergePalette(suppliedPalette);
  const web = variant === 'web';
  return <CollectionRow icon={icon} label={label} palette={palette}>
    <View style={styles.switchSlot}>
      <Switch accessibilityLabel={label} value={!!value} disabled={disabled}
        // Web matches the desktop OptionSwitch colors; Expo keeps the system switch look.
        trackColor={web ? { false: palette.surfaceMuted, true: palette.accentStrong } : { false: palette.surfaceStrong, true: palette.accent }}
        thumbColor={web ? (value ? palette.accentContrast : palette.textSecondary) : '#ffffff'}
        activeThumbColor={web ? palette.accentContrast : '#ffffff'}
        onValueChange={onValueChange} />
    </View>
  </CollectionRow>;
}

// `renderPicker` lets a platform supply its own control (iOS passes the Liquid Glass
// menu); the shared SelectField is used everywhere else.
export function CollectionSelectRow({ icon, label, error, required = false, renderPicker, palette: suppliedPalette, ...select }) {
  const palette = mergePalette(suppliedPalette);
  return <View>
    <CollectionRow icon={icon} label={required ? `${label} *` : label} palette={palette}>
      {renderPicker ? renderPicker({ label, value: select.value, options: select.options, palette,
        onChange: value => select.onChange?.({ target: { value } }) })
        : <SelectField labelHidden label={label} palette={palette} {...select}
          triggerStyle={styles.selectTrigger} triggerTextStyle={[styles.rowValue, { color: palette.textSecondary }]} />}
    </CollectionRow>
    {error ? <Text accessibilityLiveRegion="polite" style={[styles.rowError, { color: palette.danger }]}>{error}</Text> : null}
  </View>;
}

export function CollectionTextRow({ icon, label, value, onChangeText, placeholder, keyboardType, editable = true, required = false, error, palette: suppliedPalette }) {
  const palette = mergePalette(suppliedPalette);
  return <View>
    <CollectionRow icon={icon} label={required ? `${label} *` : label} palette={palette}>
      <TextInput accessibilityLabel={label} aria-invalid={error ? true : undefined} editable={editable}
        keyboardType={keyboardType} onChangeText={onChangeText} placeholder={placeholder}
        placeholderTextColor={palette.textMuted} selectionColor={palette.accent}
        value={value == null ? '' : String(value)}
        style={[styles.rowInput, { color: palette.textSecondary, opacity: editable ? 1 : 0.6 }]} />
    </CollectionRow>
    {error ? <Text accessibilityLiveRegion="polite" style={[styles.rowError, { color: palette.danger }]}>{error}</Text> : null}
  </View>;
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
    <CardRow first={!separator} trailing={(canMutate || copy.episodes?.length) ? <View style={styles.copyActions}>
      {copy.episodes?.length ? <CollectionEpisodeToggle expanded={expanded} onPress={onToggle} palette={palette} label={`episodes for ${copy.label}`} /> : null}
      {canMutate && onEdit ? <Pressable accessibilityRole="button" accessibilityLabel={`${labels.edit} ${copy.label || labels.copyLabel}`}
        onPress={() => onEdit(copy)} style={styles.iconButton}>
        <Icon spec={actionIcons.edit} color={palette.accent} size={16} style={[styles.iconText, { color: palette.accent }]}>{'✎'}</Icon>
      </Pressable> : null}
      {canMutate && onRemove ? <Pressable accessibilityRole="button" accessibilityLabel={`${labels.remove} ${copy.label || labels.copyLabel}`}
        onPress={() => onRemove(copy)} style={styles.iconButton}>
        <Icon spec={actionIcons.trash} color={palette.danger} size={16} style={[styles.iconText, { color: palette.danger }]}>{'⌫'}</Icon>
      </Pressable> : null}
    </View> : null}>
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
    </CardRow>
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

// Each Add Copy field's leading icon and example text. Web names are snake_case
// and Expo's camelCase, so lookups ignore case and underscores; Platform and
// Edition are games' use of the resolution and hdr fields.
const COPY_FIELD_ICONS = {
  format: actionIcons.disc,
  resolution: actionIcons.monitor,
  platform: actionIcons.monitor,
  hdr: actionIcons.sun,
  edition: actionIcons.star,
  is3d: actionIcons.cube,
  audiocodec: actionIcons.audioLines,
  audiochannels: actionIcons.speaker,
  bitrate: actionIcons.gauge,
  purchaseprice: actionIcons.dollar,
  location: actionIcons.mapPin,
  purchaselocation: actionIcons.mapPin,
  collectedat: actionIcons.calendar,
};
const COPY_FIELD_EXAMPLES = {
  purchaseprice: '9.99',
  location: 'Amazon',
  purchaselocation: 'Amazon',
  collectedat: 'YYYY-MM-DD',
};
const fieldKey = value => String(value || '').replace(/_/g, '').toLowerCase();

function MediumFields({ fields = [], values, errors, palette, canMutate, onChange, popover, variant, title, renderSelectPicker }) {
  const iconFor = field => COPY_FIELD_ICONS[fieldKey(field.label)] || COPY_FIELD_ICONS[fieldKey(field.name)] || actionIcons.page;
  return <CollectionGroup title={title} palette={palette} variant={variant}>
    {fields.map(field => {
      if (field.type === 'select') {
        return <CollectionSelectRow key={field.name} icon={iconFor(field)} label={field.label} required={field.required}
          error={errors[field.name]} palette={palette} filter popover={popover} multiple={field.multiple}
          renderPicker={field.multiple ? undefined : renderSelectPicker}
          value={values[field.name] ?? ''} options={field.options || []} disabled={!canMutate}
          onChange={event => onChange?.(field.name, event.target.value)} />;
      }
      if (field.type === 'checkbox') {
        return <CollectionSwitchRow key={field.name} icon={iconFor(field)} label={field.label} value={!!values[field.name]}
          palette={palette} variant={variant} disabled={!canMutate}
          onValueChange={value => onChange?.(field.name, value)} />;
      }
      if (field.type === 'datetime') {
        return <View key={field.name}>
          <CollectionRow icon={iconFor(field)} label={field.label} palette={palette}>
            <DateTimePicker value={values[field.name] ?? ''} trackTime
              onChange={value => onChange?.(field.name, value)} palette={palette} />
          </CollectionRow>
          {errors[field.name] ? <Text accessibilityLiveRegion="polite" style={[styles.rowError, { color: palette.danger }]}>{errors[field.name]}</Text> : null}
        </View>;
      }
      return <CollectionTextRow key={field.name} icon={iconFor(field)} label={field.label} value={values[field.name] ?? ''}
        required={field.required} error={errors[field.name]} placeholder={COPY_FIELD_EXAMPLES[fieldKey(field.name)] || field.placeholder || field.help}
        keyboardType={field.type === 'number' ? 'decimal-pad' : 'default'}
        editable={canMutate} palette={palette}
        onChangeText={value => onChange?.(field.name, value)} />;
    })}
  </CollectionGroup>;
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
  variant = 'native',
  title,
  renderSelectPicker,
  children,
}) {
  const labels = mergeLabels(suppliedLabels);
  const palette = mergePalette(suppliedPalette);
  if (!canMutate) return <Text style={[styles.readOnly, { color: palette.textMuted, borderColor: palette.border }]}>
    {labels.ownerOnly}
  </Text>;
  return <View style={styles.editor}>
    <MediumFields fields={fields} values={values} errors={errors}
      palette={palette} canMutate={canMutate} onChange={onChange} popover={popover} variant={variant} title={title} renderSelectPicker={renderSelectPicker} />
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
  renderSelectPicker,
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

          <CollectionCopyEditor fields={fields} values={values} errors={errors}
            labels={labels} palette={palette} canMutate={canMutate} onChange={onChange} popover={embedded} renderSelectPicker={renderSelectPicker}
            title={editingId ? labels.editCopy : copies.length ? labels.addAnother : labels.addCopy} />
          {canMutate ? <CollectionSeasonCascade scope={scope} seasons={seasons} selectedSeason={selectedSeason}
            labels={labels} palette={palette} canMutate={canMutate}
            onScopeChange={onScopeChange} onSeasonChange={onSeasonChange} /> : null}
          {children}

          <FormError message={errors.form} palette={palette} />
          {saveNote ? <Text accessibilityLiveRegion="polite" style={[styles.saveNote, { color: palette.success }]}>
            {saveNote}
          </Text> : null}
        </ScrollView>
        <View style={styles.dialogFooter}>
          <View style={styles.footerButton}><Button label={labels.cancel} tone="ghost" size="lg" width="full" onPress={onClose} palette={{ ...palette, ghost: {
            background: 'transparent', pressed: palette.surfaceStrong, hovered: palette.surfaceStrong,
            text: palette.textSecondary, border: palette.border,
          } }} /></View>
          {canMutate ? <View style={styles.footerButton}><Button label={editingId ? labels.save : labels.addCopy} size="lg" width="full"
            palette={palette} busy={busy} disabled={busy} onPress={onSave} /></View> : null}
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
  groupSection: { gap: 10 },
  groupRows: { paddingHorizontal: 16 },
  groupRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 12, minHeight: 50 },
  groupRowMultiline: { paddingVertical: 8 },
  rowLabel: { flexDirection: 'row', alignItems: 'center', gap: 8, flexShrink: 1 },
  rowLabelText: { ...cardTypography.title, flexShrink: 1 },
  rowValue: { fontSize: 16 },
  rowDivider: { height: 1, opacity: 0.4 },
  rowInput: { flex: 1, minWidth: 80, fontSize: 16, textAlign: 'right', paddingVertical: 0 },
  rowError: { fontSize: 12, lineHeight: 17, paddingBottom: 8 },
  switchSlot: { height: 50, justifyContent: 'center', alignItems: 'center' },
  selectTrigger: { borderWidth: 0, backgroundColor: 'transparent', paddingHorizontal: 0, paddingVertical: 0 },
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
  contextTitle: { ...cardTypography.title, flexShrink: 1 },
  contextMeta: { ...cardTypography.secondary },
  contextBar: { height: 8, borderRadius: 4, overflow: 'hidden', flexDirection: 'row' },
  contextBreakdown: { borderTopWidth: 1, paddingTop: 12, gap: 10 },
  contextRow: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  contextSwatch: { width: 8, height: 8, borderRadius: 2 },
  contextRowLabel: { flex: 1, ...cardTypography.item },
  contextItemRow: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  contextItemLabel: { flex: 1, ...cardTypography.item },
  contextItemResolutions: { flexShrink: 1, textAlign: 'right', ...cardTypography.secondary },
  contextMore: { fontSize: 14 },
  contextItems: { gap: 10 },
  contextDivider: { height: 1, opacity: 0.4, marginBottom: 2 },
  copyMore: { paddingHorizontal: 16, paddingBottom: 16 },
  copyEpisodes: { marginHorizontal: 16, paddingTop: 12, paddingBottom: 16, borderTopWidth: StyleSheet.hairlineWidth, gap: 10 },
  copyEpisodesWeb: { marginHorizontal: 0, marginTop: 12 },
  copyList: { gap: 8 },
  entryGroupWebContent: { padding: 16 },
  entryGroupFlushY: { paddingVertical: 0 },
  copyTitleRow: { flexDirection: 'row', alignItems: 'center', flexWrap: 'wrap', gap: 6 },
  copyTitle: { ...cardTypography.rowTitle },
  copyDetail: { ...cardTypography.rowDetail },
  copyMeta: { ...cardTypography.rowMeta },
  copyActions: { flexDirection: 'row', gap: 2 },
  iconButton: { width: 32, height: 32, alignItems: 'center', justifyContent: 'center' },
  iconText: { fontSize: 17 },
  emptyCopy: { fontSize: 12, paddingVertical: 4 },
  editor: { gap: 14 },
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
  saveNote: { fontSize: 12, fontWeight: '600' },
  dialogFooter: { flexDirection: 'row', gap: 8, paddingTop: 12 },
  footerButton: { flex: 1 },
});
