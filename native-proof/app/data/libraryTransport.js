import { getActiveAuthSession } from './authSession.js';
import { loadDatePreferences } from './userDate.js';
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
    const actions = createRemoteLibraryActions(auth.request);
    // Rows print dates in the server zone and the user's format, as the web does.
    return {
      ...actions,
      load: async params => {
        await loadDatePreferences(auth.request);
        return actions.load(params);
      },
    };
  }
  return createLocalLibraryActions(
    'Sign in to your Floppy server to load your library.',
  );
}

export { mediaRowsFromPayload } from './libraryTransportCore.js';