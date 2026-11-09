import { getActiveAuthSession } from './authSession.js';
import { createLocalMusicActions, createRemoteMusicActions } from './musicTransportCore.js';

// The native feature boundary uses the authenticated session when one exists.
// Presentation receives plain values; credentials, CSRF, base URL and error
// handling stay in the request adapter behind this contract.
export function createMusicTransport(options = {}) {
  if (typeof options.request === 'function') {
    return createRemoteMusicActions(options.request);
  }
  const auth = options.auth || getActiveAuthSession();
  if (auth && typeof auth.request === 'function') {
    return createRemoteMusicActions(auth.request);
  }
  return createLocalMusicActions(
    'Sign in to your Floppy server to save music and podcast changes.',
  );
}
