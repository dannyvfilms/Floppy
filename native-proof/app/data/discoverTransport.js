import { getActiveAuthSession } from './authSession.js';
import {
  createLocalDiscoverActions,
  createRemoteDiscoverActions,
  discoverRowsFromPayload,
  hiddenFromPayload,
  mediaOptionsFromNavigation,
} from './discoverTransportCore.js';

export function createDiscoverTransport(options = {}) {
  if (typeof options.request === 'function') {
    return createRemoteDiscoverActions(options.request);
  }
  const auth = options.auth || getActiveAuthSession();
  if (auth && typeof auth.request === 'function') {
    return createRemoteDiscoverActions(auth.request);
  }
  return createLocalDiscoverActions(
    'Sign in to your Floppy server to load Discover from the server.',
  );
}

export {
  discoverRowsFromPayload,
  hiddenFromPayload,
  mediaOptionsFromNavigation,
};