import React, { useEffect, useState } from 'react';
import { ActivityIndicator, Pressable, StyleSheet, Text, TextInput, View } from 'react-native';
import { Button } from '../ui/Button';
import { MediaCard } from '../ui/MediaCard';
import { SelectField } from '../ui/SelectField';

const defaults = {
  heading: 'Advanced discover',
  description: 'Find TMDB movies or TV using people and certifications.',
  search: 'Search',
  peopleLabel: 'People',
  peoplePlaceholder: 'Search for a person…',
  personRole: 'Match people as',
  peopleAny: 'Cast, crew, or either',
  cast: 'Cast',
  crew: 'Crew',
  logic: 'Match',
  and: 'All people',
  or: 'Any person',
  country: 'Certification country',
  certification: 'Certification',
  certificationOr: 'Any selected certification',
  sortBy: 'Sort by',
  sortReleaseDate: 'Release date',
  sortTitle: 'Title',
  sortPopularity: 'Popularity',
  sortVotes: 'Votes',
  adultFilter: 'Adult titles',
  adultExclude: 'Exclude adult titles',
  adultInclude: 'Include adult titles',
  adultOnly: 'Adult titles only',
  emptyAdultPage: 'No adult-flagged titles on this TMDB page.',
  page: 'Page',

  includeVideo: 'Include video titles',
  includeNullDates: 'Include shows without a first-air date',
  movie: 'Movies',
  tv: 'TV shows',
  mediaType: 'Media type',
  previous: 'Previous',
  next: 'Next',
  remove: 'Remove',
  empty: 'No matching titles found.',
  attribution: 'Movie and TV data provided by TMDB.',
};

export function AdvancedDiscoverView({
  props = {}, palette = {}, onSearch, onSearchPeople, onOpenTitle, onOpenSource,
  renderResults,
}) {
  const copy = { ...defaults, ...(props.labels || {}) };
  const colors = {
    text: '#fafafa', surface: '#27272a',
    surfaceStrong: '#3f3f46', border: '#3f3f46', accent: '#6366f1', link: '#818cf8',
    ...palette,
    card: palette.card || palette.surface || '#27272a',
    secondary: palette.secondary || palette.textSecondary || '#d4d4d8',
    muted: palette.muted || palette.textMuted || '#a1a1aa',
  };
  const [mediaType, setMediaType] = useState(props.mediaType || 'movie');
  const [people, setPeople] = useState(props.people || []);
  const [role, setRole] = useState(props.personRole || 'people');
  const [logic, setLogic] = useState(props.personLogic || 'and');
  const [country, setCountry] = useState(props.certificationCountry || '');
  const [certificationChoice, setCertificationChoice] = useState('');
  const [selectedCertifications, setSelectedCertifications] = useState(props.selectedCertifications || []);
  const [sort, setSort] = useState(props.sort || 'release_date');
  const [adultMode, setAdultMode] = useState(props.adultMode || (props.includeAdult ? 'include' : 'exclude'));
  const [includeVideo, setIncludeVideo] = useState(Boolean(props.includeVideo));
  const [includeNullDates, setIncludeNullDates] = useState(Boolean(props.includeNullFirstAirDates));
  const [query, setQuery] = useState('');
  const [suggestions, setSuggestions] = useState([]);
  const [loadingPeople, setLoadingPeople] = useState(false);

  useEffect(() => {
    let active = true;
    const normalized = query.trim();
    if (normalized.length < 2) {
      setSuggestions([]);
      return undefined;
    }
    const timer = setTimeout(async () => {
      setLoadingPeople(true);
      try {
        const matches = await onSearchPeople?.(normalized);
        if (active) setSuggestions(Array.isArray(matches) ? matches : []);
      } catch {
        if (active) setSuggestions([]);
      } finally {
        if (active) setLoadingPeople(false);
      }
    }, 250);
    return () => { active = false; clearTimeout(timer); };
  }, [query, onSearchPeople]);

  const countryOptions = [{ value: '', label: '—' }, ...(props.countriesByType?.[mediaType] || props.countries || [])];
  const certificateData = props.certificationsByCountry?.[mediaType]?.[country] || props.certifications || [];
  const certificateOptions = [{ value: '', label: '—' }, ...certificateData.map(item => ({
    value: item.certification,
    label: item.meaning ? `${item.certification} — ${item.meaning}` : item.certification,
  }))];
  useEffect(() => {
    if (country && !countryOptions.some(option => option.value === country)) {
      setCountry('');
      setSelectedCertifications([]);
      setCertificationChoice('');
    } else {
      const allowed = new Set(certificateData.map(item => item.certification));
      setSelectedCertifications(current => current.filter(value => allowed.has(value)));
    }
  }, [mediaType, props.countriesByType, props.certificationsByCountry, country]);
  const roleOptions = [
    { value: 'people', label: copy.peopleAny },
    { value: 'cast', label: copy.cast },
    { value: 'crew', label: copy.crew },
  ];
  const logicOptions = [
    { value: 'and', label: copy.and },
    { value: 'or', label: copy.or },
  ];
  const sortOptions = [
    { value: 'release_date', label: copy.sortReleaseDate },
    { value: 'title', label: copy.sortTitle },
    { value: 'popularity', label: copy.sortPopularity },
    { value: 'votes', label: copy.sortVotes },
  ];
  const adultOptions = [
    { value: 'exclude', label: copy.adultExclude },
    ...(props.adultAllowed ? [
      { value: 'include', label: copy.adultInclude },
      { value: 'only', label: copy.adultOnly },
    ] : []),
  ];

  function addPerson(person) {
    const id = String(person?.person_id || '');
    if (!id || people.some(entry => String(entry.person_id) === id)) return;
    setPeople(current => [...current, { person_id: id, name: person.name }]);
    setQuery('');
    setSuggestions([]);
  }

  function submit(page = 1) {
    onSearch?.({
      type: mediaType,
      people,
      personRole: role,
      personLogic: logic,
      certificationCountry: country,
      certifications: selectedCertifications,
      sort,
      adultMode,
      includeVideo,
      includeNullFirstAirDates: includeNullDates,
      page,
    });
  }

  function toggle(label, value, setter, disabled = false) {
    return <Pressable key={label} accessibilityRole="checkbox" accessibilityState={{ checked: value, disabled }}
      disabled={disabled} onPress={() => setter(!value)} style={[styles.toggle, disabled && { opacity: 0.5 }]}>
      <View style={[styles.check, { borderColor: colors.border, backgroundColor: value ? colors.accent : colors.surface }]}>
        {value ? <Text style={styles.checkMark}>✓</Text> : null}
      </View>
      <Text style={[styles.toggleLabel, { color: colors.secondary }]}>{label}</Text>
    </Pressable>;
  }

  return <View style={styles.root} testID="advanced-discover">
    <Text accessibilityRole="header" aria-level={1} style={[styles.heading, { color: colors.text }]}>{copy.heading}</Text>
    <Text style={[styles.description, { color: colors.muted }]}>{copy.description}</Text>
    <View style={styles.typeSwitch} accessibilityRole="group" accessibilityLabel={copy.mediaType}>
      {[['movie', copy.movie], ['tv', copy.tv]].map(([value, label]) => <Pressable key={value}
        accessibilityRole="button" accessibilityState={{ selected: mediaType === value }}
        onPress={() => setMediaType(value)} style={[styles.typeButton, {
          borderColor: colors.border, backgroundColor: mediaType === value ? colors.accent : colors.surface,
        }]}><Text style={{ color: mediaType === value ? (colors.accentContrast || '#fff') : colors.text, fontWeight: '600' }}>{label}</Text></Pressable>)}
    </View>
    <View style={styles.filterGrid}>
      <SelectField label={copy.country} options={countryOptions} value={country} palette={colors}
        filter
        onChange={({ target }) => {
          setCountry(target.value);
          setSelectedCertifications([]);
          setCertificationChoice('');
        }} />
      <SelectField label={copy.certification} options={certificateOptions} value={certificationChoice}
        disabled={!country || certificateOptions.length < 2} palette={colors}
        onChange={({ target }) => {
          const value = target.value;
          if (value) setSelectedCertifications(current => current.includes(value) ? current : [...current, value]);
          setCertificationChoice('');
        }} />
      {selectedCertifications.length ? <View style={styles.certificationSection}>
        <Text style={{ color: colors.muted, fontSize: 12 }}>{copy.certificationOr}</Text>
        <View style={styles.chips}>
          {selectedCertifications.map(value => <View key={value} style={[styles.personChip, {
            backgroundColor: colors.surfaceStrong, borderColor: colors.border,
          }]}>
            <Text style={{ color: colors.text }}>{value}</Text>
            <Pressable accessibilityRole="button" accessibilityLabel={`${copy.remove} ${value}`}
              onPress={() => setSelectedCertifications(current => current.filter(entry => entry !== value))}>
              <Text style={{ color: colors.link, fontWeight: '700' }}>×</Text>
            </Pressable>
          </View>)}
        </View>
      </View> : null}
      <SelectField label={copy.personRole} options={roleOptions} value={role} palette={colors}
        onChange={({ target }) => setRole(target.value)} />
      <SelectField label={copy.logic} options={logicOptions} value={logic} disabled={!people.length}
        palette={colors} onChange={({ target }) => setLogic(target.value)} />
      <SelectField label={copy.sortBy} options={sortOptions} value={sort} palette={colors}
        onChange={({ target }) => setSort(target.value)} />
    </View>
    <View style={styles.peopleSection}>
      <Text style={[styles.label, { color: colors.secondary }]}>{copy.peopleLabel}</Text>
      <TextInput accessibilityLabel={copy.peopleLabel} value={query} onChangeText={setQuery}
        placeholder={copy.peoplePlaceholder} placeholderTextColor={colors.muted}
        style={[styles.input, { backgroundColor: colors.surface, borderColor: colors.border, color: colors.text }]} />
      {loadingPeople ? <ActivityIndicator accessibilityLabel="Searching people" color={colors.accent} /> : null}
      {suggestions.length ? <View style={[styles.suggestions, { backgroundColor: colors.surface, borderColor: colors.border }]}>
        {suggestions.map(person => <Pressable key={person.person_id} accessibilityRole="button"
          accessibilityLabel={`Add ${person.name}`} onPress={() => addPerson(person)} style={styles.suggestion}>
          <Text style={{ color: colors.text }}>{person.name}</Text>
          {person.known_for_department ? <Text style={{ color: colors.muted, fontSize: 12 }}>{person.known_for_department}</Text> : null}
        </Pressable>)}
      </View> : null}
      {people.length ? <View style={styles.chips}>
        {people.map(person => <View key={person.person_id} style={[styles.personChip, { backgroundColor: colors.surfaceStrong, borderColor: colors.border }]}>
          <Text style={{ color: colors.text }}>{person.name}</Text>
          <Pressable accessibilityRole="button" accessibilityLabel={`${copy.remove} ${person.name}`}
            onPress={() => setPeople(current => current.filter(entry => entry.person_id !== person.person_id))}>
            <Text style={{ color: colors.link, fontWeight: '700' }}>×</Text>
          </Pressable>
        </View>)}
      </View> : null}
    </View>
    <View style={styles.toggles}>
      <SelectField label={copy.adultFilter} options={adultOptions} value={adultMode} palette={colors}
        onChange={({ target }) => setAdultMode(target.value)} />
      {mediaType === 'movie' ? toggle(copy.includeVideo, includeVideo, setIncludeVideo) : null}
      {mediaType === 'tv' ? toggle(copy.includeNullDates, includeNullDates, setIncludeNullDates) : null}
    </View>
    <Button label={copy.search} tone="primary" onPress={() => submit()} />
    {props.error ? <Text accessibilityLiveRegion="polite" style={{ color: colors.muted }}>{props.error}</Text> : null}
    {props.searched && !props.error && !props.results?.length ? <Text accessibilityLiveRegion="polite" style={{ color: colors.muted }}>
      {adultMode === 'only' ? copy.emptyAdultPage : copy.empty}
    </Text> : null}
    {props.results?.length ? (renderResults
      ? renderResults(props.results)
      : <View style={styles.results} accessibilityRole="list">
        {props.results.map(entry => <View key={entry.id} style={styles.result}>
          <MediaCard model={{ ...entry.card, titleColor: '#fff', subtitleColor: '#e5e7eb' }}
            palette={{ ...colors, text: '#fff', textSecondary: '#fff', textMuted: '#e5e7eb' }}
            onOpen={() => onOpenTitle?.(entry.href)} />
        </View>)}
      </View>) : null}
    {(adultMode === 'only' ? props.page > 1 || props.hasNextPage : props.totalPages > 1) ? <View style={styles.pagination}>
      <Button label={copy.previous} onPress={() => submit(Math.max(1, props.page - 1))} disabled={props.page <= 1} />
      <Text style={{ color: colors.muted }}>{adultMode === 'only' ? `${copy.page} ${props.page}` : `${props.page} / ${props.totalPages}`}</Text>
      <Button label={copy.next} onPress={() => submit(adultMode === 'only' ? props.page + 1 : Math.min(props.totalPages, props.page + 1))}
        disabled={adultMode === 'only' ? !props.hasNextPage : props.page >= props.totalPages} />
    </View> : null}
    <Pressable accessibilityRole="link" onPress={() => onOpenSource?.('https://www.themoviedb.org/')}>
      <Text style={[styles.attribution, { color: colors.muted }]}>{copy.attribution}</Text>
    </Pressable>
  </View>;
}

const styles = StyleSheet.create({
  root: { gap: 12, width: '100%', maxWidth: 1100, alignSelf: 'center' },
  heading: { fontSize: 24, lineHeight: 30, fontWeight: '700' },
  description: { fontSize: 14, lineHeight: 21 },
  typeSwitch: { flexDirection: 'row', gap: 8, marginTop: 8 },
  typeButton: { minHeight: 42, borderWidth: 1, borderRadius: 8, paddingHorizontal: 14, justifyContent: 'center' },
  filterGrid: { gap: 10 },
  peopleSection: { gap: 8, position: 'relative', zIndex: 2 },
  certificationSection: { gap: 6 },
  label: { fontSize: 14, fontWeight: '600' },
  input: { minHeight: 44, borderWidth: 1, borderRadius: 8, paddingHorizontal: 12, fontSize: 16 },
  suggestions: { borderWidth: 1, borderRadius: 8, overflow: 'hidden' },
  suggestion: { minHeight: 44, paddingHorizontal: 12, paddingVertical: 8, justifyContent: 'center', borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: '#52525b' },
  chips: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  personChip: { flexDirection: 'row', alignItems: 'center', gap: 8, borderWidth: 1, borderRadius: 20, paddingHorizontal: 10, paddingVertical: 6 },
  toggles: { gap: 8 },
  toggle: { flexDirection: 'row', alignItems: 'center', gap: 10, minHeight: 40 },
  toggleLabel: { fontSize: 14 },
  check: { width: 20, height: 20, borderWidth: 1, borderRadius: 4, justifyContent: 'center', alignItems: 'center' },
  checkMark: { color: '#fff', fontSize: 14, fontWeight: '700' },
  results: { flexDirection: 'row', flexWrap: 'wrap', gap: 12, justifyContent: 'flex-start', marginTop: 8 },
  pagination: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', justifyContent: 'center', gap: 12 },
  result: { width: 168 },

  attribution: { fontSize: 12, lineHeight: 18, textDecorationLine: 'underline' },
});
