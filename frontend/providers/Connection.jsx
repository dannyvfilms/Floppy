import React from 'react';
import { Credentials } from './Credentials';
import { usePage } from './web';

export function Connection({ draft }) {
  const { model } = usePage();
  return <Credentials credentials={{ ...model.credentials, csrf: model.csrf, next: model.next }} draft={draft} />;
}
