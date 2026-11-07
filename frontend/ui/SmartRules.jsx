import React, { useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { Badge } from './Badge';
import { Button } from './Button';
import { FormError, FormSelect, FormTextField } from './MediaCardFormControls';

const DEFAULT_PALETTE = {
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
  link: '#818cf8',
};

const DEFAULT_LABELS = {
  title: 'Smart Rules',
  types: 'Types',
  allTypes: 'All Types',
  status: 'Status',
  rating: 'Rating',
  collection: 'Collection',
  genre: 'Genre',
  impliedGenre: 'Implied Genre',
  year: 'Year',
  unknown: 'Unknown',
  released: 'Released',
  source: 'Source',
  language: 'Language',
  country: 'Country',
  platform: 'Platform',
  origin: 'Origin',
  format: 'Format',
  author: 'Author',
  channel: 'Channel',
  provider: 'Provider',
  tag: 'Tags',
  list: 'List',
  search: 'Search',
  any: 'Any',
  all: 'All',
  none: 'None',
  rated: 'Rated',
  notRated: 'Not Rated',
  collected: 'Collected',
  notCollected: 'Not Collected',
  notReleased: 'Not Released',
  editActive: 'Edit mode active',
  saving: 'Saving…',
  saved: 'Saved',
  saveFailed: 'Save failed',
  viewOnly: 'Filters apply to this view only. Saved rules are unchanged.',
  editing: 'Changes save when you press Save rules.',
  saveRules: 'Save rules',
  cancel: 'Cancel',
  clearAll: 'Clear all rules',
  min: 'Minimum rating',
  max: 'Maximum rating',
  minPlaceholder: '0.0',
  maxPlaceholder: '10.0',
  from: 'From',
  to: 'To',
  within: 'In the last',
  amount: 'Amount',
  unit: 'Unit',
  releaseDate: 'Release date',
  dateAdded: 'Date added',
  completedDate: 'Completed date',
  searchPlaceholder: 'Search this list',
  filterBy: 'Filter',
  showFilters: 'Show filters',
  hideFilters: 'Hide filters',
  tagOperator: 'Tag operator',
  noRules: 'No rules match yet.',
  validation: 'Fix the highlighted rules before saving.',
  ratingRange: 'Rating must be between 0 and 10.',
  ratingOrder: 'Minimum rating cannot be greater than maximum rating.',
  dateInvalid: 'Use YYYY-MM-DD.',
  dateOrder: 'The start date must be on or before the end date.',
  windowInvalid: 'Use a whole number from 1 to 999.',
  tierRule: 'Rules only shape this list; the server still evaluates membership.',
};

const RATING_OPTIONS = [
  { value: 'all', label: 'Any' },
  { value: 'rated', label: 'Rated' },
  { value: 'not_rated', label: 'Not Rated' },
];

const COLLECTION_OPTIONS = [
  { value: 'all', label: 'Any' },
  { value: 'collected', label: 'Collected' },
  { value: 'not_collected', label: 'Not Collected' },
];

const RELEASE_OPTIONS = [
  { value: 'all', label: 'Any' },
  { value: 'released', label: 'Released' },
  { value: 'not_released', label: 'Not Released' },
];

const TAG_MODE_OPTIONS = [
  { value: 'or', label: 'Any tag' },
  { value: 'and', label: 'All tags' },
  { value: 'not', label: 'No tag' },
];

const DATE_OPTIONS = [
  { value: 'days', label: 'Days' },
  { value: 'weeks', label: 'Weeks' },
  { value: 'months', label: 'Months' },
  { value: 'years', label: 'Years' },
];

const TEXT_KEYS = [
  'genre',
  'implied_genre',
  'source',
  'language',
  'country',
  'platform',
  'origin',
  'format',
  'author',
  'provider',
];

const DATE_GROUPS = [
  { key: 'release_date', label: 'Release date' },
  { key: 'date_added', label: 'Date added' },
  { key: 'completed_date', label: 'Completed date' },
];

function mergePalette(palette) {
  return { ...DEFAULT_PALETTE, ...(palette || {}) };
}

function mergeLabels(labels) {
  return { ...DEFAULT_LABELS, ...(labels || {}) };
}

function badgePalette(colors) {
  return {
    outline: { color: colors.textSecondary, borderColor: colors.border, borderWidth: 1 },
    indigo: { color: colors.accentText, backgroundColor: colors.accentStrong },
    muted: { color: colors.textMuted, backgroundColor: colors.surfaceStrong },
    danger: { color: colors.danger, borderColor: colors.danger, borderWidth: 1 },
  };
}

function optionLabel(options, value) {
  const match = (options || []).find(option => String(option.value ?? option.id) === String(value));
  return match ? match.label : value;
}

function displayCode(value) {
  const text = String(value || '');
  return text.length <= 3 ? text.toUpperCase() : text;
}

function mediaTypeLabels(rules, options, copy) {
  const selected = rules.media_types || [];
  if (!selected.length) {
    return copy.allTypes;
  }
  const all = (options.mediaTypes || []).map(option => option.value);
  if (all.length && selected.length === all.length && all.every(value => selected.includes(value))) {
    return copy.allTypes;
  }
  return selected.map(value => optionLabel(options.mediaTypes, value)).join(', ');
}

function ratingSummary(rules, copy) {
  const base = rules.rating && rules.rating !== 'all'
    ? optionLabel(RATING_OPTIONS, rules.rating)
    : '';
  const min = rules.rating_min ? String(rules.rating_min) : '';
  const max = rules.rating_max ? String(rules.rating_max) : '';
  if (min && max) {
    return `${min} – ${max}`;
  }
  if (min) {
    return `${copy.from} ${min}`;
  }
  if (max) {
    return `${copy.to} ${max}`;
  }
  return base || copy.any;
}

function dateSummary(rules, key, options, copy) {
  const amount = rules[`${key}_within`];
  if (amount) {
    return `${copy.within} ${amount} ${optionLabel(options.relativeUnits || DATE_OPTIONS, rules[`${key}_within_unit`]).toLowerCase()}`;
  }
  const from = rules[`${key}_from`];
  const to = rules[`${key}_to`];
  if (from && to) {
    return `${from} – ${to}`;
  }
  if (from) {
    return `${copy.from} ${from}`;
  }
  if (to) {
    return `${copy.to} ${to}`;
  }
  return '';
}

function summaryChips(rules, options, copy) {
  const chips = [{ key: 'types', label: copy.types, value: mediaTypeLabels(rules, options, copy) }];
  if ((rules.status || []).length) {
    chips.push({
      key: 'status',
      label: copy.status,
      value: rules.status.map(value => optionLabel(options.statuses, value)).join(', '),
    });
  }
  if ((rules.rating && rules.rating !== 'all') || rules.rating_min || rules.rating_max) {
    chips.push({ key: 'rating', label: copy.rating, value: ratingSummary(rules, copy) });
  }
  if (rules.collection && rules.collection !== 'all') {
    chips.push({ key: 'collection', label: copy.collection, value: optionLabel(COLLECTION_OPTIONS, rules.collection) });
  }
  TEXT_KEYS.forEach(key => {
    if (!rules[key]) {
      return;
    }
    const labels = {
      genre: copy.genre,
      implied_genre: copy.impliedGenre,
      source: copy.source,
      language: copy.language,
      country: copy.country,
      platform: copy.platform,
      origin: copy.origin,
      format: copy.format,
      author: copy.author,
      provider: copy.provider,
    };
    const value = ['source', 'language', 'country', 'origin'].includes(key)
      ? displayCode(rules[key])
      : rules[key];
    chips.push({ key, label: labels[key], value });
  });
  if (rules.year) {
    chips.push({
      key: 'year',
      label: copy.year,
      value: rules.year === 'unknown' ? copy.unknown : rules.year,
    });
  }
  if (rules.release && rules.release !== 'all') {
    chips.push({ key: 'release', label: copy.released, value: optionLabel(RELEASE_OPTIONS, rules.release) });
  }
  if ((rules.tag || []).length) {
    const mode = rules.tag_mode && rules.tag_mode !== 'or'
      ? ` (${optionLabel(TAG_MODE_OPTIONS, rules.tag_mode).toLowerCase()})`
      : '';
    chips.push({ key: 'tag', label: copy.tag, value: `${rules.tag.join(', ')}${mode}` });
  }
  if ((rules.list || []).length) {
    const names = rules.list.map(id => optionLabel(options.lists || [], id));
    chips.push({ key: 'list', label: copy.list, value: names.join(', ') });
  }
  DATE_GROUPS.forEach(group => {
    const value = dateSummary(rules, group.key, options, copy);
    if (value) {
      chips.push({ key: group.key, label: group.label, value });
    }
  });
  if (rules.search) {
    chips.push({ key: 'search', label: copy.search, value: `“${rules.search}”` });
  }
  return chips;
}

function isIsoDate(value) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(String(value || ''))) {
    return false;
  }
  const parsed = new Date(`${value}T00:00:00Z`);
  return !Number.isNaN(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value;
}

function validateRules(rules, copy) {
  const errors = {};
  const min = rules.rating_min === '' ? null : Number(rules.rating_min);
  const max = rules.rating_max === '' ? null : Number(rules.rating_max);
  if (rules.rating_min !== '' && (!Number.isFinite(min) || min < 0 || min > 10)) {
    errors.rating_min = copy.ratingRange;
  }
  if (rules.rating_max !== '' && (!Number.isFinite(max) || max < 0 || max > 10)) {
    errors.rating_max = copy.ratingRange;
  }
  if (!errors.rating_min && !errors.rating_max && min != null && max != null && min > max) {
    errors.rating_max = copy.ratingOrder;
  }
  DATE_GROUPS.forEach(group => {
    const from = rules[`${group.key}_from`];
    const to = rules[`${group.key}_to`];
    const amount = rules[`${group.key}_within`];
    if (from && !isIsoDate(from)) {
      errors[`${group.key}_from`] = copy.dateInvalid;
    }
    if (to && !isIsoDate(to)) {
      errors[`${group.key}_to`] = copy.dateInvalid;
    }
    if (!errors[`${group.key}_from`] && !errors[`${group.key}_to`] && from && to && from > to) {
      errors[`${group.key}_to`] = copy.dateOrder;
    }
    if (amount) {
      const parsed = Number(amount);
      if (!Number.isInteger(parsed) || parsed < 1 || parsed > 999) {
        errors[`${group.key}_within`] = copy.windowInvalid;
      }
    }
  });
  return errors;
}

function defaultRules(rules) {
  return {
    ...rules,
    media_types: [],
    status: [],
    rating: 'all',
    rating_min: '',
    rating_max: '',
    collection: 'all',
    genre: '',
    implied_genre: '',
    year: '',
    release: 'all',
    release_from: '',
    release_to: '',
    release_within: '',
    release_within_unit: 'days',
    release_date_from: '',
    release_date_to: '',
    release_date_within: '',
    release_date_within_unit: 'days',
    date_added_from: '',
    date_added_to: '',
    date_added_within: '',
    date_added_within_unit: 'days',
    completed_date_from: '',
    completed_date_to: '',
    completed_date_within: '',
    completed_date_within_unit: 'days',
    source: '',
    language: '',
    country: '',
    platform: '',
    origin: '',
    format: '',
    author: '',
    provider: '',
    tag: [],
    tag_mode: 'or',
    list: [],
    search: '',
  };
}

function Group({ title, hint, children, colors }) {
  return <View style={[styles.group, { borderColor: colors.border }]}>
    <View style={styles.groupHeading}>
      <Text style={[styles.groupTitle, { color: colors.textSecondary }]}>{title}</Text>
      {hint ? <Text style={[styles.groupHint, { color: colors.textMuted }]}>{hint}</Text> : null}
    </View>
    {children}
  </View>;
}

function ChoiceChips({ options, values, multiple = true, onChoose, colors, badges, copy }) {
  const selectedValues = Array.isArray(values) ? values : (values == null || values === '' ? [] : [values]);
  return <View style={styles.chipRow}>
    {options.map(option => {
      const selected = selectedValues.some(value => String(value) === String(option.value ?? option.id));
      return <Badge
        key={option.value ?? option.id}
        label={option.label}
        tone={selected ? 'indigo' : 'outline'}
        palette={badges}
        onPress={() => onChoose(option.value ?? option.id)} />;
    })}
    {multiple && selectedValues.length ? <Badge
      label={copy.clearAll}
      tone="muted"
      palette={badges}
      onPress={() => onChoose(null)} /> : null}
  </View>;
}

function OperatorChips({ options, value, onChoose, badges }) {
  return <View style={styles.chipRow}>
    {options.map(option => <Badge
      key={option.value}
      label={option.label}
      tone={String(value) === String(option.value) ? 'indigo' : 'outline'}
      palette={badges}
      onPress={() => onChoose(option.value)} />)}
  </View>;
}

function DateRuleGroup({ group, rules, errors, copy, colors, onChange }) {
  const set = (key, value) => onChange({ [`${group.key}_${key}`]: value });
  return <Group title={group.label} colors={colors}>
    <View style={styles.inlineFields}>
      <View style={styles.inlineField}>
        <FormTextField label={copy.from} value={rules[`${group.key}_from`] || ''}
          onChangeText={value => set('from', value)} error={errors[`${group.key}_from`]}
          palette={colors} placeholder="YYYY-MM-DD" />
      </View>
      <View style={styles.inlineField}>
        <FormTextField label={copy.to} value={rules[`${group.key}_to`] || ''}
          onChangeText={value => set('to', value)} error={errors[`${group.key}_to`]}
          palette={colors} placeholder="YYYY-MM-DD" />
      </View>
      <View style={styles.inlineField}>
        <FormTextField label={copy.amount} value={String(rules[`${group.key}_within`] || '')}
          onChangeText={value => set('within', value)} error={errors[`${group.key}_within`]}
          palette={colors} keyboardType="number-pad" placeholder="7" />
      </View>
      <View style={styles.inlineField}>
        <FormSelect label={copy.unit} value={rules[`${group.key}_within_unit`] || 'days'}
          options={DATE_OPTIONS} onChange={value => set('within_unit', value)} palette={colors} />
      </View>
    </View>
  </Group>;
}

export function SmartRuleSummary({
  rules = {},
  options = {},
  editMode = false,
  saveState = 'idle',
  labels,
  palette,
}) {
  const colors = mergePalette(palette);
  const copy = mergeLabels(labels);
  const badges = badgePalette(colors);
  const chips = summaryChips(rules, options, copy);
  const stateLabel = saveState === 'saving' ? copy.saving
    : saveState === 'error' ? copy.saveFailed
      : saveState === 'saved' ? copy.saved
        : editMode ? copy.editActive : '';
  const stateColor = saveState === 'saving' ? colors.warning || colors.accent
    : saveState === 'error' ? colors.danger : colors.link;
  return <View style={[styles.summary, { backgroundColor: colors.surface }]}>
    <View style={styles.summaryHeading}>
      <Text style={[styles.summaryTitle, { color: colors.textSecondary }]}>{copy.title}</Text>
      {stateLabel ? <Text style={[styles.state, { color: stateColor }]}>{stateLabel}</Text> : null}
    </View>
    <View style={styles.chipRow}>
      {chips.map(chip => <View key={chip.key} style={[styles.summaryChip, { backgroundColor: colors.surfaceStrong }]}>
        <Text style={[styles.summaryChipLabel, { color: colors.textMuted }]}>{chip.label}:</Text>
        <Text style={[styles.summaryChipValue, { color: colors.textSecondary }]}>{chip.value}</Text>
      </View>)}
    </View>
    {editMode ? <Text style={[styles.help, { color: colors.textMuted }]}>{copy.editing}</Text> : null}
  </View>;
}

export function SmartRuleBuilder({
  rules = {},
  options = {},
  editMode = false,
  canEdit = false,
  busy = false,
  saveState = 'idle',
  labels,
  palette,
  onChange,
  onSave,
  onCancel,
}) {
  const colors = mergePalette(palette);
  const copy = mergeLabels(labels);
  const badges = badgePalette(colors);
  const [errors, setErrors] = useState({});
  const [showAllGroups, setShowAllGroups] = useState(true);
  const readOnly = !canEdit;
  const update = patch => {
    setErrors(current => {
      const next = { ...current };
      Object.keys(patch).forEach(key => delete next[key]);
      return next;
    });
    onChange?.({ ...rules, ...patch });
  };
  const toggle = (key, value) => {
    if (value == null) {
      update({ [key]: [] });
      return;
    }
    const current = rules[key] || [];
    update({
      [key]: current.some(entry => String(entry) === String(value))
        ? current.filter(entry => String(entry) !== String(value))
        : [...current, value],
    });
  };
  const save = () => {
    const nextErrors = validateRules(rules, copy);
    setErrors(nextErrors);
    if (Object.keys(nextErrors).length) {
      return;
    }
    onSave?.(rules);
  };
  const clear = () => {
    setErrors({});
    onChange?.(defaultRules(rules));
  };
  const show = key => options[`show${key[0].toUpperCase()}${key.slice(1)}`] !== false;

  return <View style={[styles.builder, { backgroundColor: colors.surface, borderColor: colors.border }]}>
    <View style={styles.builderHeader}>
      <View style={styles.builderTitleBlock}>
        <Text accessibilityRole="header" style={[styles.builderTitle, { color: colors.text }]}>{copy.title}</Text>
        <Text style={[styles.help, { color: colors.textMuted }]}>
          {readOnly ? copy.viewOnly : editMode ? copy.editing : copy.tierRule}
        </Text>
      </View>
      <View style={styles.builderActions}>
        <Button label={showAllGroups ? copy.hideFilters : copy.showFilters} tone="surface"
          onPress={() => setShowAllGroups(current => !current)} palette={colors} />
        <Button label={copy.clearAll} tone="surface" onPress={clear} palette={colors} />
        {editMode ? <Button label={saveState === 'saving' ? copy.saving : copy.saveRules}
          tone="primary" busy={busy || saveState === 'saving'} disabled={busy || saveState === 'saving'}
          onPress={save} palette={colors} /> : null}
        {editMode && onCancel ? <Button label={copy.cancel} tone="surface" onPress={onCancel} palette={colors} /> : null}
      </View>
    </View>

    {Object.keys(errors).length ? <FormError message={copy.validation} palette={colors} /> : null}

    {showAllGroups ? <View style={styles.groupsContent}>
      <Group title={copy.types} colors={colors}>
        <ChoiceChips options={options.mediaTypes || []} values={rules.media_types}
          onChoose={value => toggle('media_types', value)} colors={colors} badges={badges} copy={copy} />
      </Group>

      <Group title={copy.status} colors={colors}>
        <ChoiceChips options={options.statuses || []} values={rules.status}
          onChoose={value => toggle('status', value)} colors={colors} badges={badges} copy={copy} />
      </Group>

      <Group title={copy.rating} hint={`${copy.min} / ${copy.max}`} colors={colors}>
        <OperatorChips options={RATING_OPTIONS} value={rules.rating || 'all'}
          onChoose={value => update({ rating: value })} badges={badges} />
        <View style={styles.inlineFields}>
          <View style={styles.inlineField}>
            <FormTextField label={copy.min} value={String(rules.rating_min || '')}
              onChangeText={value => update({ rating_min: value })} error={errors.rating_min}
              palette={colors} keyboardType="decimal-pad" placeholder={copy.minPlaceholder} />
          </View>
          <View style={styles.inlineField}>
            <FormTextField label={copy.max} value={String(rules.rating_max || '')}
              onChangeText={value => update({ rating_max: value })} error={errors.rating_max}
              palette={colors} keyboardType="decimal-pad" placeholder={copy.maxPlaceholder} />
          </View>
        </View>
      </Group>

      <Group title={copy.collection} colors={colors}>
        <OperatorChips options={COLLECTION_OPTIONS} value={rules.collection || 'all'}
          onChoose={value => update({ collection: value })} badges={badges} />
      </Group>

      <Group title={copy.released} colors={colors}>
        <OperatorChips options={RELEASE_OPTIONS} value={rules.release || 'all'}
          onChoose={value => update({ release: value })} badges={badges} />
      </Group>

      {show('genres') && (options.genres || []).length ? <Group title={copy.genre} colors={colors}>
        <ChoiceChips options={(options.genres || []).map(value => ({ value, label: value }))}
          values={rules.genre ? [rules.genre] : []} multiple={false}
          onChoose={value => update({ genre: value || '' })} colors={colors} badges={badges} copy={copy} />
      </Group> : null}

      {show('impliedGenres') && (options.impliedGenres || []).length ? <Group title={copy.impliedGenre} colors={colors}>
        <ChoiceChips options={(options.impliedGenres || []).map(value => ({ value, label: value }))}
          values={rules.implied_genre ? [rules.implied_genre] : []} multiple={false}
          onChoose={value => update({ implied_genre: value || '' })} colors={colors} badges={badges} copy={copy} />
      </Group> : null}

      {show('years') && (options.years || []).length ? <Group title={copy.year} colors={colors}>
        <ChoiceChips options={options.years} values={rules.year ? [rules.year] : []} multiple={false}
          onChoose={value => update({ year: value || '' })} colors={colors} badges={badges} copy={copy} />
      </Group> : null}

      {show('sources') && (options.sources || []).length ? <Group title={copy.source} colors={colors}>
        <ChoiceChips options={options.sources} values={rules.source ? [rules.source] : []} multiple={false}
          onChoose={value => update({ source: value || '' })} colors={colors} badges={badges} copy={copy} />
      </Group> : null}

      {show('languages') && (options.languages || []).length ? <Group title={copy.language} colors={colors}>
        <ChoiceChips options={options.languages} values={rules.language ? [rules.language] : []} multiple={false}
          onChoose={value => update({ language: value || '' })} colors={colors} badges={badges} copy={copy} />
      </Group> : null}

      {show('countries') && (options.countries || []).length ? <Group title={copy.country} colors={colors}>
        <ChoiceChips options={options.countries} values={rules.country ? [rules.country] : []} multiple={false}
          onChoose={value => update({ country: value || '' })} colors={colors} badges={badges} copy={copy} />
      </Group> : null}

      {show('platforms') && (options.platforms || []).length ? <Group title={copy.platform} colors={colors}>
        <ChoiceChips options={options.platforms} values={rules.platform ? [rules.platform] : []} multiple={false}
          onChoose={value => update({ platform: value || '' })} colors={colors} badges={badges} copy={copy} />
      </Group> : null}

      {show('origins') && (options.origins || []).length ? <Group title={copy.origin} colors={colors}>
        <ChoiceChips options={options.origins} values={rules.origin ? [rules.origin] : []} multiple={false}
          onChoose={value => update({ origin: value || '' })} colors={colors} badges={badges} copy={copy} />
      </Group> : null}

      {show('formats') && (options.formats || []).length ? <Group title={copy.format} colors={colors}>
        <ChoiceChips options={options.formats} values={rules.format ? [rules.format] : []} multiple={false}
          onChoose={value => update({ format: value || '' })} colors={colors} badges={badges} copy={copy} />
      </Group> : null}

      {show('authors') && (options.authors || []).length ? <Group title={options.authorIsChannel ? copy.channel : copy.author} colors={colors}>
        <ChoiceChips options={options.authors} values={rules.author ? [rules.author] : []} multiple={false}
          onChoose={value => update({ author: value || '' })} colors={colors} badges={badges} copy={copy} />
      </Group> : null}

      {show('providers') && (options.providers || []).length ? <Group title={copy.provider} colors={colors}>
        <ChoiceChips options={options.providers} values={rules.provider ? [rules.provider] : []} multiple={false}
          onChoose={value => update({ provider: value || '' })} colors={colors} badges={badges} copy={copy} />
      </Group> : null}

      {(options.lists || []).length ? <Group title={copy.list} colors={colors}>
        <ChoiceChips options={options.lists} values={rules.list}
          onChoose={value => toggle('list', value)} colors={colors} badges={badges} copy={copy} />
      </Group> : null}

      <Group title={copy.tag} hint={copy.tagOperator} colors={colors}>
        <OperatorChips options={TAG_MODE_OPTIONS} value={rules.tag_mode || 'or'}
          onChoose={value => update({ tag_mode: value })} badges={badges} />
        <ChoiceChips options={(options.tags || []).map(value => ({ value, label: value }))}
          values={rules.tag} onChoose={value => toggle('tag', value)}
          colors={colors} badges={badges} copy={copy} />
      </Group>

      <DateRuleGroup group={DATE_GROUPS[0]} rules={rules} errors={errors} copy={copy}
        colors={colors} onChange={update} />
      <DateRuleGroup group={DATE_GROUPS[1]} rules={rules} errors={errors} copy={copy}
        colors={colors} onChange={update} />
      <DateRuleGroup group={DATE_GROUPS[2]} rules={rules} errors={errors} copy={copy}
        colors={colors} onChange={update} />

      <Group title={copy.search} colors={colors}>
        <FormTextField label={copy.search} value={rules.search || ''}
          onChangeText={value => update({ search: value })} palette={colors}
          placeholder={copy.searchPlaceholder} />
      </Group>
    </View> : null}

    {readOnly ? <Text style={[styles.help, { color: colors.textMuted }]}>{copy.viewOnly}</Text> : null}
  </View>;
}

const styles = StyleSheet.create({
  summary: { borderRadius: 10, padding: 12, gap: 8 },
  summaryHeading: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 8 },
  summaryTitle: { fontSize: 12, fontWeight: '700', textTransform: 'uppercase', letterSpacing: 0.5 },
  state: { fontSize: 12, fontWeight: '600' },
  summaryChip: { flexDirection: 'row', alignItems: 'center', gap: 4, borderRadius: 6, paddingHorizontal: 8, paddingVertical: 4, maxWidth: '100%' },
  summaryChipLabel: { fontSize: 11, fontWeight: '700' },
  summaryChipValue: { flexShrink: 1, fontSize: 11 },
  builder: { borderWidth: 1, borderRadius: 10, padding: 12, gap: 10 },
  builderHeader: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'flex-start', justifyContent: 'space-between', gap: 8 },
  builderTitleBlock: { flexShrink: 1, minWidth: 0, gap: 2 },
  builderTitle: { fontSize: 17, fontWeight: '700' },
  builderActions: { flexDirection: 'row', flexWrap: 'wrap', gap: 6 },
  groupsContent: { gap: 10 },
  group: { borderTopWidth: 1, paddingTop: 10, gap: 8 },
  groupHeading: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 8 },
  groupTitle: { fontSize: 12, fontWeight: '700', textTransform: 'uppercase', letterSpacing: 0.5 },
  groupHint: { flexShrink: 1, fontSize: 11, textAlign: 'right' },
  chipRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 6 },
  inlineFields: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  inlineField: { flexGrow: 1, flexBasis: 130, minWidth: 110 },
  help: { fontSize: 12, lineHeight: 17 },
});
