import { getActiveAuthSession } from './authSession.js';
import {
  createLocalHomeActions,
  createRemoteHomeActions,
} from './homeTransportCore.js';

export function createHomeTransport(options = {}) {
  if (typeof options.request === 'function') {
    return createRemoteHomeActions(options.request);
  }
  const auth = options.auth || getActiveAuthSession();
  if (auth && typeof auth.request === 'function') {
    return createRemoteHomeActions(auth.request);
  }
  return createLocalHomeActions(
    'Sign in to your Floppy server to load Home from the server.',
  );
}

export {
  homeQuery,
  homeScreenFromPayload,
  mergeHomeRowPage,
} from './homeTransportCore.js';
