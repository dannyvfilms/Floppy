import React, { useEffect, useState } from 'react';
import { Image, Pressable, StyleSheet, Text, TextInput, View } from 'react-native';
import { Button } from '../ui/Button';
import { DateTimePicker } from '../ui/DateTimePicker';
import { Icon } from '../ui/Icon';
import { ParentPicker } from '../ui/ParentPicker';
import { SelectField } from '../ui/SelectField';
import { TextField } from '../ui/TextField';
import { actionIcons } from '../ui/actionIcons';

// The adapter supplies choices, form values, parent search and save behavior.
export function ManualEntryView({ palette, options, draft, onChange, parent, onSelectParent, onParentQuery, onRetryParent, onSubmit, saving, message, error }) {
  const [imageFailed, setImageFailed] = useState(false);
  useEffect(() => setImageFailed(false), [draft.image]);
  const type = draft.media_type;
  const child = type === 'season' || type === 'episode';
  const episode = type === 'episode';
  const dated = !['tv', 'season'].includes(type);
  const progress = !['tv', 'season', 'episode', 'podcast'].includes(type);
  const fieldPalette = { ...palette, inputBackground: palette.surfaceStrong };
  const field = (name, label, placeholder, fieldType) => <TextField key={name} label={label} value={draft[name] || ''}
    placeholder={placeholder} type={fieldType} onChangeText={value => onChange(name, value)} palette={fieldPalette}
    labelStyle={[styles.label, { color: palette.textSecondary }]} inputStyle={styles.fieldInput} />;
  const textarea = (name, label, placeholder) => <View style={styles.textareaField}>
    <Text style={[styles.label, { color: palette.textSecondary }]}>{label}</Text>
    <TextInput accessibilityLabel={label} multiline value={draft[name] || ''}
      onChangeText={value => onChange(name, value)} placeholder={placeholder} placeholderTextColor={palette.textMuted}
      style={[styles.textarea, { color: palette.text, backgroundColor: palette.surfaceStrong, borderColor: palette.border }]} />
  </View>;
  const dateField = (name, label) => <View style={styles.textareaField}>
    <Text style={[styles.label, { color: palette.textSecondary }]}>{label}</Text>
    <DateTimePicker value={draft[name] || ''} onChange={value => onChange(name, value)}
      trackTime={false} labels={{ field: label }} palette={palette} />
  </View>;
  return <View style={styles.page}>
    <Text role="heading" aria-level={1} style={[styles.title, { color: palette.text }]}>Create Custom Entry</Text>
    <Text style={{ color: palette.textMuted }}>Add a custom media entry to your collection if it's not available in the database.</Text>
    <View style={[styles.form, { backgroundColor: palette.surface }]}>
      <Text style={[styles.label, { color: palette.textSecondary }]}>Media Type</Text>
      <View style={styles.types}>{options.media_types.map(option => <Pressable key={option.value}
        accessibilityRole="button" accessibilityState={{ selected: type === option.value }}
        onPress={() => onChange('media_type', option.value)}
        style={[styles.type, { borderColor: type === option.value ? palette.accentStrong : palette.surfaceBorder, backgroundColor: type === option.value ? palette.accentStrong : palette.surface }]}>
        <Icon spec={option.icon} color={type === option.value ? palette.onAccentStrong : palette.textSecondary} size={20} />
        <Text style={{ color: type === option.value ? palette.onAccentStrong : palette.textSecondary, fontSize: 14 }}>{option.label}</Text>
      </Pressable>)}</View>
      {child ? <ParentPicker title={episode ? 'Parent Season' : 'Parent TV Show'}
        plain
        placeholder={episode ? 'Search for a season...' : 'Search for a TV show...'}
        query={parent.query} selectedId={parent.selectedId} results={parent.results} state={parent.state}
        palette={palette} onQueryChange={onParentQuery} onSelect={onSelectParent} onRetry={onRetryParent} /> : field('title', 'Title', 'Enter title')}
      {child ? field(episode ? 'episode_number' : 'season_number', episode ? 'Episode Number' : 'Season Number', '', 'number') : null}
      <View style={styles.imageRow}><View style={styles.imageField}>{field('image', 'Image URL', 'Enter image URL', 'url')}</View>
        <View style={[styles.preview, { backgroundColor: palette.surfaceStrong, borderColor: palette.fieldBorder }]}>
          {draft.image && !imageFailed ? <Image source={{ uri: draft.image }} accessibilityLabel="Preview"
            style={StyleSheet.absoluteFill} resizeMode="cover" onError={() => setImageFailed(true)} />
            : <Icon spec={actionIcons.image} color={palette.textMuted} size={32} />}
        </View>
      </View>
      {type === 'podcast' ? field('rss_feed_url', 'RSS Feed URL', '', 'url') : null}
      {!episode && options.ratings_enabled ? field('score', 'Score', `0-${options.rating_scale_max}`, 'decimal') : null}
      {progress ? field('progress', type === 'anime' ? 'Progress (Episodes)' : type === 'manga' ? 'Progress (Chapters)' : type === 'game' ? 'Progress (Play Time)' : type === 'book' ? 'Progress (Pages)' : 'Progress', '') : null}
      {!episode ? <SelectField label="Status" value={draft.status} options={options.statuses}
        palette={{ ...palette, surface: palette.surfaceStrong }} iconChevron
        labelStyle={[styles.label, { color: palette.textSecondary }]} triggerStyle={styles.fieldInput} triggerTextStyle={{ fontSize: 16 }}
        onChange={event => onChange('status', event.target.value)} /> : null}
      {dated && !episode ? dateField('start_date', 'Start Date') : null}
      {dated ? dateField('end_date', 'End Date') : null}
      {!episode ? textarea('notes', 'Notes', 'Add any notes or comments...') : null}
      {!episode ? textarea('synopsis', 'Description', 'Add a description...') : null}
      {error ? <Text accessibilityLiveRegion="polite" style={{ color: palette.danger }}>{error}</Text> : null}
      {message ? <Text accessibilityLiveRegion="polite" style={{ color: palette.text }}>{message}</Text> : null}
      <View style={styles.submit}><Button label={saving ? 'Creating...' : 'Create Entry'} tone="primary" size="md" disabled={saving} onPress={onSubmit} /></View>
    </View>
  </View>;
}

const styles = StyleSheet.create({
  page: { gap: 12 }, title: { fontSize: 30, fontWeight: '700' },
  form: { padding: 24, borderRadius: 8, gap: 24 }, label: { fontSize: 14, lineHeight: 20, fontWeight: '500' },
  types: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  type: { flexBasis: '47%', flexGrow: 1, flexDirection: 'row', alignItems: 'center', gap: 8, borderWidth: 1, borderRadius: 10, padding: 12, minHeight: 46 },
  fieldInput: { minHeight: 42, fontSize: 16, paddingVertical: 8 },
  imageRow: { flexDirection: 'row', gap: 16, alignItems: 'flex-end' }, imageField: { flex: 1, minWidth: 0 },
  preview: { width: 80, height: 80, borderWidth: 1, borderRadius: 6, overflow: 'hidden', alignItems: 'center', justifyContent: 'center' },
  textareaField: { gap: 8 }, textarea: { minHeight: 100, borderWidth: 1, borderRadius: 6, padding: 8, textAlignVertical: 'top' },
  submit: { alignSelf: 'flex-start' },
});
