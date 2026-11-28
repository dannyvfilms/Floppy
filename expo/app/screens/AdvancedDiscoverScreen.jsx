import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Linking, StyleSheet, Text, View } from 'react-native';
import { AdvancedDiscoverView } from '../../../frontend/pages/AdvancedDiscoverView';
import { Screen } from '../components/Screen';
import { createPeopleTransport } from '../data/peopleTransport';
import { enrichServerCard, routeCardHref } from '../data/serverCardCore';
import MediaCardSlot from '../surfaces/MediaCardSlot';
import { palette, spacing } from '../theme';

export const surface = {
  id: 'ADVANCED-DISCOVER',
  status: 'in_progress',
  title: 'Advanced discover',
  where: 'TMDB movie and TV discovery',
  note: 'Uses the shared discovery view and authenticated server API; native runtime verification is pending.',
};

function queryFor(filters) {
  const query = new URLSearchParams({
    type: filters.type,
    search: '1',
    person_role: filters.personRole,
    person_logic: filters.personLogic,
    sort: filters.sort,
    page: String(filters.page || 1),
  });
  if (filters.certificationCountry) query.set('certification_country', filters.certificationCountry);
  filters.certifications.forEach(certification => query.append('certification', certification));
  query.set('adult_mode', filters.adultMode);
  if (filters.includeVideo) query.set('include_video', 'true');
  if (filters.includeNullFirstAirDates) query.set('include_null_first_air_dates', 'true');
  filters.people.forEach(person => {
    query.append('person', String(person.person_id));
    query.set(`person_name_${person.person_id}`, person.name);
  });
  query.set('format', 'json');
  return query.toString();
}

export default function AdvancedDiscoverScreen({ navigate, params, transport: injectedTransport }) {
  const transport = useMemo(() => injectedTransport || createPeopleTransport(), [injectedTransport]);
  const [props, setProps] = useState(null);
  const [error, setError] = useState('');

  const load = useCallback(async queryString => {
    try {
      const next = await transport.loadAdvancedDiscover(queryString);
      setProps(next);
      setError('');
    } catch (cause) {
      setError(cause?.message || 'TMDB discovery is currently unavailable.');
    }
  }, [transport]);

  useEffect(() => {
    const initial = new URLSearchParams(params?.queryString || '');
    initial.set('format', 'json');
    load(initial.toString());
  }, [load, params?.queryString]);

  async function search(filters) {
    await load(queryFor(filters));
  }

  return <Screen chrome={false} contentStyle={styles.screen}>
    <View style={styles.content}>
      {props ? <AdvancedDiscoverView
        props={{ ...props, error: props.error || error }}
        palette={{
          text: palette.text,
          secondary: palette.textSecondary,
          muted: palette.textMuted,
          surface: palette.surface,
          surfaceStrong: palette.surfaceStrong,
          border: palette.border,
          accent: palette.accent,
          link: palette.link,
        }}
        onSearch={search}
        onSearchPeople={async query => {
          return transport.searchPeople(query);
        }}
        renderResults={entries => <MediaCardSlot
          items={entries.map(entry => ({
            key: entry.id,
            model: enrichServerCard({ ...entry.card, titleColor: '#fff', subtitleColor: '#e5e7eb' }),
            row: entry,
          }))}
          onOpenDetail={entry => navigate?.('Detail', { href: entry.href })}
          onOpenLink={href => routeCardHref(href, navigate)} />}
        onOpenTitle={href => navigate?.('Detail', { href })}
        onOpenSource={url => Linking.openURL(url).catch(() => {})} />
        : <Text accessibilityLiveRegion="polite" style={{ color: palette.textMuted }}>{error || 'Loading advanced discovery…'}</Text>}
    </View>
  </Screen>;
}

const styles = StyleSheet.create({
  screen: { paddingTop: spacing.lg },
  content: { width: '100%' },
});
