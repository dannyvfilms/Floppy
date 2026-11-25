import { getActiveAuthSession } from './authSession.js';
import {
  createLocalProvidersActions,
  createRemoteProvidersActions,
} from './providersTransportCore.js';

export function createProvidersTransport(options = {}) {
  if (typeof options.request === 'function') {
    return createRemoteProvidersActions(options.request, options.serverUrl || '');
  }
  const auth = options.auth || getActiveAuthSession();
  if (auth && typeof auth.request === 'function') {
    return createRemoteProvidersActions(auth.request, auth.getState?.()?.serverUrl || auth.serverUrl || '');
  }
  return createLocalProvidersActions('Sign in to your Floppy server to manage providers.');
}

export { detailFromPayload, directoryFromPayload } from './providersTransportCore.js';
