import { getActiveAuthSession } from './authSession.js';
import {
  createLocalHistoryActions,
  createRemoteHistoryActions,
} from './historyTransportCore.js';

export function createHistoryTransport(options = {}) {
  if (typeof options.request === 'function') {
    return createRemoteHistoryActions(options.request);
  }
  const auth = options.auth || getActiveAuthSession();
  if (auth && typeof auth.request === 'function') {
    return createRemoteHistoryActions(auth.request);
  }
  return createLocalHistoryActions(
    'Sign in to your Floppy server to load history from the server.',
  );
}

export { historyEntriesFromPayload, historyQuery } from './historyTransportCore.js';
