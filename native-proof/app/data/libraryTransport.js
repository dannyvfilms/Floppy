import { getActiveAuthSession } from './authSession.js';
import {
  createLocalLibraryActions,
  createRemoteLibraryActions,
  mediaRowsFromPayload,
} from './libraryTransportCore.js';

export function createLibraryTransport(options = {}) {
  if (typeof options.request === 'function') {
    return createRemoteLibraryActions(options.request);
  }
  const auth = options.auth || getActiveAuthSession();
  if (auth && typeof auth.request === 'function') {
    return createRemoteLibraryActions(auth.request);
  }
  return createLocalLibraryActions(
    'Sign in to your Floppy server to load your library.',
  );
}

export { mediaRowsFromPayload } from './libraryTransportCore.js';