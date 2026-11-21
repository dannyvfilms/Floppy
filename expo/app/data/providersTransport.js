import { getActiveAuthSession } from './authSession.js';
import {
  createLocalProvidersActions,
  createRemoteProvidersActions,
} from './providersTransportCore.js';

export function createProvidersTransport(options = {}) {
  if (typeof options.request === 'function') {
    return createRemoteProvidersActions(options.request);
  }
  const auth = options.auth || getActiveAuthSession();
  if (auth && typeof auth.request === 'function') {
    return createRemoteProvidersActions(auth.request);
  }
  return createLocalProvidersActions('Sign in to your Floppy server to manage providers.');
}

export { detailFromPayload, directoryFromPayload } from './providersTransportCore.js';
