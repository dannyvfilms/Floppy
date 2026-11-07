import React, { useMemo, useState } from 'react';
import {
  ActivityIndicator,
  Modal,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  useWindowDimensions,
  View,
} from 'react-native';

const defaultPalette = {
  background: '#18181b',
  surface: '#27272a',
  surfaceStrong: '#3f3f46',
  surfaceHover: '#52525b',
  border: '#52525b',
  text: '#fafafa',
  textSecondary: '#d4d4d8',
  textMuted: '#a1a1aa',
  accent: '#6366f1',
  accentStrong: '#4f46e5',
  accentText: '#ffffff',
  danger: '#ef4444',
  disabled: '#71717a',
  overlay: 'rgba(0, 0, 0, 0.55)',
};

const defaultLabels = {
  filters: 'Filters',
  allFilters: 'All',
  allTypes: 'All types',
  types: 'types',
  status: 'Status',
  allStatuses: 'All statuses',
  statuses: 'statuses',
  sort: 'Sort',
  view: 'View',
  savedViews: 'Saved views',
  clear: 'Clear',
  clearAll: 'Clear all filters',
  clearStatus: 'Clear status filter',
  direction: 'Direction',
  apply: 'Apply',
  clearRange: 'Clear',
  close: 'Close',
  mediaType: 'Media type',
  statusHeading: 'Status',
  range: 'Range',
  ascending: 'ascending',
  descending: 'descending',
  updating: 'Updating results',
  items: 'items',
  any: 'Any',
  from: 'From',
  to: 'To',
  within: 'In the last',
  change: 'Change',
  all: 'All',
  searchOptions: 'Search options',
  noOptions: 'No options found',
};

function mergeLabels(labels) {
  return { ...defaultLabels, ...(labels || {}) };
}

function typeSummary(filters, options, copy = defaultLabels) {
  const selected = filters.mediaTypes || [];
  if (!selected.length || selected.length === availableValues(options.mediaTypes).length) {
    return copy.allTypes;
  }
  if (selected.length === 1) {
    const match = availableValues(options.mediaTypes).find((item) => item.value === selected[0]);
    return match ? match.label : selected[0];
  }
  return `${selected.length} ${copy.types}`;
}

function statusSummary(filters, options, copy = defaultLabels) {
  const selected = filters.statuses || [];
  if (!selected.length) {
    return copy.allStatuses;
  }
  if (selected.length === 1) {
    const match = (options.statuses || []).find((item) => item.value === selected[0]);
    return match ? match.label : selected[0];
  }
  return `${selected.length} ${copy.statuses}`;
}

function rangeSummary(range, value) {
  if (!value) {
    return 'Any';
  }
  if (value.within) {
    const unit = (range.units || []).find((item) => item.value === value.unit);
    return `Last ${value.within} ${unit ? unit.label.toLowerCase() : value.unit || 'days'}`;
  }
  if (value.from && value.to) {
    return `${value.from} – ${value.to}`;
  }
  if (value.from) {
    return `From ${value.from}`;
  }
  if (value.to) {
    return `To ${value.to}`;
  }
  return 'Any';
}

function isRangeActive(value) {
  return Boolean(value && (value.from || value.to || value.within));
}

function sectionValue(filters, section) {
  return (filters.fields || {})[section.key];
}

function sectionClearValue(section) {
  return section.clearValue === undefined ? '' : section.clearValue;
}

function sectionIsActive(section, value) {
  if (section.type === 'multi') {
    return Array.isArray(value) && value.length > 0;
  }
  return Boolean(value) && String(value) !== String(sectionClearValue(section));
}

function sectionSummary(section, filters) {
  const value = sectionValue(filters, section);
  if (!sectionIsActive(section, value)) {
    return '';
  }
  const labels = (section.options || []);
  if (section.type === 'multi') {
    const mode = (filters.modes || {})[section.key] || section.modeValue;
    const selected = (value || []).map((item) => {
      const match = labels.find((option) => String(option.value) === String(item));
      return match ? match.label : String(item);
    });
    const prefix = mode === 'not' ? '−' : '';
    const separator = mode === 'and' ? ' & ' : ', ';
    return prefix + selected.join(separator);
  }
  const match = labels.find((option) => String(option.value) === String(value));
  return match ? match.label : String(value);
}

function sectionCount(filters, sections) {
  return (sections || []).filter((section) =>
    sectionIsActive(section, sectionValue(filters, section))).length;
}

function sectionSummaryText(filters, sections) {
  const parts = [];
  for (const section of sections || []) {
    const summary = sectionSummary(section, filters);
    if (summary) {
      parts.push(summary);
    }
  }
  return parts;
}

function activeFilterCount(filters, options) {
  let count = sectionCount(filters, options.sections);
  if ((filters.mediaTypes || []).length) {
    count += 1;
  }
  if ((filters.statuses || []).length) {
    count += 1;
  }
  for (const range of options.ranges || []) {
    if (isRangeActive((filters.ranges || {})[range.key])) {
      count += 1;
    }
  }
  return count;
}

function availableValues(options) {
  return (options || []).filter((item) => !item.disabled);
}

function filterSummary(filters, options, copy = defaultLabels) {
  const parts = [];
  if ((filters.mediaTypes || []).length) {
    parts.push(typeSummary(filters, options, copy));
  }
  parts.push(...sectionSummaryText(filters, options.sections));
  for (const range of options.ranges || []) {
    const value = (filters.ranges || {})[range.key];
    if (isRangeActive(value)) {
      parts.push(`${range.label}: ${rangeSummary(range, value)}`);
    }
  }
  if (!parts.length) {
    return 'All';
  }
  return parts.length === 1 ? parts[0] : `${parts[0]} +${parts.length - 1}`;
}

function optionLabel(options, value) {
  const match = (options || []).find((item) => item.value === value);
  return match ? match.label : value;
}

export function FilterBar({
  filters = {},
  options = {},
  labels,
  palette,
  busy = false,
  disabled = false,
  resultCount,
  onChange,
  onClear,
}) {
  const { width } = useWindowDimensions();
  const compact = width < 720;
  const copy = mergeLabels(labels);
  const colors = { ...defaultPalette, ...(palette || {}) };
  const styles = useMemo(() => createStyles(colors, compact), [colors, compact]);
  const [openSheet, setOpenSheet] = useState(null);
  const [rangeDraft, setRangeDraft] = useState(null);
  const ranges = options.ranges || [];
  const savedViews = options.savedViews || [];
  const sections = options.sections || [];
  const views = options.views || [];
  const count = activeFilterCount(filters, options);
  const isDisabled = disabled || busy;
  const directionLabel = filters.direction === 'asc' ? '↑' : '↓';
  const sortValue = `${optionLabel(options.sorts, filters.sort)} ${directionLabel}`;
  const viewValue = optionLabel(options.views, filters.view);

  function emit(intent) {
    if (isDisabled) {
      return;
    }
    onChange?.(intent);
  }

  function closeSheet() {
    setOpenSheet(null);
    setRangeDraft(null);
  }

  function openRange(range) {
    const current = (filters.ranges || {})[range.key] || {};
    setRangeDraft({
      from: current.from || '',
      to: current.to || '',
      within: current.within || '',
      unit: current.unit || (range.units && range.units[0] ? range.units[0].value : 'days'),
    });
    setOpenSheet(`range:${range.key}`);
  }

  function updateDraft(key, value) {
    setRangeDraft((current) => ({ ...(current || {}), [key]: value }));
  }

  function applyRange(range) {
    emit({ type: 'range', key: range.key, value: rangeDraft || {} });
    closeSheet();
  }

  function clearRange(range) {
    emit({ type: 'range', key: range.key, value: { from: '', to: '', within: '', unit: rangeDraft?.unit || 'days' } });
    closeSheet();
  }

  function clearAll() {
    emit({ type: 'clear' });
    onClear?.();
    closeSheet();
  }

  function toggleMulti(key, value) {
    emit({ type: 'toggle', key, value });
  }

  function chooseSingle(key, value) {
    emit({ type: 'set', key, value });
    closeSheet();
  }

  function chooseSavedView(id) {
    emit({ type: 'savedView', value: id });
    closeSheet();
  }

  const activeSection = openSheet && openSheet.startsWith('section:')
    ? sections.find((section) => `section:${section.key}` === openSheet)
    : null;
  const sheetTitle = openSheet === 'filters' ? copy.filters
    : openSheet === 'status' ? copy.status
      : openSheet === 'sort' ? copy.sort
        : openSheet === 'view' ? copy.view
          : activeSection ? activeSection.label
            : openSheet && openSheet.startsWith('range:') ? (ranges.find((range) => `range:${range.key}` === openSheet)?.label || copy.range)
              : '';

  const activeRange = openSheet && openSheet.startsWith('range:')
    ? ranges.find((range) => `range:${range.key}` === openSheet)
    : null;

  return <View style={styles.bar}>
    <View style={styles.triggers}>
      <Trigger
        label={`${copy.filters}: ${filterSummary(filters, options, copy)}`}
        value={filterSummary(filters, options, copy)}
        expanded={openSheet === 'filters'}
        disabled={isDisabled}
        onPress={() => setOpenSheet(openSheet === 'filters' ? null : 'filters')}
        styles={styles} />

      <Trigger
        label={`${copy.status}: ${statusSummary(filters, options, copy)}`}
        value={statusSummary(filters, options, copy)}
        expanded={openSheet === 'status'}
        disabled={isDisabled}
        onPress={() => setOpenSheet(openSheet === 'status' ? null : 'status')}
        styles={styles} />

      <Trigger
        label={`${copy.sort}: ${optionLabel(options.sorts, filters.sort)} ${filters.direction === 'asc' ? copy.ascending : copy.descending}`}
        value={sortValue}
        expanded={openSheet === 'sort'}
        disabled={isDisabled}
        onPress={() => setOpenSheet(openSheet === 'sort' ? null : 'sort')}
        styles={styles} />

      {views.length || savedViews.length ? <Trigger
        label={`${copy.view}: ${viewValue || copy.savedViews}`}
        value={viewValue || copy.savedViews}
        expanded={openSheet === 'view'}
        disabled={isDisabled}
        onPress={() => setOpenSheet(openSheet === 'view' ? null : 'view')}
        styles={styles} /> : null}

      {ranges.length > 0 ? <Trigger
        label={`${copy.range}: ${ranges.map((range) => `${range.label} ${rangeSummary(range, (filters.ranges || {})[range.key])}`).join(', ')}`}
        value={copy.range}
        expanded={Boolean(activeRange)}
        disabled={isDisabled}
        onPress={() => openRange(ranges[0])}
        styles={styles} /> : null}

      {count > 0 ? <Pressable
        accessibilityRole="button"
        accessibilityLabel={copy.clearAll}
        accessibilityState={{ disabled: isDisabled }}
        disabled={isDisabled}
        onPress={clearAll}
        style={({ pressed }) => [styles.clear, pressed && styles.pressed]}>
        <Text style={styles.clearText}>{copy.clear}</Text>
      </Pressable> : null}
    </View>

    <View style={styles.meta} accessibilityLiveRegion="polite">
      {busy ? <><ActivityIndicator size="small" color={colors.accent} />
        <Text style={styles.metaText}>{copy.updating}</Text></> : null}
      {typeof resultCount === 'number' && !busy ? <Text style={styles.metaText}>
        {resultCount} {copy.items}
      </Text> : null}
    </View>

    <Modal
      visible={Boolean(openSheet)}
      transparent
      animationType="fade"
      onRequestClose={closeSheet}>
      <View style={styles.overlay}>
        <Pressable accessibilityRole="button" accessibilityLabel={copy.close} style={styles.backdrop} onPress={closeSheet} />
        <View style={styles.sheet} accessibilityViewIsModal>
          <View style={styles.sheetHeader}>
            <Text style={styles.sheetTitle}>{sheetTitle}</Text>
            <Pressable
              accessibilityRole="button"
              accessibilityLabel={copy.close}
              onPress={closeSheet}
              style={({ pressed }) => [styles.close, pressed && styles.pressed]}>
              <Text style={styles.closeText}>×</Text>
            </Pressable>
          </View>
          <ScrollView style={styles.sheetBody} contentContainerStyle={styles.sheetContent} keyboardShouldPersistTaps="handled">
            {openSheet === 'filters' ? <FiltersSheet
              filters={filters}
              options={options}
              copy={copy}
              styles={styles}
              sections={sections}
              onToggleType={(value) => toggleMulti('mediaTypes', value)}
              onOpenRange={openRange}
              onOpenSection={(section) => {
                setOpenSheet(`section:${section.key}`);
                setRangeDraft(null);
              }}
              onClear={clearAll} /> : null}

            {openSheet === 'status' ? <StatusSheet
              filters={filters}
              options={options}
              copy={copy}
              styles={styles}
              onToggle={(value) => toggleMulti('statuses', value)}
              onClear={() => emit({ type: 'set', key: 'statuses', value: [] })} /> : null}

            {openSheet === 'sort' ? <SortSheet
              filters={filters}
              options={options}
              copy={copy}
              styles={styles}
              onChoose={(value) => chooseSingle('sort', value)}
              onDirection={(value) => emit({ type: 'set', key: 'direction', value })} /> : null}

            {openSheet === 'view' ? <ViewSheet
              filters={filters}
              options={options}
              copy={copy}
              styles={styles}
              savedViews={savedViews}
              onChoose={(value) => chooseSingle('view', value)}
              onSavedView={chooseSavedView} /> : null}

            {activeSection ? <SectionSheet
              section={activeSection}
              value={sectionValue(filters, activeSection)}
              mode={(filters.modes || {})[activeSection.key] || activeSection.modeValue}
              copy={copy}
              styles={styles}
              placeholderColor={colors.textMuted}
              onSelect={(option) => {
                emit({ type: activeSection.type === 'multi' ? 'toggleField' : 'field', key: activeSection.key, value: option.value });
                if (activeSection.type !== 'multi') closeSheet();
              }}
              onClear={() => {
                emit({ type: 'clearField', key: activeSection.key });
                if (activeSection.type !== 'multi') closeSheet();
              }}
              onMode={(mode) => emit({ type: 'fieldMode', key: activeSection.key, value: mode })} /> : null}

            {activeRange && rangeDraft ? <RangeSheet
              range={activeRange}
              draft={rangeDraft}
              copy={copy}
              styles={styles}
              placeholderColor={colors.textMuted}
              onChange={updateDraft}
              onApply={() => applyRange(activeRange)}
              onClear={() => clearRange(activeRange)} /> : null}
          </ScrollView>
        </View>
      </View>
    </Modal>
  </View>;
}

function Trigger({ label, value, expanded, disabled, onPress, styles }) {
  return <Pressable
    accessibilityRole="button"
    accessibilityLabel={label}
    accessibilityState={{ expanded, disabled }}
    disabled={disabled}
    onPress={onPress}
    style={({ pressed }) => [styles.trigger, expanded && styles.triggerOpen, pressed && styles.pressed]}>
    <Text numberOfLines={1} style={styles.triggerText}>{value}</Text>
    <Text style={styles.chevron}>▾</Text>
  </Pressable>;
}

function Section({ title, children, styles }) {
  return <View style={styles.section}>
    <Text style={styles.sectionTitle}>{title}</Text>
    {children}
  </View>;
}

function OptionRow({ label, selected, disabled, role = 'radio', onPress, styles }) {
  return <Pressable
    accessibilityRole={role}
    accessibilityLabel={label}
    accessibilityState={{ checked: selected, disabled }}
    disabled={disabled}
    onPress={onPress}
    style={({ pressed }) => [styles.option, selected && styles.optionSelected, pressed && styles.pressed]}>
    <Text style={[styles.optionText, disabled && styles.disabledText]}>{label}</Text>
    {selected ? <Text style={styles.check}>✓</Text> : null}
  </Pressable>;
}

function FiltersSheet({ filters, options, copy, styles, sections, onToggleType, onOpenRange, onOpenSection, onClear }) {
  return <View style={styles.sheetStack}>
    <Section title={copy.mediaType} styles={styles}>
      {(options.mediaTypes || []).map((option) => <OptionRow
        key={option.value}
        label={option.label}
        role="checkbox"
        selected={(filters.mediaTypes || []).includes(option.value)}
        disabled={option.disabled}
        onPress={() => onToggleType(option.value)}
        styles={styles} />)}
    </Section>

    {(sections || []).length ? <View style={styles.sheetStack}>
      {(sections || []).map((section) => {
        const summary = sectionSummary(section, filters);
        return <Pressable
          key={section.key}
          accessibilityRole="button"
          accessibilityLabel={`${section.label}: ${summary || copy.any}`}
          onPress={() => onOpenSection(section)}
          style={({ pressed }) => [styles.option, pressed && styles.pressed]}>
          <Text style={styles.optionText}>{section.label}</Text>
          <Text style={styles.optionValue}>{summary || copy.any}</Text>
          <Text style={styles.chevron}>›</Text>
        </Pressable>;
      })}
    </View> : null}

    {(options.ranges || []).length ? <Section title={copy.range} styles={styles}>
      {(options.ranges || []).map((range) => <Pressable
        key={range.key}
        accessibilityRole="button"
        accessibilityLabel={`${range.label}: ${rangeSummary(range, (filters.ranges || {})[range.key])}`}
        onPress={() => onOpenRange(range)}
        style={({ pressed }) => [styles.option, pressed && styles.pressed]}>
        <Text style={styles.optionText}>{range.label}</Text>
        <Text style={styles.optionValue}>{rangeSummary(range, (filters.ranges || {})[range.key])}</Text>
        <Text style={styles.chevron}>›</Text>
      </Pressable>)}
    </Section> : null}

    <Pressable
      accessibilityRole="button"
      accessibilityLabel={copy.clearAll}
      onPress={onClear}
      style={({ pressed }) => [styles.clearAll, pressed && styles.pressed]}>
      <Text style={styles.clearAllText}>{copy.clearAll}</Text>
    </Pressable>
  </View>;
}

function SectionSheet({ section, value, mode, copy, styles, placeholderColor, onSelect, onClear, onMode }) {
  const [search, setSearch] = useState('');
  const options = section.options || [];
  const clearValue = sectionClearValue(section);
  const isMulti = section.type === 'multi';
  const term = search.trim().toLowerCase();
  const visible = term
    ? options.filter((option) => String(option.label).toLowerCase().includes(term))
    : options;
  const hasClearOption = options.some((option) => String(option.value) === String(clearValue));
  const selectedValues = isMulti ? (Array.isArray(value) ? value : []) : [];
  return <View style={styles.sheetStack}>
    {section.modes?.length ? <View style={styles.segments}>
      {section.modes.map((item) => <Pressable
        key={item.value}
        accessibilityRole="button"
        accessibilityLabel={item.label}
        accessibilityState={{ selected: mode === item.value }}
        onPress={() => onMode(item.value)}
        style={({ pressed }) => [styles.segment, mode === item.value && styles.segmentSelected, pressed && styles.pressed]}>
        <Text style={[styles.segmentText, mode === item.value && styles.segmentTextSelected]}>{item.label}</Text>
      </Pressable>)}
    </View> : null}

    {section.searchable && options.length > 8 ? <TextInput
      accessibilityLabel={copy.searchOptions}
      value={search}
      onChangeText={setSearch}
      placeholder={copy.searchOptions}
      placeholderTextColor={placeholderColor}
      style={styles.input} /> : null}

    {isMulti ? <OptionRow
      label={copy.all}
      role="checkbox"
      selected={selectedValues.length === 0}
      onPress={onClear}
      styles={styles} /> : !hasClearOption ? <OptionRow
        label={copy.any}
        role="radio"
        selected={!sectionIsActive(section, value)}
        onPress={onClear}
        styles={styles} /> : null}

    {visible.map((option) => {
      const selected = isMulti
        ? selectedValues.some((item) => String(item) === String(option.value))
        : String(value) === String(option.value);
      return <OptionRow
        key={option.value}
        label={option.label}
        role={isMulti ? 'checkbox' : 'radio'}
        selected={selected}
        disabled={option.disabled}
        onPress={() => onSelect(option)}
        styles={styles} />;
    })}

    {!visible.length ? <Text style={styles.metaText}>{copy.noOptions}</Text> : null}

    {isMulti && selectedValues.length ? <Pressable
      accessibilityRole="button"
      accessibilityLabel={`${copy.clear} ${section.label}`}
      onPress={onClear}
      style={({ pressed }) => [styles.clearAll, pressed && styles.pressed]}>
      <Text style={styles.clearAllText}>{copy.clear}</Text>
    </Pressable> : null}
  </View>;
}

function StatusSheet({ filters, options, copy, styles, onToggle, onClear }) {
  return <View style={styles.sheetStack}>
    {(options.statuses || []).map((option) => <OptionRow
      key={option.value}
      label={option.label}
      role="checkbox"
      selected={(filters.statuses || []).includes(option.value)}
      disabled={option.disabled}
      onPress={() => onToggle(option.value)}
      styles={styles} />)}
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={copy.clearStatus}
      onPress={onClear}
      style={({ pressed }) => [styles.clearAll, pressed && styles.pressed]}>
      <Text style={styles.clearAllText}>{copy.clearStatus}</Text>
    </Pressable>
  </View>;
}

function SortSheet({ filters, options, copy, styles, onChoose, onDirection }) {
  return <View style={styles.sheetStack}>
    {(options.sorts || []).map((option) => <OptionRow
      key={option.value}
      label={option.label}
      role="radio"
      selected={filters.sort === option.value}
      disabled={option.disabled}
      onPress={() => onChoose(option.value)}
      styles={styles} />)}
    <Section title={copy.direction} styles={styles}>
      <View style={styles.segments}>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel={`Sort ${copy.ascending}`}
          accessibilityState={{ selected: filters.direction === 'asc' }}
          onPress={() => onDirection('asc')}
          style={({ pressed }) => [styles.segment, filters.direction === 'asc' && styles.segmentSelected, pressed && styles.pressed]}>
          <Text style={[styles.segmentText, filters.direction === 'asc' && styles.segmentTextSelected]}>A–Z</Text>
        </Pressable>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel={`Sort ${copy.descending}`}
          accessibilityState={{ selected: filters.direction !== 'asc' }}
          onPress={() => onDirection('desc')}
          style={({ pressed }) => [styles.segment, filters.direction !== 'asc' && styles.segmentSelected, pressed && styles.pressed]}>
          <Text style={[styles.segmentText, filters.direction !== 'asc' && styles.segmentTextSelected]}>Z–A</Text>
        </Pressable>
      </View>
    </Section>
  </View>;
}

function ViewSheet({ filters, options, copy, styles, savedViews, onChoose, onSavedView }) {
  return <View style={styles.sheetStack}>
    {(options.views || []).map((option) => <OptionRow
      key={option.value}
      label={option.label}
      role="radio"
      selected={filters.view === option.value}
      disabled={option.disabled}
      onPress={() => onChoose(option.value)}
      styles={styles} />)}
    {savedViews.length ? <Section title={copy.savedViews} styles={styles}>
      {savedViews.map((view) => <OptionRow
        key={view.id}
        label={view.label}
        role="radio"
        selected={view.active}
        disabled={view.disabled}
        onPress={() => onSavedView(view.id)}
        styles={styles} />)}
    </Section> : null}
  </View>;
}

function RangeSheet({ range, draft, copy, styles, placeholderColor, onChange, onApply, onClear }) {
  return <View style={styles.sheetStack}>
    {range.relative ? <View style={styles.field}>
      <Text style={styles.fieldLabel}>{copy.within}</Text>
      <TextInput
        accessibilityLabel={`${range.label} ${copy.within}`}
        value={String(draft.within || '')}
        onChangeText={(value) => onChange('within', value)}
        keyboardType="number-pad"
        placeholder="7"
        placeholderTextColor={placeholderColor}
        style={styles.input} />
      <View style={styles.segments}>
        {(range.units || []).map((unit) => <Pressable
          key={unit.value}
          accessibilityRole="button"
          accessibilityLabel={unit.label}
          accessibilityState={{ selected: draft.unit === unit.value }}
          onPress={() => onChange('unit', unit.value)}
          style={({ pressed }) => [styles.segment, draft.unit === unit.value && styles.segmentSelected, pressed && styles.pressed]}>
          <Text style={[styles.segmentText, draft.unit === unit.value && styles.segmentTextSelected]}>{unit.label}</Text>
        </Pressable>)}
      </View>
    </View> : null}

    <View style={styles.field}>
      <Text style={styles.fieldLabel}>{copy.from}</Text>
      <TextInput
        accessibilityLabel={`${range.label} ${copy.from}`}
        value={String(draft.from || '')}
        onChangeText={(value) => onChange('from', value)}
        inputMode={range.type === 'number' ? 'decimal' : 'text'}
        placeholder={range.placeholder || ''}
        placeholderTextColor={placeholderColor}
        style={styles.input} />
    </View>

    <View style={styles.field}>
      <Text style={styles.fieldLabel}>{copy.to}</Text>
      <TextInput
        accessibilityLabel={`${range.label} ${copy.to}`}
        value={String(draft.to || '')}
        onChangeText={(value) => onChange('to', value)}
        inputMode={range.type === 'number' ? 'decimal' : 'text'}
        placeholder={range.placeholder || ''}
        placeholderTextColor={placeholderColor}
        style={styles.input} />
    </View>

    <View style={styles.rangeActions}>
      <Pressable
        accessibilityRole="button"
        accessibilityLabel={`${copy.apply} ${range.label}`}
        onPress={onApply}
        style={({ pressed }) => [styles.apply, pressed && styles.pressed]}>
        <Text style={styles.applyText}>{copy.apply}</Text>
      </Pressable>
      <Pressable
        accessibilityRole="button"
        accessibilityLabel={`${copy.clearRange} ${range.label}`}
        onPress={onClear}
        style={({ pressed }) => [styles.clearRange, pressed && styles.pressed]}>
        <Text style={styles.clearRangeText}>{copy.clearRange}</Text>
      </Pressable>
    </View>
  </View>;
}

function createStyles(colors, compact) {
  return StyleSheet.create({
    bar: { gap: 8 },
    triggers: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', gap: 8 },
    trigger: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 6,
      minHeight: 36,
      paddingHorizontal: 12,
      borderRadius: 8,
      borderWidth: 1,
      borderColor: colors.border,
      backgroundColor: colors.surface,
      maxWidth: compact ? '100%' : 240,
    },
    triggerOpen: { borderColor: colors.accent, backgroundColor: colors.surfaceStrong },
    triggerText: { color: colors.textSecondary, fontSize: 13, fontWeight: '600' },
    chevron: { color: colors.textMuted, fontSize: 12 },
    pressed: { opacity: 0.72 },
    disabledText: { color: colors.disabled },
    clear: { minHeight: 36, paddingHorizontal: 12, justifyContent: 'center' },
    clearText: { color: colors.accent, fontSize: 13, fontWeight: '600' },
    meta: { minHeight: 20, flexDirection: 'row', alignItems: 'center', gap: 8 },
    metaText: { color: colors.textMuted, fontSize: 12 },
    overlay: { flex: 1, justifyContent: compact ? 'flex-end' : 'center', alignItems: 'center', backgroundColor: colors.overlay },
    backdrop: { position: 'absolute', top: 0, right: 0, bottom: 0, left: 0 },
    sheet: {
      width: compact ? '100%' : 420,
      maxHeight: compact ? '82%' : '78%',
      backgroundColor: colors.surface,
      borderWidth: 1,
      borderColor: colors.border,
      borderTopLeftRadius: compact ? 16 : 12,
      borderTopRightRadius: compact ? 16 : 12,
      borderBottomLeftRadius: compact ? 0 : 12,
      borderBottomRightRadius: compact ? 0 : 12,
      overflow: 'hidden',
    },
    sheetHeader: {
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'space-between',
      gap: 8,
      paddingHorizontal: 16,
      paddingVertical: 12,
      borderBottomWidth: 1,
      borderBottomColor: colors.border,
    },
    sheetTitle: { color: colors.text, fontSize: 16, fontWeight: '700' },
    close: { width: 32, height: 32, alignItems: 'center', justifyContent: 'center', borderRadius: 8, backgroundColor: colors.surfaceStrong },
    closeText: { color: colors.textSecondary, fontSize: 20, lineHeight: 22 },
    sheetBody: { flexGrow: 0 },
    sheetContent: { padding: 12, gap: 12 },
    sheetStack: { gap: 12 },
    section: { gap: 6 },
    sectionTitle: { color: colors.textMuted, fontSize: 11, fontWeight: '700', letterSpacing: 0.8, textTransform: 'uppercase' },
    option: {
      minHeight: 42,
      flexDirection: 'row',
      alignItems: 'center',
      gap: 8,
      paddingHorizontal: 10,
      borderRadius: 8,
      backgroundColor: colors.surfaceStrong,
    },
    optionSelected: { backgroundColor: colors.accentStrong },
    optionText: { flexShrink: 1, color: colors.textSecondary, fontSize: 14 },
    optionValue: { marginLeft: 'auto', color: colors.textMuted, fontSize: 12 },
    check: { marginLeft: 'auto', color: colors.accentText, fontSize: 14, fontWeight: '700' },
    clearAll: { minHeight: 42, alignItems: 'center', justifyContent: 'center', borderRadius: 8, borderWidth: 1, borderColor: colors.border },
    clearAllText: { color: colors.textSecondary, fontSize: 13, fontWeight: '600' },
    segments: { flexDirection: 'row', flexWrap: 'wrap', gap: 6 },
    segment: { minHeight: 36, paddingHorizontal: 12, alignItems: 'center', justifyContent: 'center', borderRadius: 8, backgroundColor: colors.surfaceStrong },
    segmentSelected: { backgroundColor: colors.accentStrong },
    segmentText: { color: colors.textSecondary, fontSize: 13, fontWeight: '600' },
    segmentTextSelected: { color: colors.accentText },
    field: { gap: 6 },
    fieldLabel: { color: colors.textMuted, fontSize: 12, fontWeight: '600' },
    input: {
      minHeight: 40,
      paddingHorizontal: 10,
      borderRadius: 8,
      borderWidth: 1,
      borderColor: colors.border,
      backgroundColor: colors.background,
      color: colors.text,
      fontSize: 14,
    },
    rangeActions: { flexDirection: 'row', gap: 8 },
    apply: { flex: 1, minHeight: 42, alignItems: 'center', justifyContent: 'center', borderRadius: 8, backgroundColor: colors.accentStrong },
    applyText: { color: colors.accentText, fontSize: 14, fontWeight: '700' },
    clearRange: { minHeight: 42, paddingHorizontal: 16, alignItems: 'center', justifyContent: 'center', borderRadius: 8, borderWidth: 1, borderColor: colors.border },
    clearRangeText: { color: colors.textSecondary, fontSize: 14, fontWeight: '600' },
  });
}
