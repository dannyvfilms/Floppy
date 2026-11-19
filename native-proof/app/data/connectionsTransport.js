import { getActiveAuthSession } from './authSession.js';
import {
  createLocalConnectionsActions,
  createRemoteConnectionsActions,
} from './connectionsTransportCore.js';

export function createConnectionsTransport(options = {}) {
  if (typeof options.request === 'function') {
    return createRemoteConnectionsActions(options.request);
  }
  const auth = options.auth || getActiveAuthSession();
  if (auth && typeof auth.request === 'function') {
    return createRemoteConnectionsActions(auth.request);
  }
  return createLocalConnectionsActions('Sign in to your Floppy server to see your connections.');
}

export { connectionsFromPayload, deviceFromPayload } from './connectionsTransportCore.js';
