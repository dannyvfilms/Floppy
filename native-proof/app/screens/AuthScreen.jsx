import React from 'react';
import { Screen } from '../components/Screen';
import { Note } from '../components/Note';

const surface = {
  id: 'AUTH',
  title: 'Account and authentication',
  where: 'Login, signup, social, password, TOTP and recovery',
  note: 'Authentication, account security, social connections and deletion guards will replace this note.',
};

export default function AuthScreen({ onBack }) {
  return <Screen title="Account" subtitle="Account and authentication" onBack={onBack}>
    <Note surface={surface} />
  </Screen>;
}
