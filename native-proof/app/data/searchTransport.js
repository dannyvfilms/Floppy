import { getActiveAuthSession } from './authSession.js';
import {
  createLocalSearchActions,
  createRemoteSearchActions,
  localResultsFromPayload,
  onlineResultsFromPayload,
} from './searchTransportCore.js';

export function createSearchTransport(options = {}) {
  if (typeof options.request === 'function') {
    return createRemoteSearchActions(options.request);
  }
  const auth = options.auth || getActiveAuthSession();
  if (auth && typeof auth.request === 'function') {
    return createRemoteSearchActions(auth.request);
  }
  return createLocalSearchActions(
    'Sign in to your Floppy server to search your library.',
  );
}

export { localResultsFromPayload, onlineResultsFromPayload };