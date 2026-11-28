import React from 'react';
import { Linking } from 'react-native';
import { PeopleSearchView } from '../../../frontend/pages/PeopleSearchView';
import { Screen } from '../components/Screen';
import { createPeopleTransport } from '../data/peopleTransport';
import { getActiveAuthSession } from '../data/authSession';
import { palette } from '../theme';

export default function PeopleSearchScreen({ navigate }) {
  const session = getActiveAuthSession();
  const transport = createPeopleTransport(session ? { auth: session } : {});
  return <Screen chrome={false} contentStyle={{ paddingTop: 24 }}>
    <PeopleSearchView
      palette={{
        text: palette.text,
        secondary: palette.textSecondary,
        muted: palette.textMuted,
        surface: palette.surface,
        border: palette.border,
        accent: palette.accent,
      }}
      onSearch={query => transport.searchPeople(query)}
      onOpenPerson={person => navigate('People', {
        identity: {
          kind: 'person',
          source: 'tmdb',
          personId: String(person.person_id),
        },
      })}
      onOpenSource={url => Linking.openURL(url).catch(() => {})} />
  </Screen>;
}
