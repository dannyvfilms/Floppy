import React, { useEffect, useMemo, useState } from 'react';
import {
  Pressable,
  StyleSheet,
  Switch,
  Text,
  TextInput,
  useWindowDimensions,
  View,
} from 'react-native';
import { Badge } from './Badge';
import { Button } from './Button.jsx';
import { CollectionEntryGroup, CollectionSectionHeading } from './CollectionCopies';
import { SelectField } from './SelectField';
import { Icon } from './Icon';
import { actionIcons } from './actionIcons';
import { cardTypography } from './cardTypography';

const FALLBACK_PALETTE = {
  surface: '#27272a',
  surfaceStrong: '#3f3f46',
  surfaceDim: '#1f1f23',
  border: '#3f3f46',
  text: '#fafafa',
  textSecondary: '#d4d4d8',
  textMuted: '#a1a1aa',
  accent: '#6366f1',
  accentStrong: '#4f46e5',
  accentText: '#ffffff',
  link: '#818cf8',
};

const DEFAULT_LABELS = {
  title: 'Calendar links',
  releasesHelp: 'Add this link to any calendar app to see upcoming releases there.',
  historyHelp: 'Add this link to any calendar app to see what you watched, read and played, on the day you logged it.',
  releasesTab: 'Upcoming releases',
  historyTab: 'Watch history',
  mediaTypes: 'Media Types',
  status: 'Status',
  releaseDates: 'Movie Release Dates',
  releaseMediaHelp: 'Choose which media types to include in this calendar URL.',
  historyMediaHelp: 'Music, podcasts and videos start off because they add many entries.',
  statusHelp: 'Choose which statuses to include in this calendar URL.',
  releaseDatesHelp: 'Choose which digital and physical release dates to include in this calendar URL.',
  subscription: 'Subscription link',
  ics: 'ICS',
  copy: 'Copy link',
  copied: 'Copied',
  download: 'Download calendar',
  unavailable: 'No calendar link is available.',
};

function mergePalette(palette) {
  return { ...FALLBACK_PALETTE, ...(palette || {}) };
}

function mergeLabels(labels) {
  return { ...DEFAULT_LABELS, ...(labels || {}) };
}

function valuesFor(items) {
  return (items || []).map((item) => item.value);
}

function selectedValues(value, available) {
  if (!Array.isArray(value)) {
    return [...available];
  }
  return value.filter((item) => available.includes(item));
}

function toggle(values, value) {
  return values.includes(value)
    ? values.filter((item) => item !== value)
    : [...values, value];
}

function encode(value) {
  return encodeURIComponent(String(value));
}

function withQuery(baseUrl, pairs) {
  if (!baseUrl) {
    return '';
  }
  const query = pairs
    .map(([key, value]) => `${encode(key)}=${encode(value)}`)
    .join('&');
  return query ? `${baseUrl}?${query}` : baseUrl;
}

export function releaseCalendarLinkUrl(baseUrl, {
  mediaTypes = [],
  statuses = [],
  releaseTypes = [],
  allReleaseTypes = [],
}) {
  const pairs = [];
  mediaTypes.forEach((value) => pairs.push(['media_types', value]));
  statuses.forEach((value) => pairs.push(['status', value]));
  if (releaseTypes.length < allReleaseTypes.length) {
    releaseTypes.forEach((value) => pairs.push(['release_types', value]));
    if (!releaseTypes.length) {
      pairs.push(['release_types', 'none']);
    }
  }
  return withQuery(baseUrl, pairs);
}

export function historyCalendarLinkUrl(baseUrl, { mediaTypes = [] }) {
  return withQuery(
    baseUrl,
    mediaTypes.length
      ? mediaTypes.map((value) => ['media_types', value])
      : [['media_types', 'none']],
  );
}

export function CalendarLinks({
  sessionRequired = false,
  initialFeed = 'releases',
  releaseMediaTypes = [],
  historyMediaTypes = [],
  statuses = [],
  releaseTypes = [],
  initialReleaseMediaTypes,
  initialHistoryMediaTypes,
  initialStatuses,
  initialReleaseTypes,
  releaseBaseUrl = '',
  historyBaseUrl = '',
  labels,
  palette,
  embedded = false,
  renderFeedPicker,
  onFeedChange,
  onSelectionChange,
  onCopyLink,
  onDownload,
}) {
  const { width } = useWindowDimensions();
  const colors = mergePalette(palette);
  const copy = mergeLabels(labels);
  const wide = width >= 768;
  const grouped = !embedded || !wide;
  const styles = useMemo(() => createStyles(colors, wide, embedded), [colors, width, embedded]);
  const releaseTypeValues = useMemo(() => valuesFor(releaseMediaTypes), [releaseMediaTypes]);
  const historyTypeValues = useMemo(() => valuesFor(historyMediaTypes), [historyMediaTypes]);
  const statusValues = useMemo(() => valuesFor(statuses), [statuses]);
  const allReleaseTypeValues = useMemo(() => valuesFor(releaseTypes), [releaseTypes]);

  const [feed, setFeed] = useState(initialFeed === 'history' ? 'history' : 'releases');
  const [releaseTypesSelection, setReleaseTypesSelection] = useState(() =>
    selectedValues(initialReleaseMediaTypes, releaseTypeValues),
  );
  const [historyTypesSelection, setHistoryTypesSelection] = useState(() =>
    selectedValues(initialHistoryMediaTypes, historyTypeValues),
  );
  const [statusesSelection, setStatusesSelection] = useState(() =>
    selectedValues(initialStatuses, statusValues),
  );
  const [datesSelection, setDatesSelection] = useState(() =>
    selectedValues(initialReleaseTypes, allReleaseTypeValues),
  );
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!copied) {
      return undefined;
    }
    const timer = setTimeout(() => setCopied(false), 2000);
    return () => clearTimeout(timer);
  }, [copied]);

  const exportUrl = feed === 'history'
    ? historyCalendarLinkUrl(historyBaseUrl, { mediaTypes: historyTypesSelection })
    : releaseCalendarLinkUrl(releaseBaseUrl, {
      mediaTypes: releaseTypesSelection,
      statuses: statusesSelection,
      releaseTypes: datesSelection,
      allReleaseTypes: allReleaseTypeValues,
    });

  function selectionState(next = {}) {
    return {
      feed,
      releaseMediaTypes: releaseTypesSelection,
      historyMediaTypes: historyTypesSelection,
      statuses: statusesSelection,
      releaseTypes: datesSelection,
      ...next,
    };
  }

  function changeFeed(value) {
    if (value === feed) {
      return;
    }
    setFeed(value);
    setCopied(false);
    onFeedChange?.(selectionState({ feed: value }));
  }

  function changeSelection(key, next, notify = selectionState()) {
    if (key === 'releaseMediaTypes') {
      setReleaseTypesSelection(next);
    } else if (key === 'historyMediaTypes') {
      setHistoryTypesSelection(next);
    } else if (key === 'statuses') {
      setStatusesSelection(next);
    } else if (key === 'releaseTypes') {
      setDatesSelection(next);
    }
    setCopied(false);
    onSelectionChange?.(notify);
  }

  async function copyLink() {
    if (!exportUrl || !onCopyLink) {
      return;
    }
    try {
      await onCopyLink(exportUrl);
      setCopied(true);
    } catch (error) {
      setCopied(false);
    }
  }

  const feedOptions = [
    { value: 'releases', label: copy.releasesTab },
    { value: 'history', label: copy.historyTab },
  ];
  const pickerOptions = [
    { value: 'releases', label: 'Upcoming Releases', displayLabel: 'Upcoming' },
    { value: 'history', label: 'Watch History', displayLabel: 'History' },
  ];
  const selectedPicker = pickerOptions.find(option => option.value === feed);
  const mediaOptions = feed === 'history' ? historyMediaTypes : releaseMediaTypes;
  const selectedMedia = feed === 'history' ? historyTypesSelection : releaseTypesSelection;

  const badgePalette = {
    outline: {
      color: colors.textSecondary,
      borderColor: colors.border,
      borderWidth: 1,
    },
  };

  if (sessionRequired) return <View style={styles.card}>
    <Text style={styles.title}>{copy.title}</Text>
    <Text style={styles.help}>Sign in with your username and password to manage this.</Text>
  </View>;

  // Expo and mobile web share the grouped-card layout (Collection sheet pattern);
  // desktop web keeps its original single card with tabs.
  if (grouped) {
    const variant = embedded ? 'web' : 'native';
    const group = (title, children) => <View style={styles.newSection}>
      {title ? <CollectionSectionHeading title={title} palette={colors} variant={variant} /> : null}
      <CollectionEntryGroup palette={colors} variant={variant}>
        <View style={styles.newCard}>{children}</View>
      </CollectionEntryGroup>
    </View>;
    const withDividers = rows => rows.map((row, index) => <View key={row.key}>
      {index ? <View style={styles.rowDivider} /> : null}
      {row}
    </View>);
    const switchRow = (key, item, selection, onToggle) => <View key={key} style={styles.switchRow}>
      <View style={styles.rowLabel}>
        {item.icon ? <Icon spec={item.icon} color={colors.textMuted} size={20} /> : null}
        <Text style={styles.pickerLabel}>{item.label}</Text>
      </View>
      <View style={styles.switchSlot}><Switch accessibilityLabel={item.label} value={selection.includes(item.value)}
        // Web matches the desktop OptionSwitch colors; Expo keeps the system switch look.
        trackColor={embedded ? { false: colors.surfaceDim, true: colors.accentStrong } : { false: colors.surfaceStrong, true: colors.accent }}
        thumbColor={embedded ? (selection.includes(item.value) ? colors.accentText : colors.textSecondary) : '#ffffff'}
        activeThumbColor={embedded ? colors.accentText : '#ffffff'}
        onValueChange={onToggle} /></View>
    </View>;
    const switchRows = (items, selection, key) => withDividers(items.map(item => switchRow(item.value, item, selection, () => {
      const next = toggle(selection, item.value);
      changeSelection(key, next, selectionState({ [key]: next }));
    })));
    const actionRow = (key, label, trailing, icon, onPress) => <Pressable key={key} accessibilityRole="button"
      accessibilityLabel={label} onPress={onPress} style={({ pressed }) => [styles.switchRow, pressed && styles.pressed]}>
      <View style={styles.rowLabel}>
        <Icon spec={icon} color={colors.textMuted} size={20} />
        <Text style={styles.pickerLabel}>{label}</Text>
      </View>
      <Text style={styles.pickerValue}>{trailing}</Text>
    </Pressable>;
    const mediaKey = feed === 'history' ? 'historyMediaTypes' : 'releaseMediaTypes';
    const actions = [
      onCopyLink && exportUrl ? actionRow('copy', 'Copy Calendar', copied ? 'Copied' : 'Copy', actionIcons.link, copyLink) : null,
      onDownload && exportUrl ? actionRow('download', 'Download Calendar', 'Download', actionIcons.download, () => onDownload(exportUrl)) : null,
    ].filter(Boolean);
    return <View style={styles.linksStack}>
      {group('Calendar Links', <View style={styles.switchRow}>
        <View style={styles.rowLabel}>
          <Icon spec={actionIcons.calendar} color={colors.textMuted} size={20} />
          <Text numberOfLines={1} style={styles.pickerLabel}>Calendar Type</Text>
        </View>
        {renderFeedPicker ? renderFeedPicker({ value: feed, options: pickerOptions, onChange: changeFeed, palette: colors }) : <SelectField label="Calendar Type" labelHidden value={feed} options={pickerOptions} displayValue={selectedPicker.displayLabel} palette={colors}
          accessibilityLabel={`Calendar Type: ${selectedPicker.label}`}
          onChange={event => changeFeed(event.target.value)} popover
          triggerStyle={styles.pickerTrigger} triggerTextStyle={styles.pickerValue}
          indicator={<Text style={styles.pickerIndicator}>⌃{'\n'}⌄</Text>} />}
      </View>)}
      {group('Media Types', switchRows(mediaOptions, selectedMedia, mediaKey))}
      {feed === 'releases' && statuses.length ? group('Status', switchRows(statuses, statusesSelection, 'statuses')) : null}
      {feed === 'releases' && releaseTypes.length ? group('Release Dates', switchRows(releaseTypes, datesSelection, 'releaseTypes')) : null}
      {actions.length ? group(copy.ics, withDividers(actions)) : null}
    </View>;
  }

  return <View style={styles.card}>
    <Text style={styles.title}>{copy.title}</Text>
    <Text style={styles.help}>{feed === 'history' ? copy.historyHelp : copy.releasesHelp}</Text>

    <View style={styles.tabs} accessibilityRole="tablist">
      {feedOptions.map((option) => <Pressable
        key={option.value}
        accessibilityRole="tab"
        accessibilityLabel={option.label}
        accessibilityState={{ selected: feed === option.value }}
        onPress={() => changeFeed(option.value)}
        style={({ pressed }) => [
          styles.tab,
          feed === option.value && styles.tabSelected,
          pressed && styles.pressed,
        ]}>
        <Text style={[styles.tabText, feed === option.value && styles.tabTextSelected]}>
          {option.label}
        </Text>
      </Pressable>)}
    </View>

    {feed === 'history' ? <View style={styles.section}>
      <Text style={styles.sectionTitle}>{copy.mediaTypes}</Text>
      <Text style={styles.sectionHelp}>{copy.historyMediaHelp}</Text>
      <View style={styles.options}>
        {historyMediaTypes.map((item) => <OptionSwitch
          key={item.value}
          label={item.label}
          checked={historyTypesSelection.includes(item.value)}
          styles={styles}
          onPress={() => {
            const next = toggle(historyTypesSelection, item.value);
            changeSelection('historyMediaTypes', next, selectionState({
              historyMediaTypes: next,
            }));
          }} />)}
      </View>
    </View> : <View style={styles.releaseSections}>
      <View style={styles.section}>
        <Text style={styles.sectionTitle}>{copy.mediaTypes}</Text>
        <Text style={styles.sectionHelp}>{copy.releaseMediaHelp}</Text>
        <View style={styles.options}>
          {releaseMediaTypes.map((item) => <OptionSwitch
            key={item.value}
            label={item.label}
            checked={releaseTypesSelection.includes(item.value)}
            styles={styles}
            onPress={() => {
              const next = toggle(releaseTypesSelection, item.value);
              changeSelection('releaseMediaTypes', next, selectionState({
                releaseMediaTypes: next,
              }));
            }} />)}
        </View>
      </View>

      <View style={styles.section}>
        <Text style={styles.sectionTitle}>{copy.status}</Text>
        <Text style={styles.sectionHelp}>{copy.statusHelp}</Text>
        <View style={styles.options}>
          {statuses.map((item) => <OptionSwitch
            key={item.value}
            label={item.label}
            checked={statusesSelection.includes(item.value)}
            styles={styles}
            onPress={() => {
              const next = toggle(statusesSelection, item.value);
              changeSelection('statuses', next, selectionState({ statuses: next }));
            }} />)}
        </View>
      </View>

      {releaseTypes.length ? <View style={styles.section}>
        <Text style={styles.sectionTitle}>{copy.releaseDates}</Text>
        <Text style={styles.sectionHelp}>{copy.releaseDatesHelp}</Text>
        <View style={styles.options}>
          {releaseTypes.map((item) => <OptionSwitch
            key={item.value}
            label={item.label}
            checked={datesSelection.includes(item.value)}
            styles={styles}
            onPress={() => {
              const next = toggle(datesSelection, item.value);
              changeSelection('releaseTypes', next, selectionState({ releaseTypes: next }));
            }} />)}
        </View>
      </View> : null}
    </View>}

    <View style={styles.urlBlock}>
      {!embedded ? <View style={styles.urlHeader}>
        <Badge label={copy.ics} tone="outline" palette={badgePalette} />
        <Text style={styles.urlLabel}>{copy.subscription}</Text>
      </View> : null}
      {exportUrl ? <TextInput
        editable={false}
        numberOfLines={1}
        value={exportUrl}
        accessibilityLabel={copy.subscription}
        style={styles.urlText} />
        : <Text style={styles.sectionHelp}>{copy.unavailable}</Text>}
      {!embedded ? <View style={styles.urlActions}>
        {onCopyLink && exportUrl ? <Button
          label={copied ? copy.copied : copy.copy}
          tone={copied ? 'surface' : 'primary'}
          onPress={copyLink} /> : null}
        {onDownload && exportUrl ? <Button
          label={copy.download}
          tone="surface"
          onPress={() => onDownload(exportUrl)} /> : null}
      </View> : null}
    </View>
  </View>;
}

function OptionSwitch({ label, checked, onPress, styles }) {
  return <Pressable
    accessibilityRole="switch"
    accessibilityLabel={label}
    accessibilityState={{ checked }}
    onPress={onPress}
    style={({ pressed }) => [styles.option, pressed && styles.pressed]}>
    <Text style={styles.optionLabel}>{label}</Text>
    <View style={[styles.track, checked && styles.trackChecked]}>
      <View style={[styles.thumb, checked && styles.thumbChecked]} />
    </View>
  </Pressable>;
}

function createStyles(colors, wide, embedded) {
  const optionWidth = wide ? '32%' : '100%';
  return StyleSheet.create({
    linksStack: { gap: 20 },
    newSection: { gap: 10 },
    // Rows carry their own 50pt height; only Expo needs side inset (web's surface already pads 0).
    newCard: { paddingHorizontal: embedded ? 0 : 16 },
    rowLabel: { flexDirection: 'row', alignItems: 'center', gap: 8, flexShrink: 1 },
    pickerLabel: { color: colors.text, ...cardTypography.title, flexShrink: 1 },
    rowDivider: { marginLeft: 28, height: 1, backgroundColor: colors.textMuted, opacity: 0.4 },
    switchRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 12, minHeight: 50 },
    switchSlot: { height: 50, justifyContent: 'center', alignItems: 'center' },
    pickerTrigger: { borderWidth: 0, backgroundColor: 'transparent', paddingHorizontal: 0, paddingVertical: 0 },
    pickerValue: { color: colors.textSecondary, fontSize: 16 },
    pickerIndicator: { color: colors.textMuted, fontSize: 13, lineHeight: 8, textAlign: 'center' },
    card: embedded ? {
      gap: 12,
    } : {
      gap: 12,
      padding: 16,
      borderRadius: 10,
      backgroundColor: colors.surface,
      borderWidth: 1,
      borderColor: colors.border,
    },
    title: { color: colors.text, fontSize: 16, fontWeight: '500', lineHeight: 24 },
    help: { color: colors.textMuted, fontSize: 14, lineHeight: 20 },
    sectionHelp: { color: colors.textMuted, fontSize: 12, lineHeight: 16 },
    tabs: {
      flexDirection: 'row',
      alignSelf: 'flex-start',
      gap: 4,
      padding: 4,
      borderRadius: 8,
      backgroundColor: colors.surfaceStrong,
    },
    tab: {
      minHeight: 32,
      paddingHorizontal: 12,
      alignItems: 'center',
      justifyContent: 'center',
      borderRadius: 6,
    },
    tabSelected: { backgroundColor: colors.accentStrong },
    tabText: { color: colors.textSecondary, fontSize: 13, fontWeight: '600' },
    tabTextSelected: { color: colors.accentText },
    releaseSections: { gap: 16, marginTop: 4 },
    section: { gap: 12 },
    sectionTitle: { color: colors.textSecondary, fontSize: 14, lineHeight: 20, fontWeight: '600' },
    options: { flexDirection: 'row', flexWrap: 'wrap', gap: 12 },
    option: {
      width: optionWidth,
      minHeight: 44,
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'space-between',
      gap: 8,
      paddingHorizontal: 10,
      paddingVertical: 8,
      borderRadius: 8,
      backgroundColor: colors.surfaceStrong,
    },
    optionLabel: { flexShrink: 1, color: colors.textSecondary, fontSize: 13 },
    track: {
      width: 36,
      height: 20,
      borderRadius: 10,
      padding: 2,
      justifyContent: 'center',
      backgroundColor: colors.surfaceDim,
    },
    trackChecked: { backgroundColor: colors.accentStrong },
    thumb: {
      width: 16,
      height: 16,
      borderRadius: 8,
      backgroundColor: colors.textSecondary,
    },
    thumbChecked: { alignSelf: 'flex-end', backgroundColor: colors.accentText },
    urlBlock: {
      gap: 8,
      marginTop: 4,
      marginBottom: embedded ? 16 : 0,
      padding: 12,
      borderRadius: 8,
      backgroundColor: colors.surfaceDim,
    },
    urlHeader: { flexDirection: 'row', alignItems: 'center', gap: 6 },
    urlLabel: { color: colors.textSecondary, fontSize: 12, fontWeight: '600' },
    urlText: {
      color: colors.textSecondary,
      fontSize: 14,
      lineHeight: 20,
      paddingVertical: 8,
      paddingHorizontal: 0,
      fontFamily: 'monospace',
    },
    urlActions: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
    pressed: { opacity: 0.72 },
  });
}
