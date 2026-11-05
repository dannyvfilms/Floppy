import { getActiveAuthSession } from './authSession.js';
import { createLocalListActions, createRemoteListActions } from './listTransportCore.js';

export function createListTransport(options = {}) {
  if (typeof options.request === 'function') {
    return createRemoteListActions(options.request);
  }
  const auth = options.auth || getActiveAuthSession();
  if (auth && typeof auth.request === 'function') {
    return createRemoteListActions(auth.request);
  }
  return createLocalListActions(
    'Sign in to your Floppy server to save list changes.',
  );
}
