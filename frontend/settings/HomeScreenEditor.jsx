import React, { useEffect, useMemo, useState } from 'react';
import { Pressable, StyleSheet, Text, TextInput, View } from 'react-native';
import { FormSaveBar } from '../ui/FormSaveBar';
import { SelectField } from '../ui/SelectField';
import { ToggleChip } from '../ui/ToggleChip';
import { ReorderList } from '../ui/ReorderList';
import { Icon } from '../ui/Icon';
import { actionIcons } from '../ui/actionIcons';
import { ConfirmDialog } from './ConfirmDialog';
import { Button } from '../ui/Button';

const defaultPalette = {
  background: '#18181b',
  surface: '#27272a',
  surfaceStrong: '#3f3f46',
  surfaceMuted: '#52525b',
  border: '#52525b',
  text: '#fafafa',
  textSecondary: '#d4d4d8',
  textMuted: '#a1a1aa',
  accent: '#6366f1',
  accentStrong: '#4f46e5',
  accentText: '#ffffff',
  warning: '#f59e0b',
  danger: '#ef4444',
};

const defaultButtonPalette = {
  primary: { background: '#4f46e5', pressed: '#4338ca', hovered: '#4338ca', text: '#ffffff', border: 'transparent' },
  surface: { background: '#3f3f46', pressed: '#52525b', hovered: '#52525b', text: '#fafafa', border: '#3f3f46' },
  danger: { background: '#dc2626', pressed: '#b91c1c', hovered: '#b91c1c', text: '#ffffff', border: 'transparent' },
  radius: 6,
};

const defaultLabels = {
  title: 'Home screen',
  copy: 'These groups are the rows on the home screen. Expand a group to edit its rows.',
  preview: 'Preview',
  expand: 'Expand section',
  collapse: 'Collapse section',
  reorderSection: 'Reorder section',
  moveUp: 'Move up',
  moveDown: 'Move down',
  labelColor: 'label color',
  noRows: 'No Home rows configured yet for this library.',
  rowName: 'Row name',
  renameRow: 'Rename this row',
  allItems: 'All items',
  filters: 'Filters',
  settings: 'Row settings',
  all: 'All',
  active: 'Active',
  any: 'Any',
  status: 'Status',
  sort: 'Sort',
  ascending: 'Ascending',
  descending: 'Descending',
  addRow: 'Add Row',
  libraryRow: 'Library Row',
  lastWatched: 'Last Watched',
  upNext: 'Up Next',
  recentlyPlayed: 'Recently Played Row',
  addList: 'Add List',
  deleteRow: 'Delete row',
  listSelection: 'List Selection',
  listHelp: 'Search your owned and collaborator lists. Smart lists are included here too.',
  searchLists: 'Search lists and smart lists',
  selected: 'Selected:',
  noList: 'No list selected yet',
  smartList: 'Smart list',
  manualList: 'Manual list',
  mediaTypeHeaders: 'Media Type Headers',
  mediaTypeHeadersHelp: 'Show an icon and media type above each group of Home rows.',
  toggleHeaders: 'Toggle media type headers',
  mediaTypeLabels: 'Media Type Labels',
  mediaTypeLabelsHelp: 'Show labels on posters in Home rows that mix media types.',
  toggleLabels: 'Toggle media type labels',
  labelAppearance: 'Label appearance',
  save: 'Save Home Screen',
  saving: 'Saving…',
  savedTitle: 'All changes saved',
  savedCopy: 'Your Home screen is up to date.',
  dirtyTitle: 'Unsaved changes',
  dirtyCopy: 'Save your Home screen to keep your changes.',
  savingTitle: 'Saving Home screen',
  savingCopy: 'Applying your Home rows…',
  errorTitle: 'Could not save Home screen',
  saveError: 'Check the highlighted rows and try again.',
  validationError: 'Some Home rows need attention.',
  listError: 'Choose a list for each List row.',
  tagMode: 'Tag mode',
};

function sameValues(left, right) {
  return JSON.stringify(left) === JSON.stringify(right);
}

function asList(value) {
  if (Array.isArray(value)) return value;
  return value === null || value === undefined || value === '' ? [] : [value];
}

function defaultSortDirection(value) {
  return ['author', 'popularity', 'runtime', 'start_date', 'title', 'time_left', 'time_to_beat', 'episode_feed'].includes(value) ? 'asc' : 'desc';
}

function mediaSubviewDefaults(mediaType) {
  if (mediaType === 'music') return 'tracks';
  if (mediaType === 'podcast') return 'shows';
  return null;
}

function rowStatusValues(row) {
  return asList(row.filters?.status).filter(value => value && value !== 'all');
}

function rowTagValues(row) {
  return asList(row.filters?.tag).filter(value => value);
}

function rowMediaTypeValues(row) {
  return asList(row.filters?.media_types).filter(value => value);
}

function rowFilterPills(section, row) {
  if (row.row_type !== 'library_query') return [];
  const pills = [];
  const fieldDefinition = key => (section.filter_fields || []).find(field => field.key === key) || null;
  const optionLabel = (key, value) => {
    const field = fieldDefinition(key);
    return (field?.options || []).find(option => String(option.value) === String(value))?.label || value;
  };
  const addPill = (key, values) => {
    if (!values.length) return;
    const field = fieldDefinition(key);
    pills.push({ key, label: field?.label || key, value: values.map(value => optionLabel(key, value)).join(', ') });
  };
  if (section.media_type === 'all') {
    const selected = rowMediaTypeValues(row);
    const mediaField = fieldDefinition('media_types');
    if (!selected.length) pills.push({ key: 'media_types', label: mediaField?.label || 'Media types', value: 'No media' });
    else if (selected.length !== (mediaField?.options?.length || 0)) addPill('media_types', selected);
  }
  addPill('status', rowStatusValues(row));
  if (section.media_type === 'music') addPill('subview', [row.filters?.subview || 'tracks']);
  ['progress', 'rating', 'collection', 'genre', 'year', 'release', 'source', 'language', 'country', 'platform', 'origin', 'format', 'author', 'provider'].forEach(key => {
    const value = row.filters?.[key];
    if (value && value !== 'all') addPill(key, [value]);
  });
  const tags = rowTagValues(row);
  if (tags.length) {
    const mode = row.filters?.tag_mode || 'or';
    pills.push({
      key: 'tag',
      label: mode === 'not' ? 'Not tagged' : 'Tags',
      value: tags.join(mode === 'and' ? ' & ' : ' or '),
    });
  }
  return pills;
}

function rowAutoTitle(section, row) {
  if (row.row_type === 'up_next') return 'Up Next';
  if (row.row_type === 'custom_list') return row.custom_list_name || 'List / Smart List';
  if (row.row_type === 'recently_unrated') return 'Recently Played - Not Rated';
  const statuses = rowStatusValues(row);
  const statusField = (section.filter_fields || []).find(field => field.key === 'status');
  const first = statuses.length === 1
    ? (statusField?.options || []).find(option => String(option.value) === String(statuses[0]))?.label || statuses[0]
    : (statuses.length > 1 ? `${statuses.length} Statuses` : 'Library');
  const parts = [first];
  const subview = mediaSubviewDefaults(section.media_type);
  if (subview) {
    const value = row.filters?.subview || subview;
    const field = (section.filter_fields || []).find(candidate => candidate.key === 'subview');
    const label = field?.options?.find(option => option.value === value)?.label || value;
    if (first === 'Library') parts[0] = label;
    else parts.push(label);
  }
  rowFilterPills(section, row).filter(pill => !['status', 'media_types', 'subview'].includes(pill.key))
    .forEach(pill => parts.push(pill.key === 'tag' && row.filters?.tag_mode === 'not' ? `Not tagged ${pill.value}` : pill.value));
  return parts.slice(0, 4).join(' • ');
}

function rowPlaceholder(section, row) {
  if ((section.filter_fields || []).length) return rowAutoTitle(section, row);
  return row.title || rowAutoTitle(section, row);
}

function sectionPreview(section) {
  return (section.rows || [])
    .map(row => (row.custom_title || '').trim() || rowPlaceholder(section, row))
    .filter(Boolean)
    .join(', ');
}

/**
 * Shared Home screen shelf editor. Sections and rows are data-driven; the
 * caller owns transport, list search results, validation and persistence.
 */
export function HomeScreenEditor({
  dragIcon,
  sections = [],
  initialSections,
  listChoices = [],
  mediaTypeChipStyles = [],
  showMediaTypeHeaders = false,
  mediaTypeChipsEnabled = false,
  mediaTypeChipStyle,
  segmentedAppearance = false,
  onChange,
  onSave,
  validate,
  labels,
  palette = {},
  buttonPalette = {},
  disabled = false,
}) {
  const copy = { ...defaultLabels, ...labels };
  const colors = { ...defaultPalette, ...palette };
  const values = {
    sections,
    showMediaTypeHeaders: Boolean(showMediaTypeHeaders),
    mediaTypeChipsEnabled: Boolean(mediaTypeChipsEnabled),
    mediaTypeChipStyle: mediaTypeChipStyle || mediaTypeChipStyles[0]?.value || '',
  };
  const serialized = useMemo(() => JSON.stringify(values), [sections, showMediaTypeHeaders, mediaTypeChipsEnabled, mediaTypeChipStyle]);
  const baseline = {
    sections: initialSections || sections,
    showMediaTypeHeaders: Boolean(showMediaTypeHeaders),
    mediaTypeChipsEnabled: Boolean(mediaTypeChipsEnabled),
    mediaTypeChipStyle: mediaTypeChipStyle || mediaTypeChipStyles[0]?.value || '',
  };
  const dirty = useMemo(() => !sameValues(values, baseline), [sections, showMediaTypeHeaders, mediaTypeChipsEnabled, mediaTypeChipStyle]);
  const [expanded, setExpanded] = useState({});
  const [colorEditor, setColorEditor] = useState(null);
  const [rowEditors, setRowEditors] = useState({});
  const [listSearch, setListSearch] = useState({});
  const [nextRowId, setNextRowId] = useState(() => sections.reduce((maxId, section) => Math.max(maxId, ...(section.rows || []).map(row => Number.parseInt(String(row.id || '0'), 10) || 0)), 0) + 1);
  const [saving, setSaving] = useState(false);
  const [localErrors, setLocalErrors] = useState({});
  const [localError, setLocalError] = useState('');
  const chipStyle = values.mediaTypeChipStyle;

  useEffect(() => {
    setLocalError('');
    setLocalErrors({});
  }, [serialized]);

  function update(nextSections, next = {}) {
    onChange?.({
      sections: nextSections,
      showMediaTypeHeaders: next.showMediaTypeHeaders ?? values.showMediaTypeHeaders,
      mediaTypeChipsEnabled: next.mediaTypeChipsEnabled ?? values.mediaTypeChipsEnabled,
      mediaTypeChipStyle: next.mediaTypeChipStyle ?? values.mediaTypeChipStyle,
    });
  }

  function copySections() {
    return sections.map(section => ({ ...section, rows: (section.rows || []).map(row => ({ ...row, filters: { ...(row.filters || {}) } })) }));
  }

  function updateRow(sectionIndex, rowIndex, mutate) {
    const next = copySections();
    const section = next[sectionIndex];
    if (!section?.rows?.[rowIndex]) return;
    mutate(section.rows[rowIndex], section);
    update(next);
  }

  function setRowFilter(row, key, value) {
    row.filters = { ...(row.filters || {}), [key]: value };
  }

  function toggleArrayFilter(row, key, value) {
    const valuesList = asList(row.filters?.[key]).filter(item => item && item !== 'all');
    row.filters = row.filters || {};
    row.filters[key] = valuesList.includes(value) ? valuesList.filter(item => item !== value) : [...valuesList, value];
  }

  function toggleStatus(row, value) {
    if (value === 'all' || value === 'All') {
      row.filters = { ...(row.filters || {}), status: [] };
      return;
    }
    toggleArrayFilter(row, 'status', value);
  }

  function setMediaSubview(row, family, value) {
    row.filters = row.filters || {};
    row.filters.media_subviews = { ...(row.filters.media_subviews || {}), [family]: value };
    const mediaTypes = rowMediaTypeValues(row);
    if (!mediaTypes.includes(family)) row.filters.media_types = [...mediaTypes, family];
  }

  function cycleTagMode(row) {
    const current = row.filters?.tag_mode || 'or';
    row.filters = { ...(row.filters || {}), tag_mode: current === 'and' ? 'or' : (current === 'or' ? 'not' : 'and') };
  }

  function defaultFilters(section, rowType) {
    if (rowType !== 'library_query') return {};
    const defaults = {
      status: ['In progress'],
      progress: ['all', 'tv', 'anime'].includes(section.media_type) ? 'not_caught_up' : 'all',
      rating: 'all',
      collection: 'all',
      genre: '',
      year: '',
      release: 'all',
      source: '',
      language: '',
      country: '',
      platform: '',
      origin: '',
      format: '',
      author: '',
      tag: [],
      tag_mode: 'or',
    };
    const subview = mediaSubviewDefaults(section.media_type);
    if (subview) defaults.subview = subview;
    if (section.media_type === 'all') {
      const mediaField = (section.filter_fields || []).find(field => field.key === 'media_types');
      defaults.media_types = (mediaField?.options || (section.available_media_types || []).map(value => ({ value }))).map(option => option.value);
    }
    return defaults;
  }

  function defaultSortValue(section, rowType) {
    if (rowType === 'recently_unrated') return 'recent';
    if (rowType === 'up_next') return 'episode_feed';
    const choices = rowType === 'custom_list'
      ? (section.sort_choices?.custom_list || [])
      : (section.sort_choices?.library_query || []);
    if (rowType === 'library_query' && ['tv', 'anime'].includes(section.media_type)) {
      const preferred = choices.find(choice => choice.value === 'next_episode_air_date');
      if (preferred) return preferred.value;
    }
    return choices[0]?.value || 'title';
  }

  function sortChoices(section, row) {
    if (row.row_type === 'custom_list') return section.sort_choices?.custom_list || [];
    if (row.row_type === 'up_next') return section.sort_choices?.up_next || [];
    return section.sort_choices?.library_query || [];
  }

  function sortLabel(section, row) {
    return sortChoices(section, row).find(choice => choice.value === row.sort_by)?.label || copy.sort;
  }

  function chooseSort(section, row, value) {
    if (row.sort_by === value) row.direction = row.direction === 'asc' ? 'desc' : 'asc';
    else {
      row.sort_by = value;
      row.direction = defaultSortDirection(value);
    }
  }

  function addRow(sectionIndex, requestedType) {
    const next = copySections();
    const section = next[sectionIndex];
    if (!section) return;
    let rowType = requestedType;
    if (rowType === 'recently_unrated' && (section.rows || []).some(row => row.row_type === 'recently_unrated')) return;
    const lastWatched = rowType === 'last_watched';
    if (lastWatched) rowType = 'library_query';
    const defaultSort = lastWatched ? 'end_date' : defaultSortValue(section, rowType);
    const newRow = {
      id: null,
      client_id: `new-row-${nextRowId}`,
      enabled: true,
      custom_title: '',
      row_type: rowType,
      custom_list_id: null,
      custom_list_name: '',
      sort_by: rowType === 'recently_unrated' ? 'recent' : defaultSort,
      direction: rowType === 'recently_unrated' ? 'desc' : defaultSortDirection(defaultSort),
      recent_show: 'album',
      filters: defaultFilters(section, rowType),
      editorOpen: rowType === 'custom_list',
    };
    if (lastWatched) {
      newRow.custom_title = copy.lastWatched;
      newRow.filters.media_types = (section.available_media_types || []).filter(type => ['movie', 'tv'].includes(type));
      newRow.filters.status = ['In progress', 'Completed', 'Paused', 'Dropped'];
      newRow.filters.progress = 'all';
    }
    section.rows = [...(section.rows || []), newRow];
    setNextRowId(current => current + 1);
    setRowEditors(current => ({ ...current, [newRow.client_id]: rowType === 'custom_list' }));
    update(next);
  }

  function removeRow(sectionIndex, clientId) {
    const next = copySections();
    next[sectionIndex].rows = (next[sectionIndex].rows || []).filter(row => row.client_id !== clientId);
    update(next);
  }

  function reorderSection(index, direction) {
    const target = index + direction;
    if (target < 0 || target >= sections.length) return;
    const next = [...sections];
    next.splice(target, 0, next.splice(index, 1)[0]);
    update(next);
  }

  function reorderRow(sectionIndex, rowIndex, direction) {
    const next = copySections();
    const rows = next[sectionIndex].rows;
    const target = rowIndex + direction;
    if (target < 0 || target >= rows.length) return;
    rows.splice(target, 0, rows.splice(rowIndex, 1)[0]);
    update(next);
  }

  function toggleExpanded(mediaType) {
    setExpanded(current => ({ ...current, [mediaType]: !current[mediaType] }));
  }

  function toggleRowEditor(clientId) {
    setRowEditors(current => ({ ...current, [clientId]: !current[clientId] }));
  }

  function setSectionColor(sectionIndex, color) {
    const next = copySections();
    next[sectionIndex].media_type_chip_color = color;
    update(next);
  }

  function validateValues(nextSections = sections) {
    if (validate) return validate({ ...values, sections: nextSections }) || {};
    const problems = {};
    nextSections.forEach(section => {
      (section.rows || []).forEach(row => {
        if (row.row_type === 'custom_list' && !row.custom_list_id) problems.lists = copy.listError;
        if (String(row.custom_title || '').length > 100) problems.titles = 'Row names are limited to 100 characters.';
      });
    });
    return problems;
  }

  function submitPayload(nextSections = sections) {
    return nextSections.map(section => ({
      media_type: section.media_type,
      rows: (section.rows || []).map(row => ({
        id: row.id,
        enabled: true,
        custom_title: row.custom_title || '',
        row_type: row.row_type,
        custom_list_id: row.custom_list_id,
        sort_by: row.sort_by,
        direction: row.direction,
        recent_show: row.recent_show || 'album',
        filters: row.filters || {},
      })),
    }));
  }

  async function save() {
    if (saving || disabled) return;
    const problems = validateValues(sections);
    if (Object.keys(problems).length) {
      setLocalErrors(problems);
      setLocalError(copy.validationError);
      return;
    }
    setLocalErrors({});
    setLocalError('');
    setSaving(true);
    try {
      await onSave?.({ values, payload: submitPayload(sections) });
    } catch (reason) {
      setLocalError(reason?.message || copy.saveError);
    } finally {
      setSaving(false);
    }
  }

  const statusOptions = section => (section.filter_fields || []).find(field => field.key === 'status')?.options || [];
  const filterFields = section => (section.filter_fields || []).filter(field => field.key !== 'status');
  const canAddLastWatched = section => section.media_type === 'all' && (section.available_media_types || []).some(type => ['movie', 'tv'].includes(type));
  const canAddUpNext = section => section.media_type === 'tv' || (section.media_type === 'all' && (section.available_media_types || []).includes('tv'));
  const canAddRecent = section => section.media_type !== 'all' && !(section.rows || []).some(row => row.row_type === 'recently_unrated');

  return <View style={[styles.form, colors.pageCards && { padding: 24, backgroundColor: colors.surface, borderRadius: 8 }]}>
    {copy.copy ? <Text style={[styles.help, { color: colors.textMuted }, colors.pageCards && { fontSize: 14, lineHeight: 20 }]}>{copy.copy}</Text> : null}
    {localErrors.lists ? <Text accessibilityRole="alert" style={[styles.help, { color: colors.danger }]}>{localErrors.lists}</Text> : null}

    <ReorderList items={sections} keyForItem={section => section.media_type} labelForItem={section => section.label}
      icon={dragIcon} palette={colors} disabled={disabled || saving} gap={colors.pageCards ? 4 : 12}
      onMove={(from, to) => reorderSection(from, to - from)}
      renderItem={(section, sectionIndex, sectionHandle) => {
      const isExpanded = Boolean(expanded[section.media_type]);
      return <View key={section.media_type} style={[styles.sectionCard, { borderColor: colors.pageCards ? colors.fieldBorder : colors.border, backgroundColor: colors.surface }, colors.pageCards && { borderRadius: 12 }]}>
        <View style={[styles.sectionHeader, colors.pageCards && { paddingHorizontal: 12, paddingVertical: 8, minHeight: 60, gap: 12 }]}>
          {sectionHandle}
          {section.icon && colors.pageCards ? <Icon spec={section.icon} color={colors.textSecondary} size={20} /> : null}
          <Pressable
            accessibilityRole="button"
            accessibilityLabel={`${isExpanded ? copy.collapse : copy.expand}: ${section.label}`}
            accessibilityState={{ expanded: isExpanded }}
            onPress={() => toggleExpanded(section.media_type)}
            style={styles.sectionGrow}>
            <Text style={[styles.sectionName, { color: colors.text }]}>{section.label || section.media_type}</Text>
            {!isExpanded && section.rows?.length ? <Text numberOfLines={1} style={[styles.sectionPreview, { color: colors.textMuted }]}>{sectionPreview(section)}</Text> : null}
          </Pressable>
          {section.media_type_chip_color && colors.pageCards ? <Pressable accessibilityRole="button" accessibilityLabel={`${section.label} ${copy.labelColor}`}
            disabled={disabled} onPress={() => setColorEditor({ index: sectionIndex, label: section.label, value: section.media_type_chip_color })}
            style={{ width: 44, height: 44, borderWidth: 1, borderColor: colors.fieldBorder, borderRadius: 12, alignItems: 'center', justifyContent: 'center' }}>
            <View style={{ width: 28, height: 24, backgroundColor: section.media_type_chip_color, borderWidth: 1, borderColor: colors.border }} />
          </Pressable> : section.media_type_chip_color ? <View style={styles.colorControl}>
            <View style={[styles.colorDot, { backgroundColor: section.media_type_chip_color, borderColor: colors.border }]} />
            <TextInput
              accessibilityLabel={`${section.label} ${copy.labelColor}`}
              value={String(section.media_type_chip_color)}
              editable={!disabled}
              autoCapitalize="none"
              autoCorrect={false}
              onChangeText={color => setSectionColor(sectionIndex, color)}
              style={[styles.colorText, { borderColor: colors.border, backgroundColor: colors.background, color: colors.textSecondary }]} />
          </View> : null}
          {colors.pageCards ? <Pressable accessibilityRole="button" accessibilityLabel={`${isExpanded ? copy.collapse : copy.expand}: ${section.label}`}
            onPress={() => toggleExpanded(section.media_type)} style={{ padding: 8 }}>
            <View style={isExpanded ? { transform: [{ rotate: '180deg' }] } : undefined}><Icon spec={actionIcons.chevronDown} color={colors.textMuted} size={16} /></View>
          </Pressable> : null}
          {!sectionHandle ? <View style={styles.moveRow}>
            <Pressable
              accessibilityRole="button"
              accessibilityLabel={`${copy.moveUp}: ${section.label}`}
              disabled={disabled || sectionIndex === 0}
              onPress={() => reorderSection(sectionIndex, -1)}
              style={({ pressed }) => [styles.moveButton, { borderColor: colors.border }, pressed && { backgroundColor: colors.surfaceStrong }]}>
              <Text style={[styles.moveText, { color: colors.textMuted }]}>↑</Text>
            </Pressable>
            <Pressable
              accessibilityRole="button"
              accessibilityLabel={`${copy.moveDown}: ${section.label}`}
              disabled={disabled || sectionIndex === sections.length - 1}
              onPress={() => reorderSection(sectionIndex, 1)}
              style={({ pressed }) => [styles.moveButton, { borderColor: colors.border }, pressed && { backgroundColor: colors.surfaceStrong }]}>
              <Text style={[styles.moveText, { color: colors.textMuted }]}>↓</Text>
            </Pressable>
          </View> : null}
        </View>

        {isExpanded ? <View style={styles.sectionBody}>
          {!(section.rows || []).length ? <View style={[styles.emptyRows, { borderColor: colors.border }]}>
            <Text style={[styles.help, { color: colors.textMuted }]}>{copy.noRows}</Text>
          </View> : null}
          <ReorderList items={section.rows || []} keyForItem={row => row.client_id}
            labelForItem={row => row.custom_title || rowAutoTitle(section, row)} icon={dragIcon} palette={colors}
            disabled={disabled || saving} onMove={(from, to) => reorderRow(sectionIndex, from, to - from)}
            renderItem={(row, rowIndex, rowHandle) => {
            const editorOpen = Boolean(rowEditors[row.client_id]);
            const pills = rowFilterPills(section, row);
            const choices = sortChoices(section, row);
            const listResults = listChoices.filter(choice => {
              const term = String(listSearch[row.client_id] || '').trim().toLowerCase();
              return !term || String(choice.name || '').toLowerCase().includes(term);
            });
            return <View key={row.client_id} style={[styles.row, { borderColor: colors.border, backgroundColor: colors.background }]}>
              <View style={styles.rowHeader}>
                {rowHandle || <View style={styles.moveRow}>
                  <Pressable
                    accessibilityRole="button"
                    accessibilityLabel={`${copy.moveUp}: ${copy.rowName} ${rowIndex + 1}`}
                    disabled={disabled || rowIndex === 0}
                    onPress={() => reorderRow(sectionIndex, rowIndex, -1)}
                    style={({ pressed }) => [styles.moveButton, { borderColor: colors.border }, pressed && { backgroundColor: colors.surfaceStrong }]}>
                    <Text style={[styles.moveText, { color: colors.textMuted }]}>↑</Text>
                  </Pressable>
                  <Pressable
                    accessibilityRole="button"
                    accessibilityLabel={`${copy.moveDown}: ${copy.rowName} ${rowIndex + 1}`}
                    disabled={disabled || rowIndex === (section.rows || []).length - 1}
                    onPress={() => reorderRow(sectionIndex, rowIndex, 1)}
                    style={({ pressed }) => [styles.moveButton, { borderColor: colors.border }, pressed && { backgroundColor: colors.surfaceStrong }]}>
                    <Text style={[styles.moveText, { color: colors.textMuted }]}>↓</Text>
                  </Pressable>
                </View>}
                <TextInput
                  accessibilityLabel={copy.rowName}
                  value={row.custom_title || ''}
                  editable={!disabled}
                  maxLength={100}
                  placeholder={rowPlaceholder(section, row)}
                  onChangeText={text => updateRow(sectionIndex, rowIndex, entry => { entry.custom_title = text; })}
                  style={[styles.rowInput, { borderColor: colors.border, backgroundColor: colors.surface, color: colors.text }]} />
                <View style={styles.rowButtons}>
                  <Pressable
                    accessibilityRole="button"
                    accessibilityLabel={`${copy.settings}: ${row.custom_title || copy.rowName}`}
                    accessibilityState={{ expanded: editorOpen }}
                    onPress={() => toggleRowEditor(row.client_id)}
                    style={({ pressed }) => [styles.smallButton, { borderColor: colors.border }, pressed && { backgroundColor: colors.surfaceStrong }]}>
                    <Text style={[styles.smallButtonText, { color: colors.textSecondary }]}>{copy.settings}</Text>
                  </Pressable>
                  <Pressable
                    accessibilityRole="button"
                    accessibilityLabel={`${copy.deleteRow}: ${row.custom_title || copy.rowName}`}
                    disabled={disabled}
                    onPress={() => removeRow(sectionIndex, row.client_id)}
                    style={({ pressed }) => [styles.smallButton, { borderColor: colors.danger }, pressed && { backgroundColor: colors.surfaceStrong }]}>
                    <Text style={[styles.smallButtonText, { color: colors.danger }]}>×</Text>
                  </Pressable>
                </View>
              </View>

              {row.row_type === 'library_query' ? <View style={styles.pillRow}>
                {pills.length ? pills.map(pill => <View key={pill.key} style={[styles.pill, { backgroundColor: colors.surfaceStrong }]}>
                  <Text style={[styles.pillText, { color: colors.textSecondary }]}>{pill.label}: {pill.value}</Text>
                </View>) : <Text style={[styles.pillText, { color: colors.textMuted }]}>{copy.allItems}</Text>}
              </View> : <Text style={[styles.pillText, { color: colors.textMuted }]}>{rowAutoTitle(section, row)}</Text>}

              {row.row_type !== 'recently_unrated' ? <View style={styles.rowMeta}>
                <Text style={[styles.pillText, { color: colors.textMuted }]}>{sortLabel(section, row)}</Text>
                <Pressable
                  accessibilityRole="button"
                  accessibilityLabel={row.direction === 'asc' ? copy.descending : copy.ascending}
                  disabled={disabled}
                  onPress={() => updateRow(sectionIndex, rowIndex, entry => { entry.direction = entry.direction === 'asc' ? 'desc' : 'asc'; })}
                  style={({ pressed }) => [styles.smallButton, { borderColor: colors.border }, pressed && { backgroundColor: colors.surfaceStrong }]}>
                  <Text style={[styles.smallButtonText, { color: colors.textSecondary }]}>{row.direction === 'asc' ? '↑' : '↓'}</Text>
                </Pressable>
              </View> : null}

              {editorOpen ? <View style={[styles.rowEditor, { borderColor: colors.border }]}>
                {row.row_type === 'library_query' ? <>
                  {statusOptions(section).length ? <View style={styles.toggleGroup}>
                    <Text style={[styles.label, { color: colors.textMuted }]}>{copy.status}</Text>
                    <View style={styles.chipRow}>
                      {statusOptions(section).map(option => <ToggleChip
                        key={`status-${option.value}`}
                        value={option.value === 'all' ? rowStatusValues(row).length === 0 : rowStatusValues(row).includes(option.value)}
                        label={option.label}
                        offLabel="Off"
                        onLabel="On"
                        disabled={disabled}
                        palette={colors}
                        onChange={() => updateRow(sectionIndex, rowIndex, entry => toggleStatus(entry, option.value))}
                      />)}
                    </View>
                  </View> : null}
                  {choices.length ? <SelectField iconChevron={Boolean(colors.pageCards)}
                    id={`home-${row.client_id}-sort`}
                    label={copy.sort}
                    options={choices}
                    value={row.sort_by}
                    disabled={disabled}
                    palette={colors}
                    onChange={event => updateRow(sectionIndex, rowIndex, entry => chooseSort(section, entry, event.target.value))}
                  /> : null}
                  {filterFields(section).map(field => {
                    if (field.key === 'tag' || field.key === 'media_types') {
                      return <View key={field.key} style={styles.toggleGroup}>
                        <Text style={[styles.label, { color: colors.textMuted }]}>{field.label}</Text>
                        <View style={styles.chipRow}>
                          {(field.options || []).map(option => <ToggleChip
                            key={`${field.key}-${option.value}`}
                            value={(field.key === 'tag' ? rowTagValues(row) : rowMediaTypeValues(row)).includes(option.value)}
                            label={option.label}
                            offLabel="Off"
                            onLabel="On"
                            disabled={disabled}
                            palette={colors}
                            onChange={() => updateRow(sectionIndex, rowIndex, entry => {
                              if (field.key === 'tag') {
                                const tags = rowTagValues(entry);
                                entry.filters = {
                                  ...(entry.filters || {}),
                                  tag: tags.includes(option.value) ? tags.filter(tag => tag !== option.value) : [...tags, option.value],
                                };
                              } else {
                                const mediaTypes = rowMediaTypeValues(entry);
                                entry.filters = {
                                  ...(entry.filters || {}),
                                  media_types: mediaTypes.includes(option.value) ? mediaTypes.filter(type => type !== option.value) : [...mediaTypes, option.value],
                                };
                              }
                            })} />)}
                        </View>
                        {field.key === 'tag' ? <Pressable
                          accessibilityRole="button"
                          accessibilityLabel={copy.tagMode}
                          disabled={disabled}
                          onPress={() => updateRow(sectionIndex, rowIndex, entry => cycleTagMode(entry))}
                          style={({ pressed }) => [styles.smallButton, { borderColor: colors.border, alignSelf: 'flex-start' }, pressed && { backgroundColor: colors.surfaceStrong }]}>
                          <Text style={[styles.smallButtonText, { color: colors.textSecondary }]}>{copy.tagMode}: {row.filters?.tag_mode || 'or'}</Text>
                        </Pressable> : null}
                      </View>;
                    }
                    return <SelectField iconChevron={Boolean(colors.pageCards)}
                      key={field.key}
                      id={`home-${row.client_id}-${field.key}`}
                      label={field.label}
                      placeholder={copy.any}
                      options={[
                        { value: 'all', label: copy.all },
                        ...(field.options || []),
                      ]}
                      value={row.filters?.[field.key] || 'all'}
                      disabled={disabled}
                      palette={colors}
                      onChange={event => updateRow(sectionIndex, rowIndex, entry => setRowFilter(entry, field.key, event.target.value === 'all' ? 'all' : event.target.value))}
                    />;
                  })}
                  {filterFields(section).filter(field => field.key === 'media_types').flatMap(field => (field.options || []).filter(option => (option.subviews || []).length).map(option => <SelectField iconChevron={Boolean(colors.pageCards)}
                    key={`subview-${option.value}`}
                    id={`home-${row.client_id}-subview-${option.value}`}
                    label={`${option.label} display level`}
                    options={option.subviews || []}
                    value={row.filters?.media_subviews?.[option.value] || option.default_subview}
                    disabled={disabled}
                    palette={colors}
                    onChange={event => updateRow(sectionIndex, rowIndex, entry => setMediaSubview(entry, option.value, event.target.value))}
                  />))}
                </> : null}

                {row.row_type === 'custom_list' ? <View style={styles.toggleGroup}>
                  <Text role="heading" aria-level={4} style={[styles.panelTitle, { color: colors.text }]}>{copy.listSelection}</Text>
                  <Text style={[styles.help, { color: colors.textMuted }]}>{copy.listHelp}</Text>
                  <TextInput
                    accessibilityLabel={copy.searchLists}
                    value={listSearch[row.client_id] || ''}
                    editable={!disabled}
                    placeholder={copy.searchLists}
                    onChangeText={text => setListSearch(current => ({ ...current, [row.client_id]: text }))}
                    style={[styles.rowInput, { borderColor: colors.border, backgroundColor: colors.surface, color: colors.text }]} />
                  <SelectField iconChevron={Boolean(colors.pageCards)}
                    id={`home-${row.client_id}-list`}
                    label={copy.listSelection}
                    placeholder={copy.searchLists}
                    options={listResults.map(choice => ({ value: choice.id, label: `${choice.name}${choice.is_smart ? ` (${copy.smartList})` : ''}` }))}
                    value={row.custom_list_id || ''}
                    disabled={disabled}
                    palette={colors}
                    onChange={event => updateRow(sectionIndex, rowIndex, entry => {
                      const result = listChoices.find(choice => String(choice.id) === String(event.target.value));
                      entry.custom_list_id = result?.id || null;
                      entry.custom_list_name = result?.name || '';
                    })}
                  />
                  <Text style={[styles.help, { color: colors.textMuted }]}>{copy.selected} {row.custom_list_name || copy.noList}</Text>
                </View> : null}

                {row.row_type === 'recently_unrated' && section.media_type === 'music' ? <SelectField iconChevron={Boolean(colors.pageCards)}
                  id={`home-${row.client_id}-recent`}
                  label="Recent unrated plays"
                  options={[
                    { value: 'album', label: 'Album' },
                    { value: 'artist', label: 'Artist' },
                    { value: 'track', label: 'Track' },
                    { value: 'all', label: 'Album, artist, and track' },
                  ]}
                  value={row.recent_show || 'album'}
                  disabled={disabled}
                  palette={colors}
                  onChange={event => updateRow(sectionIndex, rowIndex, entry => { entry.recent_show = event.target.value; })}
                /> : null}
              </View> : null}
            </View>;
          }} />

          <View style={styles.addRowWrap}>
            <Text style={[styles.label, { color: colors.textMuted }]}>{copy.addRow}</Text>
            <View style={styles.addButtons}>
              <Pressable accessibilityRole="button" disabled={disabled} onPress={() => addRow(sectionIndex, 'library_query')}
                style={({ pressed }) => [styles.addButton, { borderColor: colors.border }, pressed && { backgroundColor: colors.surfaceStrong }]}>
                <Text style={[styles.addButtonText, { color: colors.textSecondary }]}>{copy.libraryRow}</Text>
              </Pressable>
              {canAddLastWatched(section) ? <Pressable accessibilityRole="button" disabled={disabled} onPress={() => addRow(sectionIndex, 'last_watched')}
                style={({ pressed }) => [styles.addButton, { borderColor: colors.border }, pressed && { backgroundColor: colors.surfaceStrong }]}>
                <Text style={[styles.addButtonText, { color: colors.textSecondary }]}>{copy.lastWatched}</Text>
              </Pressable> : null}
              {canAddUpNext(section) ? <Pressable accessibilityRole="button" disabled={disabled} onPress={() => addRow(sectionIndex, 'up_next')}
                style={({ pressed }) => [styles.addButton, { borderColor: colors.border }, pressed && { backgroundColor: colors.surfaceStrong }]}>
                <Text style={[styles.addButtonText, { color: colors.textSecondary }]}>{copy.upNext}</Text>
              </Pressable> : null}
              {canAddRecent(section) ? <Pressable accessibilityRole="button" disabled={disabled} onPress={() => addRow(sectionIndex, 'recently_unrated')}
                style={({ pressed }) => [styles.addButton, { borderColor: colors.border }, pressed && { backgroundColor: colors.surfaceStrong }]}>
                <Text style={[styles.addButtonText, { color: colors.textSecondary }]}>{copy.recentlyPlayed}</Text>
              </Pressable> : null}
              {section.media_type !== 'all' ? <Pressable accessibilityRole="button" disabled={disabled} onPress={() => addRow(sectionIndex, 'custom_list')}
                style={({ pressed }) => [styles.addButton, { borderColor: colors.border }, pressed && { backgroundColor: colors.surfaceStrong }]}>
                <Text style={[styles.addButtonText, { color: colors.textSecondary }]}>{copy.addList}</Text>
              </Pressable> : null}
            </View>
          </View>
        </View> : null}
      </View>;
    }} />

    <View style={styles.globalGrid}>
      <View style={[styles.globalCard, { borderColor: colors.border, backgroundColor: colors.surface }]}>
        <ToggleChip
          value={values.showMediaTypeHeaders}
          label={copy.mediaTypeHeaders}
          help={copy.mediaTypeHeadersHelp}
          offLabel="Hidden"
          onLabel="Shown"
          disabled={disabled}
          palette={colors}
          onChange={next => update(sections, { showMediaTypeHeaders: next })}
        />
      </View>
      <View style={[styles.globalCard, { borderColor: colors.border, backgroundColor: colors.surface }]}>
        <ToggleChip
          value={values.mediaTypeChipsEnabled}
          label={copy.mediaTypeLabels}
          help={copy.mediaTypeLabelsHelp}
          offLabel="Hidden"
          onLabel="Shown"
          disabled={disabled}
          palette={colors}
          onChange={next => update(sections, { mediaTypeChipsEnabled: next })}
        />
        {mediaTypeChipStyles.length && !segmentedAppearance ? <SelectField iconChevron={Boolean(colors.pageCards)}
          id="home-chip-style"
          label={copy.labelAppearance}
          options={mediaTypeChipStyles}
          value={chipStyle}
          disabled={disabled}
          palette={colors}
          onChange={event => update(sections, { mediaTypeChipStyle: event.target.value })}
        /> : null}
        {mediaTypeChipStyles.length && segmentedAppearance ? <View style={{ gap: 6 }}>
          <Text style={[styles.label, { color: colors.textMuted }]}>{copy.labelAppearance}</Text>
          <View accessibilityRole="radiogroup" style={styles.segments}>
            {mediaTypeChipStyles.map(option => {
              const selected = String(option.value) === String(chipStyle);
              return <Pressable key={option.value} accessibilityRole="radio" aria-checked={selected} accessibilityState={{ checked: selected, disabled }}
                disabled={disabled} onPress={() => update(sections, { mediaTypeChipStyle: option.value })}
                style={[styles.segment, { borderColor: colors.border, backgroundColor: selected ? colors.accentStrong || colors.accent : 'transparent' }]}>
                <Text style={{ color: selected ? colors.accentContrast || colors.text : colors.textSecondary, fontSize: 13 }}>{option.label}</Text>
              </Pressable>;
            })}
          </View>
        </View> : null}
      </View>
    </View>

    <ConfirmDialog visible={Boolean(colorEditor)} title={`${colorEditor?.label || ''} ${copy.labelColor}`}
      confirmLabel="Apply" palette={colors} buttonPalette={buttonPalette}
      error={colorEditor && !/^#[0-9a-f]{6}$/i.test(colorEditor.value) ? 'Enter a six-digit hex color.' : undefined}
      onCancel={() => setColorEditor(null)} onConfirm={() => {
        if (!colorEditor || !/^#[0-9a-f]{6}$/i.test(colorEditor.value)) return;
        setSectionColor(colorEditor.index, colorEditor.value);
        setColorEditor(null);
      }}>
      <TextInput accessibilityLabel="Label color" value={colorEditor?.value || ''} autoCapitalize="none" autoCorrect={false}
        onChangeText={value => setColorEditor(current => ({ ...current, value }))}
        style={[styles.colorText, { color: colors.text, borderColor: colors.fieldBorder || colors.border }]} />
    </ConfirmDialog>
    {colors.pageCards ? <View style={{ alignItems: 'flex-end', gap: 8, marginTop: 8 }}>
      {localError ? <Text accessibilityRole="alert" style={[styles.help, { color: colors.danger }]}>{localError}</Text> : null}
      <Button label={copy.save} busy={saving} disabled={saving || disabled} onPress={save} icon={actionIcons.save} palette={buttonPalette} size="md" />
    </View> : <FormSaveBar
      dirty={dirty}
      saving={saving}
      disabled={disabled}
      error={localError}
      onSave={save}
      saveLabel={copy.save}
      labels={copy}
      palette={colors}
      buttonPalette={{ ...defaultButtonPalette, ...buttonPalette }}
    />}
  </View>;
}

const styles = StyleSheet.create({
  segments: { flexDirection: 'row', gap: 6 },
  segment: { flexGrow: 1, alignItems: 'center', borderWidth: 1, borderRadius: 6, paddingVertical: 8, paddingHorizontal: 12 },
  form: { gap: 16 },
  help: { fontSize: 12, lineHeight: 17 },
  label: { fontSize: 12, fontWeight: '600' },
  sectionCard: { gap: 0, borderWidth: 1, borderRadius: 10, overflow: 'hidden' },
  sectionHeader: { flexDirection: 'row', alignItems: 'center', gap: 8, padding: 10 },
  sectionGrow: { flexShrink: 1, flexGrow: 1, gap: 2, minWidth: 0 },
  sectionName: { fontSize: 14, fontWeight: '600' },
  sectionPreview: { fontSize: 11 },
  sectionBody: { gap: 10, borderTopWidth: 1, borderTopColor: 'transparent', padding: 10 },
  colorControl: { flexDirection: 'row', alignItems: 'center', gap: 4 },
  colorDot: { width: 18, height: 18, borderRadius: 4, borderWidth: 1 },
  colorText: { width: 74, borderWidth: 1, borderRadius: 6, paddingHorizontal: 5, paddingVertical: 4, fontSize: 11 },
  moveRow: { flexDirection: 'row', gap: 4 },
  moveButton: { width: 28, height: 28, borderWidth: 1, borderRadius: 6, alignItems: 'center', justifyContent: 'center' },
  moveText: { fontSize: 13, fontWeight: '700' },
  emptyRows: { borderWidth: 1, borderStyle: 'dashed', borderRadius: 8, padding: 12 },
  row: { gap: 8, borderWidth: 1, borderRadius: 8, padding: 8 },
  rowHeader: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  rowInput: { flexShrink: 1, flexGrow: 1, minWidth: 0, borderWidth: 1, borderRadius: 6, paddingHorizontal: 8, paddingVertical: 6, fontSize: 13 },
  rowButtons: { flexDirection: 'row', gap: 4 },
  smallButton: { borderWidth: 1, borderRadius: 6, paddingHorizontal: 7, paddingVertical: 5 },
  smallButtonText: { fontSize: 11, fontWeight: '600' },
  pillRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 4 },
  pill: { borderRadius: 5, paddingHorizontal: 6, paddingVertical: 2 },
  pillText: { fontSize: 11 },
  rowMeta: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  rowEditor: { gap: 10, borderWidth: 1, borderRadius: 8, padding: 8 },
  toggleGroup: { gap: 6 },
  panelTitle: { fontSize: 13, fontWeight: '600' },
  chipRow: { gap: 6 },
  addRowWrap: { gap: 6 },
  addButtons: { flexDirection: 'row', flexWrap: 'wrap', gap: 6 },
  addButton: { borderWidth: 1, borderRadius: 6, paddingHorizontal: 8, paddingVertical: 7 },
  addButtonText: { fontSize: 12, fontWeight: '600' },
  globalGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: 10 },
  globalCard: { flexGrow: 1, flexBasis: 220, gap: 10, borderWidth: 1, borderRadius: 10, padding: 10 },
});
