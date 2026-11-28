import React, { useState } from 'react';
import { ActivityIndicator, Image, Pressable, StyleSheet, Text, TextInput, View } from 'react-native';
import { Button } from '../ui/Button';

const DEFAULT_LABELS = {
  heading: 'Discover people',
  description: 'Search TMDB for a person, then browse their Floppy filmography.',
  label: 'Person name',
  placeholder: 'Search people…',
  search: 'Search',
  shortQuery: 'Enter at least two characters.',
  loading: 'Searching…',
  empty: 'No people found. Try another name.',
  error: 'People search is unavailable right now.',
  department: 'Known for',
  choose: 'Open profile',
  attribution: 'People and images provided by TMDB.',
};

const DEFAULT_PALETTE = {
  text: '#fafafa',
  secondary: '#d1d5db',
  muted: '#a1a1aa',
  surface: '#27272a',
  border: '#3f3f46',
  accent: '#6366f1',
};

export function PeopleSearchView({
  query: initialQuery = '',
  people: initialPeople = [],
  state: initialState = 'ready',
  labels = {},
  palette = {},
  onSearch,
  onOpenPerson,
  attributionUrl = 'https://www.themoviedb.org/',
  onOpenSource,
}) {
  const [query, setQuery] = useState(initialQuery);
  const [people, setPeople] = useState(initialPeople);
  const [state, setState] = useState(initialState);
  const [notice, setNotice] = useState('');
  const copy = { ...DEFAULT_LABELS, ...labels };
  const colors = { ...DEFAULT_PALETTE, ...palette };

  async function submit() {
    const normalized = query.trim();
    if (normalized.length < 2) {
      setNotice(copy.shortQuery);
      return;
    }
    setNotice('');
    setState('loading');
    try {
      setPeople(await onSearch(normalized));
      setState('ready');
    } catch {
      setState('error');
      setNotice(copy.error);
    }
  }

  return <View style={styles.root} testID="people-search">
    <Text accessibilityRole="header" aria-level={1} style={[styles.heading, { color: colors.text }]}>
      {copy.heading}
    </Text>
    <Text style={[styles.description, { color: colors.muted }]}>{copy.description}</Text>
    <View style={styles.form}>
      <Text accessibilityRole="label" style={[styles.label, { color: colors.secondary }]}>{copy.label}</Text>
      <TextInput
        accessibilityLabel={copy.label}
        value={query}
        onChangeText={value => { setQuery(value); setNotice(''); }}
        onSubmitEditing={submit}
        returnKeyType="search"
        placeholder={copy.placeholder}
        placeholderTextColor={colors.muted}
        style={[styles.input, { color: colors.text, backgroundColor: colors.surface, borderColor: colors.border }]}
      />
      <Button
        label={copy.search}
        tone="primary"
        onPress={submit}
        disabled={query.trim().length < 2 || state === 'loading'}
      />
    </View>
    {notice ? <Text accessibilityLiveRegion="polite" style={[styles.message, { color: colors.muted }]}>{notice}</Text> : null}
    {state === 'loading' ? <View accessibilityLiveRegion="polite" style={styles.messageRow}>
      <ActivityIndicator color={colors.accent} />
      <Text style={[styles.message, { color: colors.muted }]}>{copy.loading}</Text>
    </View> : null}
    {state === 'error' && !notice ? <Text accessibilityLiveRegion="polite" style={[styles.message, { color: colors.muted }]}>{copy.error}</Text> : null}
    {state === 'ready' && query.trim().length >= 2 && people.length === 0
      ? <Text accessibilityLiveRegion="polite" style={[styles.message, { color: colors.muted }]}>{copy.empty}</Text> : null}
    {state === 'ready' && people.length > 0 ? <View accessibilityRole="list" style={styles.results}>
      {people.map(person => <Pressable
        key={String(person.person_id)}
        accessibilityRole="link"
        accessibilityLabel={`${copy.choose}: ${person.name}`}
        onPress={() => onOpenPerson?.(person)}
        style={({ pressed }) => [styles.person, { borderColor: colors.border, backgroundColor: colors.surface }, pressed && { opacity: 0.8 }]}
      >
        {person.image ? <Image source={{ uri: person.image }} accessibilityLabel="" style={styles.image} /> : <View style={[styles.image, styles.imageFallback, { backgroundColor: colors.border }]} />}
        <View style={styles.personCopy}>
          <Text style={[styles.name, { color: colors.text }]} numberOfLines={2}>{person.name}</Text>
          {person.known_for_department ? <Text style={[styles.meta, { color: colors.muted }]}>{copy.department}: {person.known_for_department}</Text> : null}
          {person.known_for?.length ? <Text style={[styles.meta, { color: colors.muted }]} numberOfLines={2}>{person.known_for.join(', ')}</Text> : null}
        </View>
        <Text style={[styles.choose, { color: colors.accent }]}>{copy.choose}</Text>
      </Pressable>)}
    </View> : null}
    <Pressable accessibilityRole="link" onPress={() => onOpenSource?.(attributionUrl)}>
      <Text style={[styles.attribution, { color: colors.muted }]}>{copy.attribution}</Text>
    </Pressable>
  </View>;
}

const styles = StyleSheet.create({
  root: { gap: 12, width: '100%', maxWidth: 900, alignSelf: 'center' },
  heading: { fontSize: 24, lineHeight: 30, fontWeight: '700' },
  description: { fontSize: 14, lineHeight: 21 },
  form: { gap: 8, marginTop: 8 },
  label: { fontSize: 14, fontWeight: '600' },
  input: { minHeight: 44, borderWidth: 1, borderRadius: 8, paddingHorizontal: 12, fontSize: 16 },
  messageRow: { flexDirection: 'row', alignItems: 'center', gap: 8, paddingVertical: 16 },
  message: { fontSize: 14, lineHeight: 20, paddingVertical: 12 },
  results: { gap: 8, marginTop: 8 },
  person: { minHeight: 88, borderWidth: 1, borderRadius: 8, padding: 10, flexDirection: 'row', alignItems: 'center', gap: 12 },
  image: { width: 56, height: 68, borderRadius: 6, resizeMode: 'cover' },
  imageFallback: { opacity: 0.55 },
  personCopy: { flex: 1, minWidth: 0, gap: 4 },
  name: { fontSize: 16, lineHeight: 21, fontWeight: '600' },
  meta: { fontSize: 13, lineHeight: 18 },
  choose: { fontSize: 13, fontWeight: '600' },
  attribution: { fontSize: 12, lineHeight: 18, textDecorationLine: 'underline' },
});
