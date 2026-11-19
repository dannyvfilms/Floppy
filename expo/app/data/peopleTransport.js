import { getActiveAuthSession } from './authSession.js';
import { createLocalPeopleActions, createRemotePeopleActions } from './peopleTransportCore.js';

export function createPeopleTransport(options = {}) {
  if (typeof options.request === 'function') {
    return createRemotePeopleActions(options.request);
  }
  const auth = options.auth || getActiveAuthSession();
  if (auth && typeof auth.request === 'function') {
    return createRemotePeopleActions(auth.request);
  }
  return createLocalPeopleActions(
    'Sign in to your Floppy server to load person and studio profiles.',
  );
}
