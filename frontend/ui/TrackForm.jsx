import React, { useRef, useState } from 'react';
import { Pressable, ScrollView, StyleSheet, Text, TextInput, View, useWindowDimensions } from 'react-native';
import { Button } from './Button';
import { Icon } from './Icon';
import { Title } from './Title';
import { ModalCloseButton } from './Modal';
import { DateTimePicker } from './DateTimePicker';
import {
  FormError,
  FormField,
  FormHeader,
  FormStatus,
  FormTextField,
} from './MediaCardFormControls';
import { MarkdownNotes } from './MarkdownNotes';
import { RatingStars } from './RatingStars';
import { SelectField } from './SelectField';
import { TrackTabs, trackTabItems } from './TrackFormTabs';
import { CollectionGroup, CollectionRow, CollectionSelectRow, CollectionTextRow } from './CollectionCopies';
import { scoreInputToStored, validateTrackValues } from './mediaCardForms';
import { actionIcons } from './actionIcons';
import { TrackDateRow } from './TrackDateRow';
import { formatTrackDuration, parseTrackDurationMinutes } from './trackDuration';
import { valueFromDate } from './dateTime';
import { RatingCriteriaSheet, RatingScaleButton } from './RatingCriteriaSheet';
import { overallSummary } from './ratingScaleModel';

const MOBILE_WEB_MAX_WIDTH = 1024;

const DEFAULT_LABELS = {
  title: 'Tracking',
  close: 'Close',
  loading: 'Loading',
  loadFailed: "Couldn't load this form.",
  retry: 'Try again',
  save: 'Save',
  saving: 'Saving',
  delete: 'Delete',
  required: '%s is required.',
  invalidNumber: 'Enter a number.',
  minimum: 'Must be at least %s.',
  maximum: 'Must be at most %s.',
  dateOrder: 'End date must be on or after the start date.',
  dateTime: {},
};

const DEFAULT_PALETTE = {
  text: '#fafafa',
  textSecondary: '#d4d4d8',
  textMuted: '#a1a1aa',
  surface: '#27272a',
  surfaceDim: '#18181b',
  surfaceStrong: '#3f3f46',
  border: '#3f3f46',
  inputBorder: '#4b5563',
  accent: '#6366f1',
  accentContrast: '#ffffff',
  danger: '#f87171',
  radius: 8,
  focusStyle: {},
  dateTime: {},
  rating: {
    lit: '#f59e0b',
    unlit: '#52525b',
    muted: '#a1a1aa',
    focusStyle: {},
  },
};

// Same two strokes as templates/app/icons/x.svg, so the close button matches the old dialog.
const X_ICON = {
  viewBox: '0 0 24 24',
  root: { fill: 'none', stroke: 'currentColor', 'stroke-width': '2', 'stroke-linecap': 'round', 'stroke-linejoin': 'round' },
  children: [
    { tag: 'path', attrs: { d: 'M18 6 6 18' }, children: [] },
    { tag: 'path', attrs: { d: 'm6 6 12 12' }, children: [] },
  ],
};

const chevron = d => ({
  viewBox: '0 0 24 24',
  root: { fill: 'none', stroke: 'currentColor', 'stroke-width': '2', 'stroke-linecap': 'round', 'stroke-linejoin': 'round' },
  children: [{ tag: 'path', attrs: { d }, children: [] }],
});
const CHEVRON_UP = chevron('m18 15-6-6-6 6');
const CHEVRON_DOWN = chevron('m6 9 6 6 6-6');

function stepValue(value, field, direction) {
  const step = Number(field.step) || 1;
  const current = value === '' || value == null ? null : Number(value);
  let next = (Number.isFinite(current) ? current : (direction > 0 ? (field.min ?? 0) - step : (field.max ?? 0) + step))
    + direction * step;
  if (field.min != null) next = Math.max(Number(field.min), next);
  if (field.max != null) next = Math.min(Number(field.max), next);
  const decimals = (String(step).split('.')[1] || '').length;
  return next.toFixed(decimals);
}

function NumberStepper({ field, value, onChange, error, palette, labels }) {
  const colors = { color: palette.textSecondary };
  const button = (direction, icon, name) => <Pressable accessibilityRole="button"
    accessibilityLabel={`${name} ${field.label}`} onPress={() => onChange(stepValue(value, field, direction))}
    style={({ hovered }) => [styles.stepButton, { borderColor: palette.inputBorder || palette.border,
      backgroundColor: hovered ? palette.surfaceMuted : 'transparent' }]}>
    <Icon spec={icon} color={colors.color} size={14} />
  </Pressable>;
  return <View>
    <TextInput accessibilityLabel={field.label} keyboardType="numeric" value={String(value)}
      placeholder={field.placeholder} placeholderTextColor={palette.textMuted}
      onChangeText={onChange} selectionColor={palette.accent}
      style={[styles.numberInput, { backgroundColor: palette.surfaceStrong,
        borderColor: error ? palette.danger : (palette.inputBorder || palette.border), color: palette.text }]} />
    <View style={styles.stepper}>
      {button(1, CHEVRON_UP, labels.increase || 'Increase')}
      {button(-1, CHEVRON_DOWN, labels.decrease || 'Decrease')}
    </View>
  </View>;
}

function fieldType(field) {
  if (field.options?.length) return 'select';
  if (field.type === 'date' || field.name === 'start_date' || field.name === 'end_date') return 'date';
  if (field.type === 'textarea') return 'textarea';
  if (field.type === 'number') return 'number';
  if (field.type === 'rating') return 'rating';
  return 'text';
}

function HeaderBar({ title, subtitle, closeLabel, onClose, closeRef, palette }) {
  return <View style={[styles.bar, { backgroundColor: palette.surface, borderColor: palette.border }]}>
    <View style={styles.barText}>
      <Title size="bar" numberOfLines={2} color={palette.text}>{title}</Title>
      {subtitle ? <Text style={[styles.barSubtitle, { color: palette.textMuted }]}>{subtitle}</Text> : null}
    </View>
    {onClose ? <ModalCloseButton ref={closeRef} accessibilityRole="button" accessibilityLabel={closeLabel}
      onPress={onClose} style={({ focused }) => [styles.barClose, focused && palette.focusStyle]}>
      <Icon spec={X_ICON} color={palette.textMuted} size={20} />
    </ModalCloseButton> : null}
  </View>;
}

// Stored 0-10 score -> the number a viewer sees on a 5 or 10 scale.
function scoreToScale(stored, scaleMax) {
  if (stored === '' || stored == null || !Number.isFinite(Number(stored))) return '';
  return String(Number((Number(stored) * scaleMax / 10).toFixed(1)));
}

// Score typed on the viewer's scale (5 or 10) in tenths, as the desktop web form allows (step 0.1).
// The text is kept while typing ("7," is not a number yet); the form value stays on the stored 0-10 scale.
function ScoreRow({ field, value, icon, error, placeholder, palette, onChange }) {
  const scaleMax = field.scaleMax || 10;
  const [draft, setDraft] = useState(null);
  const shown = draft ?? scoreToScale(value, scaleMax);
  return <CollectionTextRow icon={icon} label={field.label} value={shown} error={error}
    placeholder={placeholder} palette={palette} keyboardType="decimal-pad"
    onChangeText={next => { setDraft(next); onChange(scoreInputToStored(next, scaleMax)); }} />;
}

// Progress typed as a duration reads as hrs and min ("2h 15min") until it is being edited.
function DurationRow({ field, value, icon, error, minuteCount, palette, onChange }) {
  const [editing, setEditing] = useState(false);
  const minutes = minuteCount ? Math.trunc(Number(value)) || 0 : parseTrackDurationMinutes(value);
  const shown = !editing && minutes ? formatTrackDuration(minutes) : String(value);
  return <View>
    <CollectionRow icon={icon} label={field.label} palette={palette}>
      <TextInput accessibilityLabel={field.label} value={shown} onChangeText={onChange}
        keyboardType={minuteCount ? 'number-pad' : 'default'}
        onFocus={() => setEditing(true)} onBlur={() => setEditing(false)}
        placeholder={field.placeholder} placeholderTextColor={palette.textMuted} selectionColor={palette.accent}
        style={[styles.durationInput, { color: palette.textSecondary }]} />
    </CollectionRow>
    {error ? <Text accessibilityLiveRegion="polite" style={[styles.rowError, { color: palette.danger }]}>{error}</Text> : null}
  </View>;
}

export function TrackForm({
  model,
  values = {},
  errors = {},
  status = 'ready',
  serverError = '',
  busy = false,
  labels: suppliedLabels,
  palette: suppliedPalette,
  onChange,
  onSubmit,
  onDelete,
  onRetry,
  onClose,
  showHeader = true,
  closeRef,
  nativeID,
  tabs = [],
  generalPrefix,
  activeTab,
  onTabChange,
  railTabs = false,
  onRetryTabs,
  onTagToggle,
  onTagCreate,
  onArtworkSave,
  onDiscoverToggle,
  secondaryActions = [],
  embedded = false,
  grouped = false,
  // Grouped-list contents inside the host's own tab navigation and footer (web).
  groupedContent = false,
  renderSelectPicker,
  renderMonthYearWheels,
  renderTimeWheels,
  renderNumberWheel,
}) {
  const labels = { ...DEFAULT_LABELS, ...(suppliedLabels || {}) };
  const palette = { ...DEFAULT_PALETTE, ...(suppliedPalette || {}) };
  const ratingPalette = { ...DEFAULT_PALETTE.rating, ...(palette.rating || {}) };
  const { height, width } = useWindowDimensions();
  const wide = width >= 640;
  const [localErrors, setLocalErrors] = useState({});
  const [localTab, setLocalTab] = useState('general');
  const [since, setSince] = useState('');
  // The one open date picker, { name, mode }; opening another closes it.
  const [ratingOpen, setRatingOpen] = useState(false);
  const ratingSnapshot = useRef(null);
  const [openPicker, setOpenPicker] = useState(null);
  // The preset last applied, with the dates it set; changing either date clears it.
  const [appliedPreset, setAppliedPreset] = useState(null);
  const fieldErrors = { ...errors, ...localErrors };
  const selectedTab = activeTab === undefined ? localTab : activeTab;

  function selectTab(id) {
    if (activeTab === undefined) setLocalTab(id);
    onTabChange?.(id);
  }

  function runtimeOf(field) {
    const minutes = Number(field.runtimeMinutes);
    return Number.isFinite(minutes) && minutes > 0 ? minutes : 0;
  }

  // Picking a release date as the end back-fills an empty start a runtime earlier.
  function changeDate(field, next, detail) {
    change(field.name, next);
    const runtime = runtimeOf(field);
    if (field.name === 'end_date' && next && runtime && !values.start_date
      && detail?.source === 'suggestion') {
      const end = new Date(String(next).includes('T') ? next : `${next}T00:00`);
      if (!Number.isNaN(end.getTime())) {
        change('start_date', valueFromDate(new Date(end.getTime() - runtime * 60000),
          Boolean(model.trackTime)));
      }
    }
  }

  function quickDate(field, action) {
    const trackTime = Boolean(model.trackTime);
    const runtime = runtimeOf(field);
    const moment = new Date();
    if (action === 'release-date') {
      change(field.name, field.suggestionDate || '');
    } else if (action === 'just-finished') {
      change('end_date', valueFromDate(moment, trackTime));
      if (runtime && !values.start_date) {
        change('start_date', valueFromDate(new Date(moment.getTime() - runtime * 60000), trackTime));
      }
    } else {
      change('start_date', valueFromDate(moment, trackTime));
      if (runtime && !values.end_date) {
        change('end_date', valueFromDate(new Date(moment.getTime() + runtime * 60000), trackTime));
      }
      if (['', 'Completed', 'Planning'].includes(values.status ?? '')) {
        change('status', 'In progress');
      }
    }
  }

  // Presets for the Start and End rows. Each sets both dates; where the runtime is unknown the other date is
  // the same moment. Ended sets only the End.
  function applyPreset(id) {
    const trackTime = Boolean(model.trackTime);
    const dateField = (model.fields || []).find(field => field.name === 'start_date')
      || (model.fields || []).find(field => field.name === 'end_date') || {};
    const span = runtimeOf(dateField) * 60000;
    const now = new Date();
    const at = moment => valueFromDate(moment, trackTime);
    let start = values.start_date ?? '';
    let end = values.end_date ?? '';
    if (id === 'start-now') {
      start = at(now);
      end = at(new Date(now.getTime() + span));
    } else if (id === 'just-finished') {
      end = at(now);
      start = at(new Date(now.getTime() - span));
    } else if (id === 'ended') {
      end = at(now);
    } else if (id === 'release-date' && dateField.suggestionDate) {
      const released = new Date(`${dateField.suggestionDate}T00:00`);
      if (Number.isNaN(released.getTime())) return;
      start = at(released);
      end = at(new Date(released.getTime() + span));
    }
    change('start_date', start);
    change('end_date', end);
    if (id === 'start-now' && ['', 'Completed', 'Planning'].includes(values.status ?? '')) change('status', 'In progress');
    setAppliedPreset({ id, start, end });
    // Close the open picker so the new dates show at once.
    setOpenPicker(null);
  }
  const presetSource = (model?.fields || []).find(field => field.name === 'start_date') || {};
  // The picker shows the applied preset until either date changes, then returns to Choose.
  const activePreset = appliedPreset && appliedPreset.start === (values.start_date ?? '')
    && appliedPreset.end === (values.end_date ?? '') ? appliedPreset.id : '';
  const presets = {
    label: labels.presets || 'Presets', placeholder: labels.choosePreset || 'Choose', value: activePreset,
    onSelect: applyPreset,
    options: [
      { value: 'start-now', label: labels.startNow || 'Start Now' },
      ...(presetSource.suggestionDate ? [{ value: 'release-date', label: labels.releaseDate || 'Release Date' }] : []),
      { value: 'just-finished', label: labels.justFinished || 'Just Finished' },
      { value: 'ended', label: labels.ended || 'Ended' },
    ],
  };

  // Remember the rating values when the sheet opens so Cancel can put them back.
  function openRating() {
    ratingSnapshot.current = Object.fromEntries(Object.keys(values)
      .filter(key => key.startsWith('criterion:') || key === 'score' || key === 'score_is_manual')
      .map(key => [key, values[key]]));
    setRatingOpen(true);
  }
  function cancelRating() {
    Object.entries(ratingSnapshot.current || {}).forEach(([key, value]) => change(key, value));
    setRatingOpen(false);
  }

  function change(name, value) {
    if (localErrors[name]) setLocalErrors(current => ({ ...current, [name]: '' }));
    onChange?.(name, value);
  }

  function validate() {
    const next = validateTrackValues(model, values, labels);
    setLocalErrors(next);
    return Object.keys(next).length === 0;
  }

  function submit() {
    if (!validate()) return;
    onSubmit?.(values);
  }

  function runSecondary(action) {
    if (!validate()) return;
    action.onPress?.(action.needsSince ? { ...values, rewatch_started_at: since } : values);
  }

  const sidebar = !embedded && tabs.length > 0;
  // `grouped` is the whole native layout; `groupedContent` takes only its rows and tab bodies, and only
  // where the app shell is in its mobile layout (under 1024 px, so phones and an open iPhone Duo; desktop
  // web keeps its two-column form). The tab navigation keeps its own 640 px rule.
  const contentGrouped = groupedContent && width < MOBILE_WEB_MAX_WIDTH;
  const groupedRows = grouped || contentGrouped;
  const inputPalette = { ...palette, border: palette.inputBorder || palette.border };
  // Native iOS layout (grouped = true): grouped lists of 50 pt rows with a leading icon, like the
  // Collection modal. Dates get their own section.
  const rowIcons = { status: actionIcons.circleCheck, score: actionIcons.star, rating: actionIcons.star,
    progress: actionIcons.historyClock, start_date: actionIcons.calendar, end_date: actionIcons.calendar };
  // While a date picker is open the group drops its icons, so the dividers start at the labels.
  const datesOpen = Boolean(openPicker);
  // The grouped rows speak Expo's plain copy: a form that comes from the server carries its own wording
  // ("Progress (Time Played)", "e.g. Plex, Jellyfin...") that the native sheet never shows.
  const plainField = source => ({ ...source, placeholder: '',
    label: source.name === 'progress' ? (labels.progress || 'Progress') : source.label });
  const rowFor = source => {
    const field = plainField(source);
    const type = fieldType(field);
    const value = values[field.name] == null ? '' : values[field.name];
    const error = fieldErrors[field.name];
    const icon = rowIcons[field.name] || (type === 'date' ? actionIcons.calendar : actionIcons.page);
    const errorText = error ? <Text accessibilityLiveRegion="polite" style={[styles.rowError, { color: palette.danger }]}>{error}</Text> : null;
    // A custom rating scale replaces the score picker with a button that opens the criteria sheet.
    if (field.name === 'score' && field.ratingScale) {
      const summary = overallSummary(field.ratingScale, values);
      return <RatingScaleButton key={field.name} grouped icon={icon} label={field.label} error={error} palette={palette}
        placeholder={labels.addRating || 'Add Rating'} value={summary.shown}
        onPress={openRating} />;
    }
    if (type === 'select') {
      return <CollectionSelectRow key={field.name} icon={icon} label={field.label} error={error}
        palette={palette} filter popover renderPicker={renderSelectPicker} value={value} options={field.options}
        onChange={event => change(field.name, event.target.value)} />;
    }
    if (type === 'date') {
      // Short labels keep the date and time buttons on one line.
      const dateLabel = field.name === 'start_date' ? (labels.start || 'Start') : field.name === 'end_date' ? (labels.end || 'End') : field.label;
      return <TrackDateRow key={field.name} label={dateLabel} icon={datesOpen ? undefined : icon}
        mode={openPicker?.name === field.name ? openPicker.mode : null}
        onModeChange={mode => setOpenPicker(mode ? { name: field.name, mode } : null)} value={value} error={error}
        trackTime={Boolean(model.trackTime)} palette={palette} labels={labels.dateTime || {}}
        onChange={(next, detail) => changeDate(field, next, detail)}
        renderMonthYear={renderMonthYearWheels} renderTime={renderTimeWheels} />;
    }
    // Durations read as hrs and min: typed ones (game time, reading time) and numeric minutes.
    const minuteCount = type === 'number' && field.name === 'progress' && field.unit === 'minutes';
    if ((type === 'text' && ['progress', 'reading_time'].includes(field.name)) || minuteCount) {
      return <DurationRow key={field.name} field={field} value={value} icon={icon} error={error}
        minuteCount={minuteCount} palette={palette} onChange={next => change(field.name, next)} />;
    }
    // Score: typed on the viewer's scale (5 or 10, else 10) in tenths, like the desktop web form;
    // a decimal comma reads as a point. A whole-number picker could not hold 7.5.
    if (field.name === 'score' && type === 'number') {
      return <ScoreRow key={field.name} field={field} value={value} icon={icon} error={error}
        placeholder={labels.addRating || 'Add Rating'} palette={palette}
        onChange={next => change(field.name, next)} />;
    }
    // Number and text fields are one inline input; the stepper buttons are a web control.
    return <CollectionTextRow key={field.name} icon={icon} label={field.label} value={value}
      error={error} placeholder={field.placeholder} palette={palette}
      keyboardType={type === 'number' ? 'decimal-pad' : 'default'}
      onChangeText={next => change(field.name, next)} />;
  };
  const groupedFields = groupedRows ? (model?.fields || []).filter(field => field.name !== 'notes') : [];
  // The native sheet's order: Status, Score, Progress, then the rest as the form lists them.
  const rowRank = field => { const index = ['status', 'score', 'progress'].indexOf(field.name); return index < 0 ? 3 : index; };
  const groupedMain = groupedFields.filter(field => fieldType(field) !== 'date')
    .map((field, index) => ({ field, index }))
    .sort((a, b) => rowRank(a.field) - rowRank(b.field) || a.index - b.index)
    .map(entry => rowFor(entry.field));
  const groupedDates = groupedFields.filter(field => fieldType(field) === 'date').map(rowFor);
  // Presets sit under the End row and set Start and End together.
  if (groupedDates.length) {
    groupedDates.push(<CollectionSelectRow key="date-presets" icon={datesOpen ? undefined : actionIcons.alarmClock} label={presets.label}
      palette={palette} filter popover renderPicker={renderSelectPicker} value={presets.value}
      options={[{ value: '', label: presets.label, displayLabel: presets.placeholder }, ...presets.options]}
      onChange={event => { if (event.target.value) presets.onSelect(event.target.value); }} />);
  }
  const cells = (model?.fields || []).filter(field => field.name !== 'notes').map(field => {
    const type = fieldType(field);
    const value = values[field.name] == null ? '' : values[field.name];
    let control;
    if (field.name === 'score' && field.ratingScale) {
      const summary = overallSummary(field.ratingScale, values);
      control = <FormField label={field.label} required={field.required} help={field.help}
        error={fieldErrors[field.name]} palette={palette}>
        <RatingScaleButton label={field.label} palette={inputPalette} placeholder={labels.addRating || 'Add Rating'}
          value={summary.shown} error={fieldErrors[field.name]}
          onPress={openRating} />
      </FormField>;
    } else if (type === 'select') {
      control = <FormField label={field.label} required={field.required} help={field.help}
        error={fieldErrors[field.name]} palette={palette}>
        <SelectField labelHidden filter label={field.label} accessibilityLabel={`${field.label}: ${
          (field.options.find(option => String(option.value) === String(value)) || {}).label ?? ''}`}
        value={value} options={field.options} palette={inputPalette}
        onChange={event => change(field.name, event.target.value)} />
      </FormField>;
    } else if (type === 'date') {
      control = <FormField label={field.label} required={field.required}
        help={field.help} error={fieldErrors[field.name]} palette={palette}>
        <DateTimePicker value={value}
          onChange={(next, detail) => changeDate(field, next, detail)}
          trackTime={Boolean(model.trackTime)} labels={labels.dateTime || {}}
          palette={palette.dateTime || {}}
          quickActions={field.quickActions || []}
          suggestionDate={field.suggestionDate || ''}
          suggestionLabel={field.suggestionLabel || ''}
          suggestionExtras={field.suggestionExtras || []}
          runtimeMinutes={field.runtimeMinutes || ''}
          copyValue={field.copyFrom ? (values[field.copyFrom] || '') : ''}
          copyLabel={field.copyFromLabel || ''}
          copyEmptyMessage={field.copyEmptyMessage || ''}
          onQuickAction={action => quickDate(field, action)} />
      </FormField>;
    } else if (type === 'rating') {
      const scaleMax = Math.max(1, Number(field.max) || 10);
      const numeric = value === '' ? null : Number(value);
      control = <FormField label={field.label} required={field.required}
        help={field.help} error={fieldErrors[field.name]} palette={palette}>
        <RatingStars scaleMax={scaleMax} value={Number.isFinite(numeric) ? numeric : null}
          label={field.label} palette={ratingPalette}
          onSelect={next => change(field.name, next == null ? '' : String(next))}
          renderStar={lit => <Text style={[styles.ratingStar, {
            color: lit ? ratingPalette.lit : ratingPalette.unlit,
          }]}>★</Text>} />
      </FormField>;
    } else if (type === 'number') {
      control = <FormField label={field.label} required={field.required}
        help={field.help} error={fieldErrors[field.name]} palette={palette}>
        <NumberStepper field={field} value={value} onChange={next => change(field.name, next)}
          error={fieldErrors[field.name]} palette={palette} labels={labels} />
      </FormField>;
    } else {
      control = <FormTextField label={field.label} value={value}
        onChangeText={next => change(field.name, next)} required={field.required}
        help={field.help} error={fieldErrors[field.name]} placeholder={field.placeholder}
        keyboardType={type === 'number' ? 'numeric' : 'default'}
        multiline={type === 'textarea'} palette={inputPalette} />;
    }
    return <View key={field.name} style={sidebar && wide ? styles.cell : styles.fullCell}>{control}</View>;
  });
  const notes = (model?.fields || []).filter(field => field.name === 'notes').map(field => <MarkdownNotes
    key={field.name} label={field.label} value={values[field.name] == null ? '' : values[field.name]}
    onChangeText={next => change(field.name, next)} hint={field.help}
    placeholder={labels.notesPlaceholder || 'Add any notes or comments...'}
    grouped={groupedRows}
    error={fieldErrors[field.name]} palette={groupedRows ? palette : inputPalette} />);
  const deleteButton = model?.deleteAction && onDelete
    ? <Button label={labels.delete} tone="danger-solid" disabled={busy}
      onPress={() => onDelete(values)} palette={palette} /> : null;
  const renderSecondary = action => <View key={action.key} style={styles.secondary}>
    <Button label={action.label} tone={action.tone || 'surface'} disabled={busy || action.disabled}
      palette={palette} onPress={() => runSecondary(action)} />
    {action.needsSince ? <View style={styles.since}>
      <Text style={[styles.sinceLabel, { color: palette.textSecondary }]}>{labels.since || 'Since'}</Text>
      <View style={styles.sinceField}>
        <DateTimePicker value={since} onChange={setSince} trackTime={false}
          labels={{ ...(labels.dateTime || {}), field: labels.since || 'Since' }}
          palette={palette.dateTime || {}} />
      </View>
    </View> : null}
  </View>;
  const secondary = secondaryActions.filter(action => action.key !== 'save-as-new').map(renderSecondary);
  const saveAsNew = secondaryActions.filter(action => action.key === 'save-as-new').map(renderSecondary);
  const submitButton = <Button label={busy ? labels.saving : (model?.submitLabel || labels.save)} busy={busy}
    disabled={busy} onPress={submit} palette={palette} />;

  // Entry actions as grouped rows (Expo's pattern, now also the web's grouped contents): save as a new entry,
  // other repeat actions, delete; then the Cancel / primary footer the Collection modal uses.
  const entryRows = groupedRows ? [
    ...secondaryActions.map(action => <CollectionRow key={action.key} label={action.label}
      tone={action.key === 'save-as-new' ? 'accent' : undefined} palette={palette}
      onPress={busy || action.disabled ? undefined : () => runSecondary(action)} />),
    ...(model?.deleteAction && onDelete ? [<CollectionRow key="delete" label={labels.delete} tone="danger" palette={palette}
      onPress={busy ? undefined : () => onDelete(values)} />] : []),
  ] : [];
  const entryActions = entryRows.length ? <CollectionGroup palette={palette}>{entryRows}</CollectionGroup> : null;

  // The Collection modal's footer: Cancel and the primary action, at the end of the scrolling form (not pinned, so it takes no space).
  const groupedFooter = groupedRows ? <View style={styles.groupedFooter}>
    <View style={styles.footerButton}><Button label={labels.cancel || 'Cancel'} tone="ghost" size="lg" width="full"
      onPress={onClose} palette={{ ...palette, ghost: {
        background: 'transparent', pressed: palette.surfaceStrong, hovered: palette.surfaceStrong,
        text: palette.textSecondary, border: palette.border,
      } }} /></View>
    <View style={styles.footerButton}><Button label={busy ? labels.saving : (model?.submitLabel || labels.save)} size="lg"
      width="full" palette={palette} busy={busy} disabled={busy} onPress={submit} /></View>
  </View> : null;

  // The custom rating scale's criteria sheet; the score row above is only its button.
  const ratingField = (model?.fields || []).find(field => field.name === 'score' && field.ratingScale);
  const ratingSheet = ratingField ? <RatingCriteriaSheet open={ratingOpen} scale={ratingField.ratingScale}
    values={values} onChange={change} onClose={() => setRatingOpen(false)} onCancel={cancelRating} palette={palette}
    renderWheel={renderNumberWheel} labels={labels.rating} subtitle={ratingField.ratingScale.name} /> : null;

  const generalBody = <View style={sidebar ? styles.generalSide : styles.stack}>
    {ratingSheet}
    {generalPrefix}
    {groupedRows ? <View style={styles.generalSide}>
      {groupedMain.length ? <CollectionGroup title={labels.details || 'Details'} palette={palette}>{groupedMain}</CollectionGroup> : null}
      {groupedDates.length ? <CollectionGroup title={labels.dates || 'Dates'} palette={palette}>{groupedDates}</CollectionGroup> : null}
    </View>
      : sidebar ? <View style={styles.grid}>{cells}</View> : cells}
    {notes}
    {groupedRows ? entryActions : null}
    {groupedRows ? (sidebar ? groupedFooter : null) : sidebar ? <View style={styles.footer}>
      <View style={styles.footerStart}>{deleteButton}{secondary}</View>
      <View style={styles.footerStart}>{saveAsNew}{submitButton}</View>
    </View> : <View style={styles.actions}>
      {submitButton}{deleteButton}{secondary}
    </View>}
  </View>;

  if (sidebar) {
    return <View nativeID={nativeID} style={[styles.shell, {
      backgroundColor: palette.surfaceDim, maxHeight: Math.min(height * 0.92, height - 64) }]}>
      {showHeader ? <HeaderBar title={model?.title || labels.title} subtitle={model?.subtitle}
        closeLabel={labels.close} onClose={onClose} closeRef={closeRef} palette={palette} /> : null}
      {status === 'loading' ? <FormStatus message={labels.loading} tone="loading" palette={palette} /> : null}
      {status === 'error' ? <View style={styles.stack}>
        <FormError message={labels.loadFailed} palette={palette} />
        <Button label={labels.retry} tone="surface" onPress={onRetry} palette={palette} />
      </View> : null}
      {status === 'ready' && model ? <>
        {serverError ? <View style={styles.serverError}><FormError message={serverError} palette={palette} /></View> : null}
        <TrackTabs sidebar grouped={contentGrouped} tabs={tabs} activeId={selectedTab} onChange={selectTab}
          labels={labels} palette={palette} generalContent={generalBody}
          onRetry={onRetryTabs} onTagToggle={onTagToggle} onTagCreate={onTagCreate}
          onArtworkSave={onArtworkSave} onDiscoverToggle={onDiscoverToggle} />
      </> : null}
    </View>;
  }

  return <View nativeID={nativeID} style={[styles.card,
    embedded && styles.embedded, grouped && styles.groupedCard,
    { backgroundColor: embedded ? 'transparent' : palette.surface, maxHeight: embedded ? undefined : height * 0.88 }]}>
    {showHeader ? <FormHeader title={model?.title || labels.title} closeLabel={labels.close}
      onClose={onClose} closeRef={closeRef} palette={palette} /> : null}
    {status === 'loading' ? <FormStatus message={labels.loading} tone="loading" palette={palette} /> : null}
    {status === 'error' ? <View style={styles.stack}>
      <FormError message={labels.loadFailed} palette={palette} />
      <Button label={labels.retry} tone="surface" onPress={onRetry} palette={palette} />
    </View> : null}
    {status === 'ready' && model ? <ScrollView keyboardShouldPersistTaps="handled" style={grouped ? styles.scrollFill : styles.scroll}
      contentContainerStyle={styles.stack}>
      {model.subtitle ? <View style={styles.subtitleWrap}>
        <FormStatus message={model.subtitle} palette={palette} />
      </View> : null}
      {serverError ? <FormError message={serverError} palette={palette} /> : null}
      {grouped && tabs.length && !railTabs ? <View style={styles.sectionPicker}>
        <CollectionGroup palette={palette}>
          <CollectionSelectRow label={labels.section || 'Section'} icon={actionIcons.list} palette={palette}
            filter popover renderPicker={renderSelectPicker} value={selectedTab}
            options={trackTabItems(tabs, labels)} onChange={event => selectTab(event.target.value)} />
        </CollectionGroup>
      </View> : null}
      {tabs.length ? <TrackTabs tabs={tabs} activeId={selectedTab} onChange={selectTab}
        grouped={groupedRows} hideNav={grouped} renderSelectPicker={renderSelectPicker}
        labels={labels} palette={palette} generalContent={generalBody}
        onRetry={onRetryTabs} onTagToggle={onTagToggle} onTagCreate={onTagCreate}
        onArtworkSave={onArtworkSave} onDiscoverToggle={onDiscoverToggle} /> : generalBody}
      {groupedFooter}
    </ScrollView> : null}
  </View>;
}

const styles = StyleSheet.create({
  shell: { width: '100%', borderRadius: 12, overflow: 'hidden', flexShrink: 1 },
  bar: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 12,
    paddingHorizontal: 28, paddingVertical: 16, borderBottomWidth: 1 },
  barText: { flexShrink: 1, minWidth: 0 },
    barSubtitle: { fontSize: 14, marginTop: 2 },
  barClose: { padding: 4, borderRadius: 6 },
  serverError: { paddingHorizontal: 24, paddingTop: 12 },
  generalSide: { gap: 20 },
  grid: { flexDirection: 'row', flexWrap: 'wrap', columnGap: 16, rowGap: 20 },
  cell: { flexBasis: '48.5%', maxWidth: '48.5%', flexGrow: 1, minWidth: 0 },
  fullCell: { width: '100%' },
  footer: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 16, marginTop: 4 },
  numberInput: { minHeight: 46, borderWidth: 1, borderRadius: 6, paddingLeft: 10, paddingRight: 44, fontSize: 14 },
  stepper: { position: 'absolute', top: 0, right: 0, bottom: 0, width: 34 },
  stepButton: { flex: 1, alignItems: 'center', justifyContent: 'center', borderWidth: 1 },
  secondary: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  since: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  sinceLabel: { fontSize: 12 },
  sinceField: { width: 150 },
  footerStart: { flexDirection: 'row', alignItems: 'center', flexWrap: 'wrap', gap: 8 },
  card: {
    width: '100%', borderRadius: 8, padding: 24, gap: 16,
    shadowColor: '#000000', shadowOpacity: 0.35, shadowRadius: 24, shadowOffset: { width: 0, height: 12 }, elevation: 16,
  },
  embedded: {
    borderRadius: 0, padding: 0, shadowOpacity: 0, shadowRadius: 0, shadowOffset: { width: 0, height: 0 }, elevation: 0,
  },
  scroll: { flexGrow: 0 },
  scrollFill: { flex: 1 },
  groupedCard: { flex: 1 },
  groupedFooter: { flexDirection: 'row', gap: 8, paddingTop: 12, paddingBottom: 8 },
  footerButton: { flex: 1 },
  stack: { gap: 14 },
  subtitleWrap: { marginTop: -4 },
  ratingStar: { fontSize: 18 },
  sectionPicker: { marginBottom: 4 },
  durationInput: { flex: 1, minWidth: 0, textAlign: 'right', fontSize: 16, padding: 0 },
  rowError: { fontSize: 13, lineHeight: 18, paddingHorizontal: 16, paddingBottom: 10 },
  actions: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', gap: 10, marginTop: 4 },
});
